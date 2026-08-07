"""Wikipedia pageviews_series documents expand into wikipedia_pageviews_daily
rows -- the table momentum math actually reads -- on top of the generic
raw_documents audit trail every connector gets.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from opportunity_engine.agents.ingestion_agent import run_ingestion
from opportunity_engine.clock import fixed_clock
from opportunity_engine.collectors.wikipedia_pageviews import WikipediaPageviewsCollector
from opportunity_engine.domain.models import TrackedTopic

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "wikipedia"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())  # type: ignore[no-any-return]


def test_run_ingestion_expands_wikipedia_series_into_daily_rows(
    db_conn: psycopg.Connection[Any],
) -> None:
    response = _load("pageviews_response.json")

    def fake_fetch(url: str, headers: dict[str, str]) -> dict[str, Any]:
        return response

    collector = WikipediaPageviewsCollector(
        topics=[TrackedTopic(project="en.wikipedia", article="ChatGPT")],
        user_agent="OpportunityEngine/0.1 (contact: davide@vamur.com)",
        fetch=fake_fetch,
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    run_ingestion(
        db_conn,
        [collector],
        since=datetime(2025, 1, 1, tzinfo=UTC),
        until=datetime(2025, 1, 10, tzinfo=UTC),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    audit_count = db_conn.execute(
        "SELECT count(*) FROM raw_documents WHERE doc_type = 'wikipedia_pageviews_series'"
    ).fetchone()
    assert audit_count == (1,)

    daily_rows = db_conn.execute(
        "SELECT pageview_date, views FROM wikipedia_pageviews_daily "
        "WHERE project = 'en.wikipedia' AND article = 'ChatGPT' ORDER BY pageview_date"
    ).fetchall()
    assert len(daily_rows) == len(response["items"])
    assert daily_rows[0][1] == response["items"][0]["views"]
