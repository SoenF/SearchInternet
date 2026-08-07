"""End-to-end ranking against a real (local Docker) Postgres, covering
acceptance criteria #2 (no duplicate opportunity in a snapshot), #3 (full
per-item traceability), #5 (a full, zero-LLM pipeline produces an exploitable
ranking), and #6 (a strong-momentum opportunity reaches the top 10).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg

from opportunity_engine.agents.ranking_agent import run_ranking
from opportunity_engine.agents.scoring_agent import run_scoring
from opportunity_engine.clock import fixed_clock

TODAY = date(2026, 8, 7)
AS_OF = datetime(2026, 8, 7, tzinfo=UTC)


def _insert_opportunity(conn: psycopg.Connection[Any], title: str) -> int:
    row = conn.execute(
        """
        INSERT INTO opportunities (title, primary_strategy, status)
        VALUES (%s, 'pain_driven', 'candidate')
        RETURNING id
        """,
        (title,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _seed_daily_signal(
    conn: psycopg.Connection[Any], opportunity_id: int, day: date, mention_count: int
) -> None:
    conn.execute(
        """
        INSERT INTO opportunity_daily_signal (opportunity_id, signal_date, mention_count)
        VALUES (%s, %s, %s)
        ON CONFLICT (opportunity_id, signal_date) DO UPDATE SET mention_count = EXCLUDED.mention_count
        """,
        (opportunity_id, day, mention_count),
    )


def _link_hn_doc_today(
    conn: psycopg.Connection[Any], opportunity_id: int, external_id: str, title: str
) -> None:
    conn.execute(
        """
        INSERT INTO connectors (name, source_description, source_url, quota_description,
                                 tos_url, tos_status, last_verified)
        VALUES ('hackernews_algolia', 't', 'http://t', 't', 'http://t', 'compliant', '2026-08-07')
        ON CONFLICT (name) DO NOTHING
        """
    )
    row = conn.execute(
        """
        INSERT INTO raw_documents
            (connector_name, external_id, doc_type, fetched_at, published_at, title, content_hash, raw_json)
        VALUES ('hackernews_algolia', %s, 'hn_ask', %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (external_id, AS_OF, AS_OF, title, external_id, json.dumps({})),
    ).fetchone()
    assert row is not None
    conn.execute(
        "INSERT INTO opportunity_sources (opportunity_id, raw_document_id) VALUES (%s, %s)",
        (opportunity_id, int(row[0])),
    )


def test_backlog_row_is_fully_traceable_per_dimension_strategy_and_sources(
    db_conn: psycopg.Connection[Any],
) -> None:
    opportunity_id = _insert_opportunity(db_conn, "SSL renewal tool")
    _link_hn_doc_today(
        db_conn, opportunity_id, "1", "Ask HN: is there a tool to auto-renew SSL certificates?"
    )
    db_conn.commit()

    run_scoring(db_conn, clock=fixed_clock(AS_OF))
    run_ranking(db_conn, clock=fixed_clock(AS_OF))

    row = db_conn.execute(
        """
        SELECT bs.rank, bs.composite_score, bs.strategy, sh.momentum_score,
               sh.market_proof_score, sh.buildability_pass, sh.vendability_pass
        FROM backlog_snapshots bs
        JOIN score_history sh ON sh.opportunity_id = bs.opportunity_id
        WHERE bs.opportunity_id = %s AND bs.window_start = %s
        """,
        (opportunity_id, TODAY),
    ).fetchone()
    assert row is not None
    rank, composite_score, strategy, momentum_score, market_proof_score, build_ok, vend_ok = row
    assert rank == 1
    assert strategy == "pain_driven"
    assert composite_score is not None
    assert momentum_score is not None
    assert market_proof_score is not None
    assert build_ok and vend_ok

    sources = db_conn.execute(
        "SELECT count(*) FROM opportunity_sources WHERE opportunity_id = %s", (opportunity_id,)
    ).fetchone()
    assert sources == (1,)


