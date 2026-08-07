"""Phase 5 end to end: a candidate whose embedding sits near an already-
rejected opportunity's centroid should score lower than an otherwise
identical candidate with no rejected neighbors.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import psycopg

from opportunity_engine.agents.scoring_agent import run_scoring
from opportunity_engine.clock import fixed_clock

AS_OF = datetime(2026, 8, 7, tzinfo=UTC)
VEC_REJECTED = [1.0] + [0.0] * 767
VEC_NEAR = [0.99] + [0.14106736] + [0.0] * 766  # cosine similarity ~0.99 to VEC_REJECTED
VEC_FAR = [0.0] * 767 + [1.0]  # orthogonal


def _insert_rejected_opportunity(conn: psycopg.Connection[Any]) -> int:
    row = conn.execute(
        """
        INSERT INTO opportunities
            (title, primary_strategy, status, rejection_reason, centroid_embedding, centroid_updated_at)
        VALUES ('Past rejected idea', 'pain_driven', 'rejected', 'buildability:regulated_domain', %s, now())
        RETURNING id
        """,
        (VEC_REJECTED,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _insert_candidate_with_centroid(
    conn: psycopg.Connection[Any], *, title: str, centroid: list[float]
) -> int:
    row = conn.execute(
        """
        INSERT INTO opportunities
            (title, primary_strategy, status, centroid_embedding, centroid_updated_at)
        VALUES (%s, 'pain_driven', 'candidate', %s, now())
        RETURNING id
        """,
        (title, centroid),
    ).fetchone()
    assert row is not None
    opportunity_id = int(row[0])

    conn.execute(
        """
        INSERT INTO connectors (name, source_description, source_url, quota_description,
                                 tos_url, tos_status, last_verified)
        VALUES ('hackernews_algolia', 't', 'http://t', 't', 'http://t', 'compliant', '2026-08-07')
        ON CONFLICT (name) DO NOTHING
        """
    )
    # give every candidate the same non-zero market-proof baseline (a disclosed
    # revenue mention) so the rejection penalty's effect is visible in the
    # comparison -- otherwise both composite scores start at 0 regardless of
    # the penalty (0 floored by max(0, ...) is still 0)
    body = "We just hit $5k MRR with this tool."
    doc_row = conn.execute(
        """
        INSERT INTO raw_documents
            (connector_name, external_id, doc_type, fetched_at, published_at, title, body, content_hash, raw_json)
        VALUES ('hackernews_algolia', %s, 'hn_ask', %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (title, AS_OF, AS_OF, title, body, title, json.dumps({})),
    ).fetchone()
    assert doc_row is not None
    conn.execute(
        "INSERT INTO opportunity_sources (opportunity_id, raw_document_id) VALUES (%s, %s)",
        (opportunity_id, int(doc_row[0])),
    )
    return opportunity_id


def test_candidate_near_a_rejected_opportunity_scores_lower(
    db_conn: psycopg.Connection[Any],
) -> None:
    _insert_rejected_opportunity(db_conn)
    near_id = _insert_candidate_with_centroid(
        db_conn, title="Near the rejected idea", centroid=VEC_NEAR
    )
    far_id = _insert_candidate_with_centroid(
        db_conn, title="Unrelated to the rejected idea", centroid=VEC_FAR
    )
    db_conn.commit()

    run_scoring(db_conn, clock=fixed_clock(AS_OF))

    near_score, far_score = (
        db_conn.execute(
            "SELECT current_score FROM opportunities WHERE id = %s", (opportunity_id,)
        ).fetchone()[0]
        for opportunity_id in (near_id, far_id)
    )

    assert near_score < far_score

    penalty_row = db_conn.execute(
        "SELECT inputs_snapshot FROM score_history WHERE opportunity_id = %s", (near_id,)
    ).fetchone()
    assert penalty_row is not None
    snapshot = penalty_row[0]
    assert snapshot["rejection_penalty_points"] > 0
    assert len(snapshot["rejection_penalty_neighbors"]) == 1


def test_candidate_far_from_any_rejection_has_no_penalty(
    db_conn: psycopg.Connection[Any],
) -> None:
    _insert_rejected_opportunity(db_conn)
    far_id = _insert_candidate_with_centroid(db_conn, title="Totally unrelated", centroid=VEC_FAR)
    db_conn.commit()

    run_scoring(db_conn, clock=fixed_clock(AS_OF))

    snapshot = db_conn.execute(
        "SELECT inputs_snapshot FROM score_history WHERE opportunity_id = %s", (far_id,)
    ).fetchone()[0]
    assert snapshot["rejection_penalty_points"] == 0
    assert snapshot["rejection_penalty_neighbors"] == []
