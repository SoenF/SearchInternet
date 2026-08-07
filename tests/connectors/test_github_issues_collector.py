"""Fixture-driven: catches our own parser regressing against a known-good
recorded response shape. Does not detect the live API changing shape --
scripts/refresh_fixtures.py is the (manual, non-CI) tool for that. Mirrors
tests/connectors/test_hackernews_collector.py.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opportunity_engine.clock import fixed_clock
from opportunity_engine.collectors.github_issues import GitHubIssuesCollector

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "github_issues"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())  # type: ignore[no-any-return]


def _make_fetch(response: dict[str, Any]):
    """The real captured fixture has a huge real-world total_count (millions
    of matching issues genuinely exist live) -- only return it on page 1, an
    empty page after, so tests that don't care about pagination don't loop
    until GitHubIssuesCollector's own 1000-result cap."""

    def fake_fetch(url: str, params: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        assert "created:" in params["q"]
        if params["page"] > 1:
            return {"items": [], "total_count": response.get("total_count", 0)}
        return response

    return fake_fetch


def test_collect_yields_github_issue_documents() -> None:
    response = _load("search_issues.json")
    collector = GitHubIssuesCollector(
        fetch=_make_fetch(response), clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC))
    )

    docs = list(
        collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )

    assert len(docs) == len(response["items"])
    assert all(d.doc_type == "github_issue" for d in docs)
    assert all(d.connector_name == "github_issues" for d in docs)
    assert all(d.fetched_at == datetime(2026, 8, 7, tzinfo=UTC) for d in docs)

    idempotence_doc = next(d for d in docs if "idempotence" in (d.title or ""))
    assert idempotence_doc.category == "enhancement"
    assert idempotence_doc.external_id.endswith("#12")


def test_collect_skips_a_single_malformed_issue_without_raising() -> None:
    response = copy.deepcopy(_load("search_issues.json"))
    response["items"].append({"title": "missing repository_url, number, created_at"})
    collector = GitHubIssuesCollector(
        fetch=_make_fetch(response), clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC))
    )

    docs = list(
        collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )

    # the malformed item is skipped; the well-formed ones on either side still come through
    assert len(docs) == len(response["items"]) - 1


def test_collect_sends_bearer_token_when_configured() -> None:
    captured_headers: dict[str, str] = {}

    def fake_fetch(url: str, params: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        captured_headers.update(headers)
        return {"items": [], "total_count": 0}

    collector = GitHubIssuesCollector(token="my-token", fetch=fake_fetch)
    list(collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)))

    assert captured_headers["Authorization"] == "Bearer my-token"


def test_collect_omits_authorization_header_without_a_token() -> None:
    captured_headers: dict[str, str] = {}

    def fake_fetch(url: str, params: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        captured_headers.update(headers)
        return {"items": [], "total_count": 0}

    collector = GitHubIssuesCollector(fetch=fake_fetch)
    list(collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)))

    assert "Authorization" not in captured_headers
