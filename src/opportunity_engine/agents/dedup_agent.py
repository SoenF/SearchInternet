"""Single-responsibility service: embed newly ingested documents, decide
merge/novel/gray-zone against existing opportunity centroids, and act on it.
Talks to other agents only through the database and the events log.

Wikipedia pageviews_series documents are handled separately from the rest:
they're evidence for a *tracked topic* that already belongs to an existing
opportunity (`tracked_topics.added_by_opportunity_id`), not new candidate
material -- so they're linked directly via that lookup rather than run through
embedding-based dedup (which wouldn't be meaningful for a raw numeric time
series anyway).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import psycopg
from pgvector import Vector

from opportunity_engine.clock import Clock, utc_now
from opportunity_engine.domain.enums import DedupDecision, DetectionStrategyName, EventType
from opportunity_engine.domain.models import RawDocument
from opportunity_engine.events import append_event
from opportunity_engine.providers.embedding_provider import EmbeddingProvider
from opportunity_engine.tools.clustering import nearest_centroids
from opportunity_engine.tools.dedup import classify_document

logger = logging.getLogger(__name__)

# Provisional strategy assigned at opportunity-creation time, by source doc_type.
# DetectionStrategy.evaluate() (see strategies/) reassesses eligibility later;
# this is just what a *new* opportunity starts out tagged as, since the schema
# requires primary_strategy NOT NULL from creation.
_STRATEGY_BY_DOC_TYPE: dict[str, DetectionStrategyName] = {
    "hn_ask": DetectionStrategyName.PAIN_DRIVEN,
    "hn_show": DetectionStrategyName.PAIN_DRIVEN,
    "reddit_post": DetectionStrategyName.PAIN_DRIVEN,
    "producthunt_post": DetectionStrategyName.PAIN_DRIVEN,
    "stackexchange_question": DetectionStrategyName.PAIN_DRIVEN,
    "github_issue": DetectionStrategyName.PAIN_DRIVEN,
    "app_store_review": DetectionStrategyName.PAIN_DRIVEN,
    "discourse_topic": DetectionStrategyName.PAIN_DRIVEN,
    "edgar_formd": DetectionStrategyName.ARBITRAGE,
    "app_store_ranking": DetectionStrategyName.ARBITRAGE,
}

_WIKIPEDIA_DOC_TYPE = "wikipedia_pageviews_series"


@dataclass
class DedupStats:
    merged: int = 0
    novel: int = 0
    gray_zone: int = 0
    wikipedia_linked: int = 0
    skipped_no_text: int = 0


def run_dedup(
    conn: psycopg.Connection[Any],
    embedding_provider: EmbeddingProvider,
    *,
    merge_threshold: float = 0.92,
    novel_threshold: float = 0.75,
    clock: Clock = utc_now,
) -> DedupStats:
    stats = DedupStats()
    model_name = embedding_provider.model_name

    for doc in _fetch_unlinked_wikipedia_documents(conn):
        if _link_wikipedia_doc_to_tracked_opportunity(conn, doc):
            stats.wikipedia_linked += 1
        conn.commit()

    for doc in _fetch_unembedded_documents(conn, model_name):
        text = _embeddable_text(doc)
        if not text:
            stats.skipped_no_text += 1
            continue

        assert doc.id is not None
        [vector] = embedding_provider.embed([text])
        _store_embedding(conn, doc.id, model_name, vector)

        matches = nearest_centroids(conn, vector, k=1)
        nearest = matches[0] if matches else None
        result = classify_document(
            nearest, merge_threshold=merge_threshold, novel_threshold=novel_threshold
        )

        if result.decision == DedupDecision.MERGE:
            assert result.matched_opportunity_id is not None
            _merge_into_opportunity(conn, result.matched_opportunity_id, doc, model_name, clock)
            stats.merged += 1
        elif result.decision == DedupDecision.NOVEL:
            _create_opportunity(conn, doc, vector, clock, related_opportunity_id=None)
            stats.novel += 1
        else:
            _create_opportunity(
                conn, doc, vector, clock, related_opportunity_id=result.matched_opportunity_id
            )
            stats.gray_zone += 1
        conn.commit()

    return stats


def _embeddable_text(doc: RawDocument) -> str | None:
    parts = [part for part in (doc.title, doc.body) if part]
    text = "\n".join(parts).strip()
    return text or None


def _fetch_unembedded_documents(
    conn: psycopg.Connection[Any], model_name: str
) -> list[RawDocument]:
    rows = conn.execute(
        """
        SELECT rd.id, rd.connector_name, rd.external_id, rd.doc_type, rd.fetched_at,
               rd.published_at, rd.source_url, rd.title, rd.body, rd.country_code,
               rd.category, rd.content_hash, rd.raw_json
        FROM raw_documents rd
        WHERE rd.doc_type != %s
          AND NOT EXISTS (
              SELECT 1 FROM document_embeddings de
              WHERE de.raw_document_id = rd.id AND de.model_name = %s
          )
        ORDER BY rd.id
        """,
        (_WIKIPEDIA_DOC_TYPE, model_name),
    ).fetchall()
    return [_row_to_raw_document(row) for row in rows]


def _fetch_unlinked_wikipedia_documents(conn: psycopg.Connection[Any]) -> list[RawDocument]:
    rows = conn.execute(
        """
        SELECT rd.id, rd.connector_name, rd.external_id, rd.doc_type, rd.fetched_at,
               rd.published_at, rd.source_url, rd.title, rd.body, rd.country_code,
               rd.category, rd.content_hash, rd.raw_json
        FROM raw_documents rd
        WHERE rd.doc_type = %s
          AND NOT EXISTS (
              SELECT 1 FROM opportunity_sources os WHERE os.raw_document_id = rd.id
          )
        ORDER BY rd.id
        """,
        (_WIKIPEDIA_DOC_TYPE,),
    ).fetchall()
    return [_row_to_raw_document(row) for row in rows]


def _row_to_raw_document(row: tuple[Any, ...]) -> RawDocument:
    return RawDocument(
        id=row[0],
        connector_name=row[1],
        external_id=row[2],
        doc_type=row[3],
        fetched_at=row[4],
        published_at=row[5],
        source_url=row[6],
        title=row[7],
        body=row[8],
        country_code=row[9],
        category=row[10],
        content_hash=row[11],
        raw_json=row[12],
    )


def _store_embedding(
    conn: psycopg.Connection[Any], raw_document_id: int, model_name: str, vector: list[float]
) -> None:
    conn.execute(
        """
        INSERT INTO document_embeddings (raw_document_id, model_name, model_version, embedding)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (raw_document_id, model_name) DO UPDATE SET embedding = EXCLUDED.embedding
        """,
        (raw_document_id, model_name, "1", Vector(vector)),
    )


def _merge_into_opportunity(
    conn: psycopg.Connection[Any],
    opportunity_id: int,
    doc: RawDocument,
    model_name: str,
    clock: Clock,
) -> None:
    conn.execute(
        """
        INSERT INTO opportunity_sources (opportunity_id, raw_document_id)
        VALUES (%s, %s) ON CONFLICT DO NOTHING
        """,
        (opportunity_id, doc.id),
    )
    _recompute_centroid(conn, opportunity_id, model_name, clock)
    now = clock()
    conn.execute(
        "UPDATE opportunities SET last_seen_at = %s, updated_at = %s WHERE id = %s",
        (now, now, opportunity_id),
    )
    append_event(
        conn,
        EventType.OPPORTUNITY_MERGED,
        opportunity_id=opportunity_id,
        payload={"raw_document_id": doc.id, "connector_name": doc.connector_name},
    )


def _recompute_centroid(
    conn: psycopg.Connection[Any], opportunity_id: int, model_name: str, clock: Clock
) -> None:
    """Recomputed from scratch as the normalized mean of every linked
    embedding, rather than an incremental running mean -- cheap at this
    project's volume and avoids renormalization drift."""
    row = conn.execute(
        """
        SELECT avg(de.embedding)
        FROM document_embeddings de
        JOIN opportunity_sources os ON os.raw_document_id = de.raw_document_id
        WHERE os.opportunity_id = %s AND de.model_name = %s
        """,
        (opportunity_id, model_name),
    ).fetchone()
    assert row is not None and row[0] is not None
    average = np.asarray(row[0].to_numpy(), dtype=float)  # avg(vector) loads back as a Vector
    norm = float(np.linalg.norm(average))
    normalized = (average / norm).tolist() if norm > 0 else average.tolist()
    conn.execute(
        "UPDATE opportunities SET centroid_embedding = %s, centroid_updated_at = %s WHERE id = %s",
        (Vector(normalized), clock(), opportunity_id),
    )


