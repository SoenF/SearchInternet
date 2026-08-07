"""Fixture-driven against real captured responses (verified live calls to
api.github.com/search/repositories and registry.npmjs.org/-/v1/search).
No LLM, no network in this test -- pure parsing only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opportunity_engine.tools.competitor_search import (
    build_search_query,
    parse_github_repo_search,
    parse_npm_search,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "competitor_search"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())  # type: ignore[no-any-return]


def test_build_search_query_strips_show_hn_prefix() -> None:
    assert build_search_query("Show HN: my new CSV importer") == "my new CSV importer"


def test_build_search_query_strips_ask_hn_prefix_case_insensitively() -> None:
    assert build_search_query("ask hn: is there a tool for X?") == "is there a tool for X?"


def test_build_search_query_strips_tell_hn_prefix() -> None:
    assert build_search_query("Tell HN: something happened") == "something happened"


def test_build_search_query_leaves_untitled_text_alone() -> None:
    assert build_search_query("CloudQuell") == "CloudQuell"


def test_parse_github_repo_search_extracts_name_url_and_stars() -> None:
    data = _load("github_repo_search.json")
    matches = parse_github_repo_search(data)

    assert len(matches) == len(data["items"])
    assert all(m.source == "github" for m in matches)
    first = matches[0]
    assert first.name == data["items"][0]["full_name"]
    assert first.url == data["items"][0]["html_url"]
    assert first.popularity == data["items"][0]["stargazers_count"]


def test_parse_github_repo_search_respects_limit() -> None:
    data = _load("github_repo_search.json")
    matches = parse_github_repo_search(data, limit=1)
    assert len(matches) == 1


def test_parse_npm_search_extracts_name_and_npm_url() -> None:
    data = _load("npm_search.json")
    matches = parse_npm_search(data)

    assert len(matches) == len(data["objects"])
    assert all(m.source == "npm" for m in matches)
    first = matches[0]
    assert first.name == data["objects"][0]["package"]["name"]
    assert first.url == data["objects"][0]["package"]["links"]["npm"]


def test_parse_npm_search_skips_packages_with_no_npm_link() -> None:
    data = {"objects": [{"package": {"name": "weird-package", "links": {}}}]}
    assert parse_npm_search(data) == []
