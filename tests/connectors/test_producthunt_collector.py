"""Fixture-driven, with an important caveat this project's other connector
tests don't have: `tests/fixtures/producthunt/posts_page.json` is a
hand-constructed fixture, not a captured live response -- the Product Hunt
v2 API requires an OAuth/developer bearer token for every single request
(no anonymous tier), which this build environment does not have. Field
names and nesting were verified against the public schema at
github.com/producthunt/producthunt-api/blob/master/schema.graphql instead
of a live call. This test therefore only proves the parser handles the
documented shape correctly, not that the live API still matches it --
run scripts/refresh_fixtures.py with a real token to check that periodically.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opportunity_engine.clock import fixed_clock
from opportunity_engine.collectors.producthunt import ProductHuntCollector

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "producthunt"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())  # type: ignore[no-any-return]


def _make_fetch(page: dict[str, Any]):
    def fake_fetch(variables: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        if variables.get("after") is not None:
            return {"data": {"posts": {"edges": [], "pageInfo": {"hasNextPage": False}}}}
        return page

    return fake_fetch


def test_collect_yields_producthunt_documents() -> None:
    page = _load("posts_page.json")
    collector = ProductHuntCollector(
        fetch=_make_fetch(page), clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC))
    )

    docs = list(
        collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )

    edges = page["data"]["posts"]["edges"]
    assert len(docs) == len(edges)
    assert all(d.doc_type == "producthunt_post" for d in docs)
    assert all(d.connector_name == "producthunt" for d in docs)
    assert all(d.fetched_at == datetime(2026, 8, 7, tzinfo=UTC) for d in docs)

    invoiceflow = next(d for d in docs if d.external_id == "700001")
    assert invoiceflow.title == "InvoiceFlow"
    assert invoiceflow.category == "Fintech"
    assert "Reconcile invoices" in (invoiceflow.body or "")

    ticket_tagger = next(d for d in docs if d.external_id == "700002")
    assert "$4k MRR" in (ticket_tagger.body or "")


def test_collect_skips_a_single_malformed_post_without_raising() -> None:
    page = copy.deepcopy(_load("posts_page.json"))
    page["data"]["posts"]["edges"].append({"node": {"name": "missing id and createdAt"}})
    collector = ProductHuntCollector(
        fetch=_make_fetch(page), clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC))
    )

    docs = list(
        collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )

    assert len(docs) == 2  # the malformed edge is skipped, the two well-formed ones survive


def test_collect_paginates_until_has_next_page_is_false() -> None:
    first_page = {
        "data": {
            "posts": {
                "edges": [_load("posts_page.json")["data"]["posts"]["edges"][0]],
                "pageInfo": {"hasNextPage": True, "endCursor": "cursor1"},
            }
        }
    }
    second_page = {
        "data": {
            "posts": {
                "edges": [_load("posts_page.json")["data"]["posts"]["edges"][1]],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
    }

    def fake_fetch(variables: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        return second_page if variables.get("after") == "cursor1" else first_page

    collector = ProductHuntCollector(
        fetch=fake_fetch, clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC))
    )

    docs = list(
        collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )

    assert {d.external_id for d in docs} == {"700001", "700002"}
