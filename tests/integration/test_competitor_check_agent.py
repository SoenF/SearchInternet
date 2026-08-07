"""End-to-end against a real (local Docker) Postgres, with injected fake
GitHub/npm fetchers -- no real network call, consistent with the zero-
network-calls-in-tests rule.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg

from opportunity_engine.agents.competitor_check_agent import run_competitor_check
from opportunity_engine.clock import fixed_clock

AS_OF = datetime(2026, 8, 7, tzinfo=UTC)


def _insert_opportunity(
    conn: psycopg.Connection[Any], *, title: str, current_score: float | None = None
) -> int:
    row = conn.execute(
        """
        INSERT INTO opportunities (title, primary_strategy, status, current_score)
        VALUES (%s, 'pain_driven', 'candidate', %s)
        RETURNING id
        """,
        (title, current_score),
    ).fetchone()
    assert row is not None
    return int(row[0])


_GITHUB_RESPONSE = {
    "total_count": 12,
    "items": [
        {
            "full_name": "someone/csv-budgeter",
            "html_url": "https://github.com/someone/csv-budgeter",
            "stargazers_count": 42,
        }
    ],
}
_NPM_RESPONSE = {
    "total": 3,
    "objects": [
        {
            "package": {
                "name": "csv-budget",
                "links": {"npm": "https://www.npmjs.com/package/csv-budget"},
            }
        }
    ],
}
_EMPTY_GITHUB_RESPONSE = {"total_count": 0, "items": []}
_EMPTY_NPM_RESPONSE = {"total": 0, "objects": []}


def test_check_persists_match_count_and_top_matches(db_conn: psycopg.Connection[Any]) -> None:
    opportunity_id = _insert_opportunity(db_conn, title="CSV budgeting tool")
    db_conn.commit()

    stats = run_competitor_check(
        db_conn,
        github_fetch=lambda query: _GITHUB_RESPONSE,
        npm_fetch=lambda query: _NPM_RESPONSE,
        clock=fixed_clock(AS_OF),
    )

    assert stats.checked == 1
    assert stats.saturated == 1  # 12 + 3 = 15 > default threshold of 5

    match_count, matches, checked_at = db_conn.execute(
        "SELECT competitor_match_count, competitor_matches, competitor_checked_at "
        "FROM opportunities WHERE id = %s",
        (opportunity_id,),
    ).fetchone()
    assert match_count == 15
    assert checked_at == AS_OF
    assert {m["name"] for m in matches} == {"someone/csv-budgeter", "csv-budget"}

    event = db_conn.execute(
        "SELECT event_type, payload FROM events WHERE opportunity_id = %s", (opportunity_id,)
    ).fetchone()
    assert event is not None
    event_type, payload = event
    assert event_type == "competitor_checked"
    assert payload["match_count"] == 15


def test_check_records_zero_when_no_matches_found(db_conn: psycopg.Connection[Any]) -> None:
    opportunity_id = _insert_opportunity(db_conn, title="A genuinely novel idea")
    db_conn.commit()

    run_competitor_check(
        db_conn,
        github_fetch=lambda query: _EMPTY_GITHUB_RESPONSE,
        npm_fetch=lambda query: _EMPTY_NPM_RESPONSE,
        clock=fixed_clock(AS_OF),
    )

    match_count, matches = db_conn.execute(
        "SELECT competitor_match_count, competitor_matches FROM opportunities WHERE id = %s",
        (opportunity_id,),
    ).fetchone()
    assert match_count == 0
    assert matches == []


def test_already_checked_opportunities_are_not_rechecked(db_conn: psycopg.Connection[Any]) -> None:
    opportunity_id = _insert_opportunity(db_conn, title="CSV budgeting tool")
    db_conn.commit()

    calls = []

    def counting_github_fetch(query: str) -> dict[str, Any]:
        calls.append(query)
        return _GITHUB_RESPONSE

    run_competitor_check(
        db_conn,
        github_fetch=counting_github_fetch,
        npm_fetch=lambda query: _NPM_RESPONSE,
        clock=fixed_clock(AS_OF),
    )
    run_competitor_check(
        db_conn,
        github_fetch=counting_github_fetch,
        npm_fetch=lambda query: _NPM_RESPONSE,
        clock=fixed_clock(AS_OF),
    )

    assert len(calls) == 1
    updated = db_conn.execute(
        "SELECT id FROM opportunities WHERE competitor_checked_at IS NULL"
    ).fetchall()
    assert updated == []
    assert opportunity_id  # keep linters happy about the unused-looking variable


def test_batch_size_limits_opportunities_checked_per_run(db_conn: psycopg.Connection[Any]) -> None:
    for i in range(3):
        _insert_opportunity(db_conn, title=f"Idea {i}")
    db_conn.commit()

    stats = run_competitor_check(
        db_conn,
        batch_size=2,
        github_fetch=lambda query: _EMPTY_GITHUB_RESPONSE,
        npm_fetch=lambda query: _EMPTY_NPM_RESPONSE,
        clock=fixed_clock(AS_OF),
    )

    assert stats.checked == 2
    remaining = db_conn.execute(
        "SELECT count(*) FROM opportunities WHERE competitor_checked_at IS NULL"
    ).fetchone()
    assert remaining == (1,)


def test_checks_highest_scored_opportunities_first(db_conn: psycopg.Connection[Any]) -> None:
    low_id = _insert_opportunity(db_conn, title="Low score idea", current_score=1.0)
    high_id = _insert_opportunity(db_conn, title="High score idea", current_score=99.0)
    db_conn.commit()

    stats = run_competitor_check(
        db_conn,
        batch_size=1,
        github_fetch=lambda query: _EMPTY_GITHUB_RESPONSE,
        npm_fetch=lambda query: _EMPTY_NPM_RESPONSE,
        clock=fixed_clock(AS_OF),
    )

    assert stats.checked == 1
    checked_at_high = db_conn.execute(
        "SELECT competitor_checked_at FROM opportunities WHERE id = %s", (high_id,)
    ).fetchone()[0]
    checked_at_low = db_conn.execute(
        "SELECT competitor_checked_at FROM opportunities WHERE id = %s", (low_id,)
    ).fetchone()[0]
    assert checked_at_high is not None
    assert checked_at_low is None


def test_one_source_failing_does_not_block_the_other(db_conn: psycopg.Connection[Any]) -> None:
    opportunity_id = _insert_opportunity(db_conn, title="CSV budgeting tool")
    db_conn.commit()

    def failing_github_fetch(query: str) -> dict[str, Any]:
        raise RuntimeError("simulated GitHub outage")

    run_competitor_check(
        db_conn,
        github_fetch=failing_github_fetch,
        npm_fetch=lambda query: _NPM_RESPONSE,
        clock=fixed_clock(AS_OF),
    )

    match_count, checked_at = db_conn.execute(
        "SELECT competitor_match_count, competitor_checked_at FROM opportunities WHERE id = %s",
        (opportunity_id,),
    ).fetchone()
    assert match_count == 3  # npm's contribution alone; GitHub's failure counted as 0, not fatal
    assert checked_at is not None
