"""Validates the full path: fixture -> collector -> parse -> DB insert ->
connector_runs -> event, against a real (local Docker) Postgres.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from opportunity_engine.agents.ingestion_agent import run_ingestion
from opportunity_engine.clock import fixed_clock
from opportunity_engine.collectors.hackernews import HackerNewsCollector

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "hackernews"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())  # type: ignore[no-any-return]


def test_run_ingestion_persists_documents_run_stats_and_event(
    db_conn: psycopg.Connection[Any],
) -> None:
    ask_response = _load("search_by_date_ask_hn.json")
    show_response = _load("search_by_date_show_hn.json")

    def fake_fetch(url: str, params: dict[str, Any]) -> dict[str, Any]:
        if params["page"] > 0:
            return {"hits": [], "nbPages": 1}
        return ask_response if params["tags"] == "ask_hn" else show_response

    collector = HackerNewsCollector(
        fetch=fake_fetch, clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC))
    )

    result = run_ingestion(
        db_conn,
        [collector],
        since=datetime(2025, 1, 1, tzinfo=UTC),
        until=datetime(2025, 1, 2, tzinfo=UTC),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    expected_count = len(ask_response["hits"]) + len(show_response["hits"])
    assert result == {"hackernews_algolia": expected_count}

    stored_count = db_conn.execute(
        "SELECT count(*) FROM raw_documents WHERE connector_name = 'hackernews_algolia'"
    ).fetchone()
    assert stored_count == (expected_count,)

    run_row = db_conn.execute(
        "SELECT status, items_fetched, items_stored FROM connector_runs "
        "WHERE connector_name = 'hackernews_algolia'"
    ).fetchone()
    assert run_row == ("success", expected_count, expected_count)

    event_row = db_conn.execute(
        "SELECT event_type, payload FROM events WHERE connector_name = 'hackernews_algolia'"
    ).fetchone()
    assert event_row is not None
    assert event_row[0] == "document_ingested"
    assert event_row[1] == {
        "items_fetched": expected_count,
        "items_stored": expected_count,
        "status": "success",
    }

    manifest_row = db_conn.execute(
        "SELECT tos_status, enabled FROM connectors WHERE name = 'hackernews_algolia'"
    ).fetchone()
    assert manifest_row == ("compliant", True)


def test_run_ingestion_reingesting_upserts_without_duplicating(
    db_conn: psycopg.Connection[Any],
) -> None:
    ask_response = _load("search_by_date_ask_hn.json")

    def fake_fetch(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return (
            {"hits": [], "nbPages": 1}
            if params["page"] > 0 or params["tags"] != "ask_hn"
            else ask_response
        )

    clock = fixed_clock(datetime(2026, 8, 7, tzinfo=UTC))
    make_collector = lambda: HackerNewsCollector(fetch=fake_fetch, clock=clock)

    run_ingestion(
        db_conn,
        [make_collector()],
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 2, tzinfo=UTC),
        clock=clock,
    )
    run_ingestion(
        db_conn,
        [make_collector()],
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 2, tzinfo=UTC),
        clock=clock,
    )

    stored_count = db_conn.execute(
        "SELECT count(*) FROM raw_documents WHERE connector_name = 'hackernews_algolia'"
    ).fetchone()
    assert stored_count == (len(ask_response["hits"]),)
