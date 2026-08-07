"""nearest_centroids against a real (local Docker) Postgres -- in particular
the status/exclude filters added for the Phase-5 feedback loop, where getting
the WHERE-clause parameter order wrong (relative to the two vector
placeholders in SELECT and ORDER BY) would silently return wrong matches
rather than erroring.
"""

from __future__ import annotations

from typing import Any

import psycopg

from opportunity_engine.tools.clustering import nearest_centroids

VEC_A = [1.0] + [0.0] * 767
VEC_B = [0.9] + [0.436] * 1 + [0.0] * 766  # close to VEC_A
VEC_FAR = [0.0] * 767 + [1.0]  # orthogonal to VEC_A


def _insert_opportunity(
    conn: psycopg.Connection[Any], *, status: str, centroid: list[float], title: str
) -> int:
    row = conn.execute(
        """
        INSERT INTO opportunities (title, primary_strategy, status, centroid_embedding, centroid_updated_at)
        VALUES (%s, 'pain_driven', %s, %s, now())
        RETURNING id
        """,
        (title, status, centroid),
    ).fetchone()
    assert row is not None
    return int(row[0])


def test_status_filter_only_matches_requested_statuses(db_conn: psycopg.Connection[Any]) -> None:
    rejected_id = _insert_opportunity(
        db_conn, status="rejected", centroid=VEC_B, title="rejected neighbor"
    )
    _insert_opportunity(db_conn, status="candidate", centroid=VEC_B, title="candidate neighbor")
    db_conn.commit()

    matches = nearest_centroids(db_conn, VEC_A, k=5, statuses=["rejected"])

    assert [m.opportunity_id for m in matches] == [rejected_id]


def test_no_status_filter_matches_everything(db_conn: psycopg.Connection[Any]) -> None:
    rejected_id = _insert_opportunity(
        db_conn, status="rejected", centroid=VEC_B, title="rejected neighbor"
    )
    candidate_id = _insert_opportunity(
        db_conn, status="candidate", centroid=VEC_B, title="candidate neighbor"
    )
    db_conn.commit()

    matches = nearest_centroids(db_conn, VEC_A, k=5)

    assert {m.opportunity_id for m in matches} == {rejected_id, candidate_id}


def test_exclude_opportunity_id_omits_self_match(db_conn: psycopg.Connection[Any]) -> None:
    self_id = _insert_opportunity(db_conn, status="candidate", centroid=VEC_A, title="self")
    other_id = _insert_opportunity(db_conn, status="candidate", centroid=VEC_B, title="other")
    db_conn.commit()

    matches = nearest_centroids(db_conn, VEC_A, k=5, exclude_opportunity_id=self_id)

    assert [m.opportunity_id for m in matches] == [other_id]


def test_status_and_exclude_filters_compose(db_conn: psycopg.Connection[Any]) -> None:
    self_id = _insert_opportunity(
        db_conn, status="rejected", centroid=VEC_A, title="self, rejected"
    )
    other_rejected_id = _insert_opportunity(
        db_conn, status="rejected", centroid=VEC_B, title="other, rejected"
    )
    _insert_opportunity(db_conn, status="candidate", centroid=VEC_B, title="other, candidate")
    db_conn.commit()

    matches = nearest_centroids(
        db_conn, VEC_A, k=5, statuses=["rejected"], exclude_opportunity_id=self_id
    )

    assert [m.opportunity_id for m in matches] == [other_rejected_id]


def test_similarity_ordering_is_closest_first(db_conn: psycopg.Connection[Any]) -> None:
    far_id = _insert_opportunity(db_conn, status="rejected", centroid=VEC_FAR, title="far")
    close_id = _insert_opportunity(db_conn, status="rejected", centroid=VEC_B, title="close")
    db_conn.commit()

    matches = nearest_centroids(db_conn, VEC_A, k=5, statuses=["rejected"])

    assert [m.opportunity_id for m in matches] == [close_id, far_id]
    assert matches[0].similarity > matches[1].similarity
