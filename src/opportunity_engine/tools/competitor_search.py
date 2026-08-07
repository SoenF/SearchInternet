"""Pure helpers for the free, rule-based competitor-saturation check: count
how many existing GitHub repos and npm packages match an opportunity's title
keywords. This is a keyword count against two free, no-approval-needed
registries, not semantic matching -- no LLM anywhere in this module. It
detects developer-tool-shaped competitors well; a consumer app or a service
with no code artifact on GitHub/npm is a documented blind spot, same kind of
honest limitation as the personal-brand-risk warning in scoring_tools.py.
Response shapes verified against live calls to api.github.com/search/
repositories and registry.npmjs.org/-/v1/search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_HN_PREFIX_RE = re.compile(r"^(show|ask|tell)\s+hn\s*:\s*", re.IGNORECASE)


@dataclass(frozen=True)
class CompetitorMatch:
    source: str  # "github" | "npm"
    name: str
    url: str
    popularity: int | None = None  # stars (GitHub) or None (npm has no simple count here)


def build_search_query(title: str) -> str:
    """Strips the "Show HN:"/"Ask HN:"/"Tell HN:" prefix HN titles carry --
    keeping it would search for the literal words "show" and "hn", which is
    noise, not signal. No further NLP: the raw (prefix-stripped) title is the
    query, on purpose -- keyword search against free registries doesn't need
    or benefit from more machinery than that."""
    return _HN_PREFIX_RE.sub("", title).strip()


def parse_github_repo_search(data: dict[str, Any], limit: int = 5) -> list[CompetitorMatch]:
    items = data.get("items", [])
    return [
        CompetitorMatch(
            source="github",
            name=item["full_name"],
            url=item["html_url"],
            popularity=item.get("stargazers_count"),
        )
        for item in items[:limit]
    ]


def parse_npm_search(data: dict[str, Any], limit: int = 5) -> list[CompetitorMatch]:
    objects = data.get("objects", [])
    matches = []
    for obj in objects[:limit]:
        package = obj.get("package", {})
        npm_url = package.get("links", {}).get("npm")
        if not package.get("name") or not npm_url:
            continue
        matches.append(CompetitorMatch(source="npm", name=package["name"], url=npm_url))
    return matches
