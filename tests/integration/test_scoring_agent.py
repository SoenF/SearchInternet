"""End-to-end scoring against a real (local Docker) Postgres: seeds
opportunities + linked raw_documents directly (bypassing DedupAgent, which is
already covered by its own integration tests), then runs the scoring agent
and inspects opportunities/score_history/proof_events/opportunity_daily_signal.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from opportunity_engine.agents.scoring_agent import run_scoring
from opportunity_engine.clock import fixed_clock

AS_OF = datetime(2026, 8, 7, tzinfo=UTC)


def _ensure_connector(conn: psycopg.Connection[Any], name: str) -> None:
    conn.execute(
        """
        INSERT INTO connectors (name, source_description, source_url, quota_description,
                                 tos_url, tos_status, last_verified)
        VALUES (%s, 'test', 'http://test', 'test', 'http://test', 'compliant', '2026-08-07')
        ON CONFLICT (name) DO NOTHING
        """,
        (name,),
    )


def _insert_opportunity(
    conn: psycopg.Connection[Any], *, strategy: str, title: str = "Test opportunity"
) -> int:
    row = conn.execute(
        """
        INSERT INTO opportunities (title, primary_strategy, status)
        VALUES (%s, %s, 'candidate')
        RETURNING id
        """,
        (title, strategy),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _link_document(
    conn: psycopg.Connection[Any],
    opportunity_id: int,
    *,
    connector_name: str,
    external_id: str,
    doc_type: str,
    title: str | None = None,
    body: str | None = None,
    country_code: str | None = None,
    category: str | None = None,
    fetched_at: datetime = AS_OF,
    published_at: datetime | None = None,
    raw_json: dict[str, Any] | None = None,
) -> int:
    _ensure_connector(conn, connector_name)
    row = conn.execute(
        """
        INSERT INTO raw_documents
            (connector_name, external_id, doc_type, fetched_at, published_at, title, body,
             country_code, category, content_hash, raw_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            connector_name,
            external_id,
            doc_type,
            fetched_at,
            published_at or fetched_at,
            title,
            body,
            country_code,
            category,
            external_id,
            json.dumps(raw_json or {}),
        ),
    ).fetchone()
    assert row is not None
    raw_document_id = int(row[0])
    conn.execute(
        "INSERT INTO opportunity_sources (opportunity_id, raw_document_id) VALUES (%s, %s)",
        (opportunity_id, raw_document_id),
    )
    return raw_document_id


def test_pain_driven_opportunity_with_no_red_flags_is_scored_not_rejected(
    db_conn: psycopg.Connection[Any],
) -> None:
    opportunity_id = _insert_opportunity(db_conn, strategy="pain_driven")
    _link_document(
        db_conn,
        opportunity_id,
        connector_name="hackernews_algolia",
        external_id="1",
        doc_type="hn_ask",
        title="Ask HN: is there a tool to auto-renew my SaaS SSL certificates?",
    )
    db_conn.commit()

    stats = run_scoring(db_conn, clock=fixed_clock(AS_OF))

    assert stats.scored == 1
    assert stats.rejected == 0

    status, current_score = db_conn.execute(
        "SELECT status, current_score FROM opportunities WHERE id = %s", (opportunity_id,)
    ).fetchone()
    assert status == "candidate"
    assert current_score is not None

    history = db_conn.execute(
        "SELECT buildability_pass, vendability_pass, barrier_pass, momentum_confidence "
        "FROM score_history WHERE opportunity_id = %s",
        (opportunity_id,),
    ).fetchone()
    assert history == (True, True, None, "insufficient_history")


def test_arbitrage_opportunity_with_no_barrier_is_rejected(
    db_conn: psycopg.Connection[Any],
) -> None:
    opportunity_id = _insert_opportunity(db_conn, strategy="arbitrage")
    _link_document(
        db_conn,
        opportunity_id,
        connector_name="itunes_app_store",
        external_id="us:topfreeapplications:123:2026-08-07",
        doc_type="app_store_ranking",
        title="Some App",
        country_code="us",  # only charts in the US -- not an origin market, no barrier possible
        category="Productivity",
        raw_json={"rank": 5},
    )
    db_conn.commit()

    stats = run_scoring(db_conn, clock=fixed_clock(AS_OF))

    assert stats.rejected == 1
    status, reason = db_conn.execute(
        "SELECT status, rejection_reason FROM opportunities WHERE id = %s", (opportunity_id,)
    ).fetchone()
    assert status == "rejected"
    assert reason == "arbitrage:no_barrier_identified"


def test_arbitrage_opportunity_charting_abroad_only_is_accepted(
    db_conn: psycopg.Connection[Any],
) -> None:
    opportunity_id = _insert_opportunity(db_conn, strategy="arbitrage")
    _link_document(
        db_conn,
        opportunity_id,
        connector_name="itunes_app_store",
        external_id="jp:topfreeapplications:456:2026-08-07",
        doc_type="app_store_ranking",
        title="Some App",
        country_code="jp",  # charts in Japan only -- no US presence observed
        category="Productivity",
        raw_json={"rank": 3},
    )
    db_conn.commit()

    stats = run_scoring(db_conn, clock=fixed_clock(AS_OF))

    assert stats.scored == 1
    status = db_conn.execute(
        "SELECT status FROM opportunities WHERE id = %s", (opportunity_id,)
    ).fetchone()
    assert status == ("candidate",)

    barrier_pass = db_conn.execute(
        "SELECT barrier_pass FROM score_history WHERE opportunity_id = %s",
        (opportunity_id,),
    ).fetchone()
    assert barrier_pass == (True,)