def _create_opportunity(
    conn: psycopg.Connection[Any],
    doc: RawDocument,
    vector: list[float],
    clock: Clock,
    *,
    related_opportunity_id: int | None,
) -> int:
    strategy = _STRATEGY_BY_DOC_TYPE.get(doc.doc_type, DetectionStrategyName.PAIN_DRIVEN)
    now = clock()
    row = conn.execute(
        """
        INSERT INTO opportunities (
            title, category, primary_strategy, status, centroid_embedding,
            centroid_updated_at, related_opportunity_id, first_seen_at, last_seen_at
        ) VALUES (%s, %s, %s, 'candidate', %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            doc.title or f"Untitled ({doc.connector_name}:{doc.external_id})",
            doc.category,
            strategy.value,
            Vector(vector),
            now,
            related_opportunity_id,
            now,
            now,
        ),
    ).fetchone()
    assert row is not None
    opportunity_id = int(row[0])

    conn.execute(
        "INSERT INTO opportunity_sources (opportunity_id, raw_document_id) VALUES (%s, %s)",
        (opportunity_id, doc.id),
    )
    event_type = (
        EventType.OPPORTUNITY_CREATED_GRAY_ZONE_REVIEW
        if related_opportunity_id is not None
        else EventType.OPPORTUNITY_CREATED
    )
    append_event(
        conn,
        event_type,
        opportunity_id=opportunity_id,
        payload={
            "raw_document_id": doc.id,
            "connector_name": doc.connector_name,
            "related_opportunity_id": related_opportunity_id,
        },
    )
    return opportunity_id


def _link_wikipedia_doc_to_tracked_opportunity(
    conn: psycopg.Connection[Any], doc: RawDocument
) -> bool:
    items = doc.raw_json.get("items") or []
    if not items:
        return False
    project = items[0].get("project")
    article = items[0].get("article")
    if not project or not article:
        return False

    row = conn.execute(
        "SELECT added_by_opportunity_id FROM tracked_topics WHERE project = %s AND article = %s",
        (project, article),
    ).fetchone()
    if row is None or row[0] is None:
        logger.info(
            "tracked topic has no owning opportunity yet, skipping link",
            extra={"project": project, "article": article},
        )
        return False

    opportunity_id = row[0]
    conn.execute(
        """
        INSERT INTO opportunity_sources (opportunity_id, raw_document_id)
        VALUES (%s, %s) ON CONFLICT DO NOTHING
        """,
        (opportunity_id, doc.id),
    )
    return True
