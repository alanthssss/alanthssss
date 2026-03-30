#!/usr/bin/env python3
"""
update_readme.py

Fetches recent public repositories from the GitHub user 'alanthssss' personal
account AND from every organization they publicly belong to, then updates the
README.md section delimited by HTML comment markers:

  <!-- RECENT-PROJECTS:START --> ... <!-- RECENT-PROJECTS:END -->

Required environment variable:
  GH_TOKEN  – A GitHub personal access token (or the built-in GITHUB_TOKEN)
               with at least `public_repo` and `read:user` scopes.

Usage:
  python scripts/update_readme.py
"""

import os
import re
import sys
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITHUB_USERNAME = "alanthssss"
README_PATH = os.path.join(os.path.dirname(__file__), "..", "README.md")
REST_URL = "https://api.github.com"
MAX_RECENT = 6  # number of recent repos to list


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_token() -> str:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GH_TOKEN or GITHUB_TOKEN environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    return token


def rest_get(token: str, path: str, params: dict | None = None) -> list | dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    response = requests.get(f"{REST_URL}{path}", headers=headers, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_user_orgs(token: str) -> list[str]:
    """Return login names of organisations the user publicly belongs to."""
    orgs = rest_get(token, f"/users/{GITHUB_USERNAME}/orgs")
    return [org["login"] for org in orgs]


def fetch_recent_repos(token: str) -> list[dict]:
    """Return up to MAX_RECENT most-recently-updated public repos across the
    user's personal account and every org they publicly belong to."""

    # Personal repos (owner type only, large page to have enough candidates)
    personal: list[dict] = rest_get(
        token,
        f"/users/{GITHUB_USERNAME}/repos",
        params={"sort": "updated", "direction": "desc", "per_page": 50, "type": "owner"},
    )

    # Repos from each publicly-visible organisation membership
    org_repos: list[dict] = []
    for org in fetch_user_orgs(token):
        try:
            repos = rest_get(
                token,
                f"/orgs/{org}/repos",
                params={"type": "public", "sort": "updated", "direction": "desc", "per_page": MAX_RECENT},
            )
            org_repos.extend(repos)
        except Exception as exc:
            print(f"WARNING: could not fetch repos for org '{org}': {exc}", file=sys.stderr)

    # Merge, deduplicate by full_name, sort newest-first, drop the profile repo
    all_repos: dict[str, dict] = {r["full_name"]: r for r in personal + org_repos}
    sorted_repos = sorted(
        all_repos.values(),
        key=lambda r: r.get("updated_at", ""),
        reverse=True,
    )
    return [r for r in sorted_repos if r["name"] != GITHUB_USERNAME][:MAX_RECENT]


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def language_badge(lang: str | None) -> str:
    return lang if lang else "—"


def escape_md_pipes(text: str) -> str:
    """Escape pipe characters so they don't break Markdown table cells."""
    return text.replace("|", "\\|")


def render_recent_table(repos: list[dict]) -> str:
    if not repos:
        return "_No public repositories found._\n"
    lines = [
        "| Project | Description | Stack | Updated |",
        "|---------|-------------|-------|---------|",
    ]
    for repo in repos:
        full_name = repo.get("full_name", repo.get("name", ""))
        url = repo.get("html_url", f"https://github.com/{full_name}")
        desc = escape_md_pipes(repo.get("description") or "")
        lang = language_badge(repo.get("language"))
        updated_raw = repo.get("updated_at", "")
        try:
            updated = datetime.fromisoformat(updated_raw.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            updated = updated_raw[:10] if updated_raw else "—"
        lines.append(f"| [{full_name}]({url}) | {desc} | {lang} | {updated} |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# README patching
# ---------------------------------------------------------------------------

def replace_section(content: str, start_marker: str, end_marker: str, new_body: str) -> str:
    pattern = re.compile(
        rf"({re.escape(start_marker)}\n).*?(\n{re.escape(end_marker)})",
        re.DOTALL,
    )
    replacement = lambda m: m.group(1) + new_body + m.group(2)
    result, count = pattern.subn(replacement, content)
    if count == 0:
        print(f"WARNING: marker '{start_marker}' not found in README.", file=sys.stderr)
    return result


def update_readme(recent: list[dict]) -> bool:
    """Return True if the file was changed."""
    readme_path = os.path.abspath(README_PATH)
    with open(readme_path, encoding="utf-8") as f:
        original = f.read()

    content = replace_section(
        original,
        "<!-- RECENT-PROJECTS:START -->",
        "<!-- RECENT-PROJECTS:END -->",
        render_recent_table(recent),
    )

    if content == original:
        print("README is already up-to-date.")
        return False

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("README updated successfully.")
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    token = get_token()
    print(f"Fetching {MAX_RECENT} most-recently-updated repos for @{GITHUB_USERNAME} (personal + org)...")
    recent = fetch_recent_repos(token)
    print(f"  Found {len(recent)} repo(s).")

    update_readme(recent)


if __name__ == "__main__":
    main()
