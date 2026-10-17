"""Refresh the "Featured projects" table in README.md from the GitHub API.

Runs in GitHub Actions (see .github/workflows/update-readme.yml), so every new
public repository appears on the profile without editing the README by hand.
Standard library only.

Environment variables
---------------------
GITHUB_USER   account to list (Actions sets GITHUB_REPOSITORY_OWNER)
GITHUB_TOKEN  optional; raises the API rate limit
FEATURED      optional comma-separated repo names to show first, in order
EXCLUDE       optional comma-separated repo names to hide
MAX_REPOS     how many rows to show (default 8)
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

START = "<!-- REPOS:START -->"
END = "<!-- REPOS:END -->"
README = Path(__file__).resolve().parents[1] / "README.md"


def fetch_repos(user: str, token: str | None = None) -> list[dict]:
    url = f"https://api.github.com/users/{user}/repos?type=owner&sort=pushed&per_page=100"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-readme-updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    req = urllib.request.Request(url, headers=headers)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def select_repos(
    repos: list[dict],
    user: str,
    featured: list[str] | None = None,
    exclude: list[str] | None = None,
    limit: int = 8,
) -> list[dict]:
    """Public, non-fork, non-archived repos; featured first, then by stars and recency."""
    hidden = {user.lower(), *(n.lower() for n in exclude or [])}
    pool = [
        r
        for r in repos
        if not r.get("fork")
        and not r.get("archived")
        and not r.get("private")
        and r["name"].lower() not in hidden
    ]
    order = [n.lower() for n in featured or []]
    first = sorted(
        (r for r in pool if r["name"].lower() in order),
        key=lambda r: order.index(r["name"].lower()),
    )
    rest = [r for r in pool if r["name"].lower() not in order]
    rest.sort(key=lambda r: r.get("pushed_at") or "", reverse=True)
    rest.sort(key=lambda r: r.get("stargazers_count", 0), reverse=True)  # stable
    return (first + rest)[:limit]


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_table(repos: list[dict]) -> str:
    if not repos:
        return "_Projects coming soon._"
    lines = ["| Project | What it does | Built with |", "|---|---|---|"]
    for r in repos:
        name = f"[**{r['name']}**]({r['html_url']})"
        stars = r.get("stargazers_count", 0)
        if stars:
            name += f" ★{stars}"
        desc = _cell(r.get("description") or "")
        tech = [r["language"]] if r.get("language") else []
        tech += [f"`{t}`" for t in (r.get("topics") or [])[:3]]
        lines.append(f"| {name} | {desc} | {' '.join(tech)} |")
    return "\n".join(lines)


def replace_section(readme: str, content: str) -> str:
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(readme):
        raise ValueError(f"README is missing the {START} / {END} markers")
    return pattern.sub(lambda _: f"{START}\n{content}\n{END}", readme)


def _csv(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


def main(readme: Path = README) -> int:
    user = os.environ.get("GITHUB_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER")
    if not user:
        print("Set GITHUB_USER", file=sys.stderr)
        return 2
    repos = fetch_repos(user, os.environ.get("GITHUB_TOKEN"))
    chosen = select_repos(
        repos,
        user,
        featured=_csv("FEATURED"),
        exclude=_csv("EXCLUDE"),
        limit=int(os.environ.get("MAX_REPOS") or "8"),
    )
    old = readme.read_text(encoding="utf-8")
    new = replace_section(old, render_table(chosen))
    if new != old:
        readme.write_text(new, encoding="utf-8")
        print(f"README updated with {len(chosen)} repositories")
    else:
        print("README already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
