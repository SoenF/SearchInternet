"""Fixture-driven: catches our own parser regressing against a known-good
recorded response shape. Does not detect the live API changing shape --
scripts/refresh_fixtures.py is the (manual, non-CI) tool for that.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opportunity_engine.clock import fixed_clock
from opportunity_engine.collectors.hackernews import HackerNewsCollector

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "hackernews"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())  # type: ignore[no-any-return]


def _make_fetch(ask_response: dict[str, Any], show_response: dict[str, Any]):
    def fake_fetch(url: str, params: dict[str, Any]) -> dict[str, Any]:
        if params["page"] > 0:
            return {"hits": [], "nbPages": 1}
        return ask_response if params["tags"] == "ask_hn" else show_response

    return fake_fetch


def test_collect_yields_ask_and_show_hn_documents() -> None:
    ask_response = _load("search_by_date_ask_hn.json")
    show_response = _load("search_by_date_show_hn.json")
    collector = HackerNewsCollector(
        fetch=_make_fetch(ask_response, show_response),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )

    assert len(docs) == len(ask_response["hits"]) + len(show_response["hits"])
    assert {d.doc_type for d in docs} == {"hn_ask", "hn_show"}
    assert all(d.connector_name == "hackernews_algolia" for d in docs)
    assert all(d.fetched_at == datetime(2026, 8, 7, tzinfo=UTC) for d in docs)

    show_launch_urls = [d.source_url for d in docs if d.doc_type == "hn_show"]
    assert any(url and "chatmcp.pro" in url for url in show_launch_urls)


def test_collect_skips_a_single_malformed_hit_without_raising() -> None:
    ask_response = copy.deepcopy(_load("search_by_date_ask_hn.json"))
    ask_response["hits"].append({"title": "missing objectID and created_at_i"})
    show_response = _load("search_by_date_show_hn.json")
    collector = HackerNewsCollector(
        fetch=_make_fetch(ask_response, show_response),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )

    # the malformed hit is skipped; the well-formed ones on either side still come through
    assert len(docs) == len(ask_response["hits"]) - 1 + len(show_response["hits"])