def test_regulated_domain_is_rejected_at_buildability_gate(
    db_conn: psycopg.Connection[Any],
) -> None:
    opportunity_id = _insert_opportunity(db_conn, strategy="pain_driven")
    _link_document(
        db_conn,
        opportunity_id,
        connector_name="hackernews_algolia",
        external_id="1",
        doc_type="hn_ask",
        title="Ask HN: a tool that is HIPAA compliant for clinics",
    )
    db_conn.commit()

    run_scoring(db_conn, clock=fixed_clock(AS_OF))

    status, reason = db_conn.execute(
        "SELECT status, rejection_reason FROM opportunities WHERE id = %s", (opportunity_id,)
    ).fetchone()
    assert status == "rejected"
    assert reason == "buildability:regulated_domain"


def test_edgar_filing_produces_a_proof_event_and_dominates_score(
    db_conn: psycopg.Connection[Any],
) -> None:
    opportunity_id = _insert_opportunity(db_conn, strategy="arbitrage")
    _link_document(
        db_conn,
        opportunity_id,
        connector_name="itunes_app_store",
        external_id="jp:topfreeapplications:789:2026-08-07",
        doc_type="app_store_ranking",
        title="Funded App",
        country_code="jp",
        category="Productivity",
        raw_json={"rank": 2},
    )
    _link_document(
        db_conn,
        opportunity_id,
        connector_name="sec_edgar_formd",
        external_id="0001-26-000099",
        doc_type="edgar_formd",
        title="Funded App Inc.",
        published_at=AS_OF,
    )
    db_conn.commit()

    run_scoring(db_conn, clock=fixed_clock(AS_OF))

    proof_types = db_conn.execute(
        "SELECT proof_type FROM proof_events WHERE opportunity_id = %s ORDER BY proof_type",
        (opportunity_id,),
    ).fetchall()
    assert ("edgar_funding",) in proof_types
    assert ("app_store_ranking",) in proof_types

    composite_score, _breakdown = db_conn.execute(
        "SELECT current_score, current_score_breakdown FROM opportunities WHERE id = %s",
        (opportunity_id,),
    ).fetchone()
    assert composite_score is not None
    assert composite_score >= 40.0  # EDGAR alone contributes 50 (100 * 0.5 weight) to the composite


def test_disclosed_revenue_extracted_from_hn_text_produces_proof_event(
    db_conn: psycopg.Connection[Any],
) -> None:
    opportunity_id = _insert_opportunity(db_conn, strategy="pain_driven")
    _link_document(
        db_conn,
        opportunity_id,
        connector_name="hackernews_algolia",
        external_id="1",
        doc_type="hn_show",
        title="Show HN: my SaaS just hit $8k MRR",
        body="Proud milestone after a year of grinding.",
        published_at=AS_OF,
    )
    db_conn.commit()

    run_scoring(db_conn, clock=fixed_clock(AS_OF))

    proof_type, extracted_value = db_conn.execute(
        "SELECT proof_type, extracted_value FROM proof_events WHERE opportunity_id = %s",
        (opportunity_id,),
    ).fetchone()
    assert proof_type == "disclosed_revenue"
    assert extracted_value["monthly_amount_usd"] == 8000.0


def test_willingness_to_pay_extracted_from_hn_text_produces_proof_event(
    db_conn: psycopg.Connection[Any],
) -> None:
    opportunity_id = _insert_opportunity(db_conn, strategy="pain_driven")
    _link_document(
        db_conn,
        opportunity_id,
        connector_name="hackernews_algolia",
        external_id="1",
        doc_type="hn_ask",
        title="Ask HN: is there a tool for invoice reconciliation?",
        body="I would pay $50 for something that did this well.",
        published_at=AS_OF,
    )
    db_conn.commit()

    run_scoring(db_conn, clock=fixed_clock(AS_OF))

    proof_type, extracted_value = db_conn.execute(
        "SELECT proof_type, extracted_value FROM proof_events WHERE opportunity_id = %s",
        (opportunity_id,),
    ).fetchone()
    assert proof_type == "willingness_to_pay"
    assert extracted_value["monthly_amount_usd"] == 50.0

    inputs_snapshot = db_conn.execute(
        "SELECT inputs_snapshot FROM score_history WHERE opportunity_id = %s", (opportunity_id,)
    ).fetchone()[0]
    assert inputs_snapshot["demand_score"] == 0.6
    assert inputs_snapshot["demand_matched_types"] == ["explicit_demand_request"]


def test_momentum_reaches_ok_confidence_once_baseline_history_exists(
    db_conn: psycopg.Connection[Any],
) -> None:
    """Directly exercises the bootstrap -> OK confidence transition end to
    end through the real daily-signal rollup and momentum computation."""
    opportunity_id = _insert_opportunity(db_conn, strategy="pain_driven")
    for i in range(63):
        day = AS_OF - timedelta(days=i)
        _link_document(
            db_conn,
            opportunity_id,
            connector_name="hackernews_algolia",
            external_id=f"day-{i}",
            doc_type="hn_ask",
            title="Ask HN: is there a tool to auto-renew my SaaS SSL certificates?",
            fetched_at=day,
        )
    db_conn.commit()

    for i in range(63, -1, -1):
        as_of_day = AS_OF - timedelta(days=i)
        run_scoring(db_conn, clock=fixed_clock(as_of_day))

    latest = db_conn.execute(
        "SELECT momentum_confidence FROM score_history WHERE opportunity_id = %s "
        "ORDER BY id DESC LIMIT 1",
        (opportunity_id,),
    ).fetchone()
    assert latest == ("ok",)