def test_full_pipeline_with_zero_llm_calls_produces_an_exploitable_ranking(
    db_conn: psycopg.Connection[Any],
) -> None:
    for i in range(5):
        opportunity_id = _insert_opportunity(db_conn, f"Opportunity {i}")
        _link_hn_doc_today(db_conn, opportunity_id, f"doc-{i}", f"Ask HN: idea number {i}?")
    db_conn.commit()

    scoring_stats = run_scoring(db_conn, clock=fixed_clock(AS_OF))
    slots_written = run_ranking(db_conn, clock=fixed_clock(AS_OF))

    assert scoring_stats.scored == 5
    assert slots_written > 0

    opportunity_ids_in_backlog = [
        row[0]
        for row in db_conn.execute(
            "SELECT opportunity_id FROM backlog_snapshots WHERE window_start = %s", (TODAY,)
        ).fetchall()
    ]
    # acceptance criterion #2: no duplicate opportunity in a single snapshot
    assert len(opportunity_ids_in_backlog) == len(set(opportunity_ids_in_backlog))


def test_qualified_status_promotion_on_first_proposal(db_conn: psycopg.Connection[Any]) -> None:
    opportunity_id = _insert_opportunity(db_conn, "Promoted opportunity")
    _link_hn_doc_today(db_conn, opportunity_id, "1", "Ask HN: does this tool exist?")
    db_conn.commit()

    run_scoring(db_conn, clock=fixed_clock(AS_OF))
    status_before = db_conn.execute(
        "SELECT status FROM opportunities WHERE id = %s", (opportunity_id,)
    ).fetchone()
    assert status_before == ("candidate",)

    run_ranking(db_conn, clock=fixed_clock(AS_OF))
    status_after = db_conn.execute(
        "SELECT status FROM opportunities WHERE id = %s", (opportunity_id,)
    ).fetchone()
    assert status_after == ("qualified",)


def test_strong_momentum_opportunity_reaches_top_ten_within_the_daily_cycle(
    db_conn: psycopg.Connection[Any],
) -> None:
    """Acceptance criterion #6: a manually-injected opportunity with strong
    momentum reaches the top 10 in well under 72h. Baseline history (56 days)
    is seeded directly to represent data already collected by prior daily
    ingestion runs; only the final day's scoring+ranking pass is executed
    here, which is exactly what one nightly `run-daily` invocation does in
    production -- one pipeline cycle, not 72 hours of simulated wall time.
    """
    injected_id = _insert_opportunity(db_conn, "Injected high-momentum opportunity")
    for i in range(7, 63):  # baseline window: flat, low activity
        _seed_daily_signal(db_conn, injected_id, TODAY - timedelta(days=i), mention_count=2)
    for i in range(1, 7):  # last 6 of the 7 recent days: sharp spike
        _seed_daily_signal(db_conn, injected_id, TODAY - timedelta(days=i), mention_count=10)
    _link_hn_doc_today(db_conn, injected_id, "spike-0", "Ask HN: sudden surge of interest?")

    background_ids = []
    for n in range(15):
        background_id = _insert_opportunity(db_conn, f"Background opportunity {n}")
        for i in range(1, 63):  # flat baseline AND flat recent -- no momentum
            _seed_daily_signal(db_conn, background_id, TODAY - timedelta(days=i), mention_count=1)
        _link_hn_doc_today(db_conn, background_id, f"bg-{n}", f"Ask HN: background idea {n}?")
        background_ids.append(background_id)
    db_conn.commit()

    run_scoring(db_conn, clock=fixed_clock(AS_OF))
    run_ranking(db_conn, clock=fixed_clock(AS_OF), cfg=_no_exploration_config())

    top_ten = [
        row[0]
        for row in db_conn.execute(
            "SELECT opportunity_id FROM backlog_snapshots "
            "WHERE window_start = %s ORDER BY rank LIMIT 10",
            (TODAY,),
        ).fetchall()
    ]
    assert injected_id in top_ten

    momentum_scores = dict(
        db_conn.execute(
            "SELECT opportunity_id, momentum_score FROM score_history "
            "WHERE opportunity_id = ANY(%s)",
            ([injected_id, *background_ids],),
        ).fetchall()
    )
    assert momentum_scores[injected_id] > momentum_scores[background_ids[0]]


def _no_exploration_config():  # type: ignore[no-untyped-def]
    from opportunity_engine.tools.ranking import RankingConfig

    return RankingConfig(
        top_n=10, strategy_quota={"pain_driven": 1.0}, exploration_share=0.0, max_category_share=1.0
    )
