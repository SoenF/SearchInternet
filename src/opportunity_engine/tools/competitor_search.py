"""Pure helpers for the free, rule-based competitor-saturation check: count
how many existing GitHub repos and npm packages match an opportunity's
keywords. This is a keyword count against two free, no-approval-needed
registries, not semantic matching -- no LLM anywhere in this module. It
detects developer-tool-shaped competitors well; a consumer app or a service
with no code artifact on GitHub/npm is a documented blind spot, same kind of
honest limitation as the personal-brand-risk warning in scoring_tools.py.
Response shapes verified against live calls to api.github.com/search/
repositories and registry.npmjs.org/-/v1/search.

`build_search_query` prefers a tagline (the first line of a linked
document's body -- a good proxy for "one-line pitch" across Product Hunt,
HN Show, and app-review sources alike) over the bare title, and strips
dollar amounts/MRR-ARR jargon/HN-meta words. This is a real fix, not
speculative: verified against production data on 2026-08-07 that the naive
title-only version produced two failure modes -- a made-up brand name
("CloudQuell") searches as 0 matches (not "no competitors," just "nothing
to search for"), and a title containing "$17K to $170K MRR" pulled in noise
unrelated to the actual product. Still fundamentally a keyword heuristic,
not language understanding -- an unusual tagline or an HN title with no
tagline at all can still produce a weak query; that residual limitation is
accepted, not solved, the same way the buildability/vendability gates
accept theirs elsewhere in this codebase."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_HN_PREFIX_RE = re.compile(r"^(show|ask|tell)\s+hn\s*:\s*", re.IGNORECASE)
_CURRENCY_OR_METRIC_RE = re.compile(
    r"\$\s?\d[\d,.]*\s?[kmb]?\b|\b\d[\d,.]*\s?[kmb]?\s?(mrr|arr)\b|\bmrr\b|\barr\b",
    re.IGNORECASE,
)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "for",
        "with",
        "of",
        "in",
        "on",
        "to",
        "from",
        "i",
        "we",
        "our",
        "my",
        "your",
        "how",
        "what",
        "why",
        "just",
        "went",
        "built",
        "launched",
        "broke",
        "down",
        "is",
        "are",
        "be",
        "it",
        "this",
        "that",
    }
)
_MAX_QUERY_WORDS = 8


@dataclass(frozen=True)
class CompetitorMatch:
    source: str  # "github" | "npm"
    name: str
    url: str
    popularity: int | None = None  # stars (GitHub) or None (npm has no simple count here)


def _clean(text: str) -> str:
    text = _HN_PREFIX_RE.sub("", text)
    text = _CURRENCY_OR_METRIC_RE.sub("", text)
    words = [w for w in re.findall(r"[A-Za-z']+", text) if w.lower() not in _STOPWORDS]
    return " ".join(words[:_MAX_QUERY_WORDS])


def build_search_query(title: str, tagline: str | None = None) -> str:
    """`tagline` should be the first line of the opportunity's linked body
    text, if any -- e.g. a Product Hunt tagline ("Single ledger for your
    cloud and AI spend") is far better search material than a brand name
    ("CloudQuell") alone. Falls back to the (cleaned) title when there's no
    tagline, or when cleaning the tagline leaves nothing usable."""
    cleaned_title = _clean(title)
    if tagline:
        cleaned_tagline = _clean(tagline)
        if cleaned_tagline:
            return cleaned_tagline
    return cleaned_title or title.strip()


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
