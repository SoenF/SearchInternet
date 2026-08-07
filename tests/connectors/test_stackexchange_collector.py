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
from opportunity_engine.collectors.stackexchange import StackExchangeCollector

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "stackexchange"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())  # type: ignore[no-any-return]


def _make_fetch(response: dict[str, Any]):
    """The real captured fixture has has_more=true (more results genuinely
    exist live) -- only return it on page 1, an empty/exhausted page after,
    so tests that don't care about pagination don't loop forever."""

    def fake_fetch(url: str, params: dict[str, Any]) -> dict[str, Any]:
        assert params["site"] == "softwarerecs"
        if params["page"] > 1:
            return {"items": [], "has_more": False}
        return response

    return fake_fetch


def test_collect_yields_stackexchange_documents() -> None:
    response = _load("questions_softwarerecs.json")
    collector = StackExchangeCollector(
        sites=frozenset({"softwarerecs"}),
        fetch=_make_fetch(response),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )

    assert len(docs) == len(response["items"])
    assert all(d.doc_type == "stackexchange_question" for d in docs)
    assert all(d.connector_name == "stackexchange" for d in docs)
    assert all(d.fetched_at == datetime(2026, 8, 7, tzinfo=UTC) for d in docs)

    htmx_doc = next(d for d in docs if "HTMX-aware" in (d.title or ""))
    assert htmx_doc.category == "windows"
    assert "minimalist" in (htmx_doc.body or "")
    assert "<p>" not in (htmx_doc.body or "")  # HTML stripped


def test_collect_skips_a_single_malformed_question_without_raising() -> None:
    response = copy.deepcopy(_load("questions_softwarerecs.json"))
    response["items"].append({"title": "missing question_id and creation_date"})
    collector = StackExchangeCollector(
        sites=frozenset({"softwarerecs"}),
        fetch=_make_fetch(response),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )

    # the malformed item is skipped; the well-formed ones on either side still come through
    assert len(docs) == len(response["items"]) - 1


def test_collect_paginates_until_has_more_is_false() -> None:
    items = _load("questions_softwarerecs.json")["items"]
    first_page = {"items": [items[0]], "has_more": True}
    second_page = {"items": items[1:], "has_more": False}

    def fake_fetch(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return second_page if params["page"] == 2 else first_page

    collector = StackExchangeCollector(
        sites=frozenset({"softwarerecs"}),
        fetch=fake_fetch,
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )

    assert len(docs) == len(items)


def test_collect_includes_api_key_when_configured() -> None:
    captured_params: dict[str, Any] = {}

    def fake_fetch(url: str, params: dict[str, Any]) -> dict[str, Any]:
        captured_params.update(params)
        return {"items": [], "has_more": False}

    collector = StackExchangeCollector(
        sites=frozenset({"softwarerecs"}), api_key="my-key", fetch=fake_fetch
    )
    list(collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)))

    assert captured_params["key"] == "my-key"
