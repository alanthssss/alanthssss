#!/usr/bin/env python3
"""
update_readme.py

Fetches pinned repositories and recent public repositories for the GitHub user
'alanthssss', then updates the README.md sections delimited by HTML comment
markers:

  <!-- PINNED-REPOS:START --> ... <!-- PINNED-REPOS:END -->
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
GRAPHQL_URL = "https://api.github.com/graphql"
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


def graphql_query(token: str, query: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = requests.post(GRAPHQL_URL, json={"query": query}, headers=headers, timeout=15)
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        print(f"GraphQL errors: {data['errors']}", file=sys.stderr)
        sys.exit(1)
    return data


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

PINNED_QUERY = """
{
  user(login: "%s") {
    pinnedItems(first: 6, types: REPOSITORY) {
      nodes {
        ... on Repository {
          name
          nameWithOwner
          description
          url
          primaryLanguage { name }
        }
      }
    }
  }
}
""" % GITHUB_USERNAME


def fetch_pinned_repos(token: str) -> list[dict]:
    data = graphql_query(token, PINNED_QUERY)
    nodes = data.get("data", {}).get("user", {}).get("pinnedItems", {}).get("nodes", [])
    return [n for n in nodes if n]  # filter out nulls


def fetch_recent_repos(token: str) -> list[dict]:
    repos = rest_get(
        token,
        f"/users/{GITHUB_USERNAME}/repos",
        params={"sort": "updated", "direction": "desc", "per_page": MAX_RECENT, "type": "owner"},
    )
    # Exclude the profile README repo itself
    return [r for r in repos if r["name"] != GITHUB_USERNAME][:MAX_RECENT]


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def language_badge(lang: str | None) -> str:
    return lang if lang else "—"


def escape_md_pipes(text: str) -> str:
    """Escape pipe characters so they don't break Markdown table cells."""
    return text.replace("|", "\\|")


def render_pinned_table(repos: list[dict]) -> str:
    if not repos:
        return "_No pinned repositories found._\n"
    lines = [
        "| Project | Description | Stack |",
        "|---------|-------------|-------|",
    ]
    for repo in repos:
        name_with_owner = repo.get("nameWithOwner", "")
        url = repo.get("url") or f"https://github.com/{name_with_owner}"
        desc = escape_md_pipes(repo.get("description") or "")
        lang = language_badge(
            (repo.get("primaryLanguage") or {}).get("name")
        )
        lines.append(f"| [{name_with_owner}]({url}) | {desc} | {lang} |")
    return "\n".join(lines) + "\n"


def render_recent_table(repos: list[dict]) -> str:
    if not repos:
        return "_No public repositories found._\n"
    lines = [
        "| Project | Description | Stack | Updated |",
        "|---------|-------------|-------|---------|",
    ]
    for repo in repos:
        name = repo.get("name", "")
        url = repo.get("html_url", f"https://github.com/{GITHUB_USERNAME}/{name}")
        desc = escape_md_pipes(repo.get("description") or "")
        lang = language_badge(repo.get("language"))
        updated_raw = repo.get("updated_at", "")
        try:
            updated = datetime.fromisoformat(updated_raw.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            updated = updated_raw[:10] if updated_raw else "—"
        lines.append(f"| [{name}]({url}) | {desc} | {lang} | {updated} |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# README patching
# ---------------------------------------------------------------------------

def replace_section(content: str, start_marker: str, end_marker: str, new_body: str) -> str:
    pattern = re.compile(
        rf"({re.escape(start_marker)}\n).*?(\n{re.escape(end_marker)})",
        re.DOTALL,
    )
    replacement = rf"\g<1>{new_body}\g<2>"
    result, count = pattern.subn(replacement, content)
    if count == 0:
        print(f"WARNING: marker '{start_marker}' not found in README.", file=sys.stderr)
    return result


def update_readme(pinned: list[dict], recent: list[dict]) -> bool:
    """Return True if the file was changed."""
    readme_path = os.path.abspath(README_PATH)
    with open(readme_path, encoding="utf-8") as f:
        original = f.read()

    content = original
    content = replace_section(
        content,
        "<!-- PINNED-REPOS:START -->",
        "<!-- PINNED-REPOS:END -->",
        render_pinned_table(pinned),
    )
    content = replace_section(
        content,
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
    print(f"Fetching pinned repos for @{GITHUB_USERNAME}...")
    pinned = fetch_pinned_repos(token)
    print(f"  Found {len(pinned)} pinned repo(s).")

    print(f"Fetching {MAX_RECENT} most-recently-updated repos for @{GITHUB_USERNAME}...")
    recent = fetch_recent_repos(token)
    print(f"  Found {len(recent)} repo(s).")

    update_readme(pinned, recent)


if __name__ == "__main__":
    main()
