"""Vector-similarity helpers. `cosine_similarity` is a true pure function
(numpy only); `nearest_centroids` is a thin pgvector query -- same
"pure function, does I/O when the job needs it" pattern as tools/storage.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import psycopg
from pgvector import Vector


def cosine_similarity(a: list[float], b: list[float]) -> float:
    vec_a, vec_b = np.array(a, dtype=float), np.array(b, dtype=float)
    denom = float(np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)


@dataclass(frozen=True)
class CentroidMatch:
    opportunity_id: int
    similarity: float


def nearest_centroids(
    conn: psycopg.Connection[Any],
    embedding: list[float],
    k: int = 5,
    *,
    statuses: list[str] | None = None,
    exclude_opportunity_id: int | None = None,
) -> list[CentroidMatch]:
    """Nearest existing opportunity centroids by cosine similarity, closest
    first. pgvector's `<=>` operator is cosine *distance* under
    vector_cosine_ops, so similarity = 1 - distance.

    `register_vector()` only adapts `Vector`/`numpy.ndarray` params, not plain
    `list` (psycopg's own list->array(8) adapter wins otherwise) -- hence the
    explicit `Vector(...)` wrap here rather than passing `embedding` as-is.

    `statuses` narrows the search to specific lifecycle statuses (e.g.
    `["rejected"]` for the Phase-5 feedback loop); `None` (the DedupAgent
    default) searches every opportunity regardless of status, since "is this
    literally the same real-world candidate" doesn't depend on lifecycle
    state. `exclude_opportunity_id` keeps an opportunity from matching
    itself.
    """
    query_vector = Vector(embedding)
    conditions = ["centroid_embedding IS NOT NULL"]
    where_params: list[Any] = []
    if statuses is not None:
        conditions.append("status = ANY(%s)")
        where_params.append(statuses)
    if exclude_opportunity_id is not None:
        conditions.append("id != %s")
        where_params.append(exclude_opportunity_id)

    # Positional params must match the rendered SQL's %s order exactly: the
    # SELECT's distance calc, then the WHERE-clause params, then ORDER BY's
    # distance calc, then LIMIT -- the WHERE params sit *between* the two
    # vector placeholders, not after both.
    params: list[Any] = [query_vector, *where_params, query_vector, k]

    rows = conn.execute(
        f"""
        SELECT id, 1 - (centroid_embedding <=> %s) AS similarity
        FROM opportunities
        WHERE {" AND ".join(conditions)}
        ORDER BY centroid_embedding <=> %s
        LIMIT %s
        """,
        params,
    ).fetchall()
    return [CentroidMatch(opportunity_id=row[0], similarity=float(row[1])) for row in rows]
