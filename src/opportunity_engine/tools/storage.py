"""Pure(ish) persistence helpers shared by every agent -- plain SQL, no ORM."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import psycopg

from opportunity_engine.collectors.base import ConnectorManifest
from opportunity_engine.domain.models import RawDocument, TrackedTopic


def upsert_connector_manifest(
    conn: psycopg.Connection[Any], manifest: ConnectorManifest, *, enabled: bool
) -> None:
    conn.execute(
        """
        INSERT INTO connectors (
            name, source_description, source_url, quota_description,
            tos_url, tos_status, last_verified, enabled
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (name) DO UPDATE SET
            source_description = EXCLUDED.source_description,
            source_url = EXCLUDED.source_url,
            quota_description = EXCLUDED.quota_description,
            tos_url = EXCLUDED.tos_url,
            tos_status = EXCLUDED.tos_status,
            last_verified = EXCLUDED.last_verified,
            enabled = EXCLUDED.enabled,
            updated_at = now()
        """,
        (
            manifest.name,
            manifest.source_description,
            manifest.source_url,
            manifest.quota_description,
            manifest.tos_url,
            manifest.tos_status,
            manifest.last_verified,
            enabled,
        ),
    )


def store_raw_document(conn: psycopg.Connection[Any], doc: RawDocument) -> int:
    """Upsert on (connector_name, external_id): re-ingesting the same item
    (e.g. an HN post whose comment count changed) refreshes it in place rather
    than duplicating it."""
    row = conn.execute(
        """
        INSERT INTO raw_documents (
            connector_name, external_id, doc_type, fetched_at, published_at,
            source_url, title, body, country_code, category, content_hash, raw_json
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (connector_name, external_id) DO UPDATE SET
            fetched_at = EXCLUDED.fetched_at,
            published_at = EXCLUDED.published_at,
            source_url = EXCLUDED.source_url,
            title = EXCLUDED.title,
            body = EXCLUDED.body,
            country_code = EXCLUDED.country_code,
            category = EXCLUDED.category,
            content_hash = EXCLUDED.content_hash,
            raw_json = EXCLUDED.raw_json
        RETURNING id
        """,
        (
            doc.connector_name,
            doc.external_id,
            doc.doc_type,
            doc.fetched_at,
            doc.published_at,
            doc.source_url,
            doc.title,
            doc.body,
            doc.country_code,
            doc.category,
            doc.content_hash,
            json.dumps(doc.raw_json, default=str),
        ),
    ).fetchone()
    assert row is not None
    return int(row[0])


def upsert_wikipedia_series(conn: psycopg.Connection[Any], raw_json: dict[str, Any]) -> int:
    """Expands a Wikipedia pageviews_series RawDocument's raw_json into
    individual daily rows -- the shape momentum math actually reads. Each
    item already carries its own project/article, so no extra parameters
    are needed here."""
    rows = 0
    for item in raw_json.get("items", []):
        pageview_date = (
            datetime.strptime(item["timestamp"][:8], "%Y%m%d").replace(tzinfo=UTC).date()
        )
        conn.execute(
            """
            INSERT INTO wikipedia_pageviews_daily (project, article, pageview_date, views)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (project, article, pageview_date) DO UPDATE SET
                views = EXCLUDED.views,
                fetched_at = now()
            """,
            (item["project"], item["article"], pageview_date, item["views"]),
        )
        rows += 1
    return rows


def add_tracked_topic(
    conn: psycopg.Connection[Any],
    topic: TrackedTopic,
    topic_label: str,
    *,
    added_by_opportunity_id: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO tracked_topics (project, article, topic_label, added_by_opportunity_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (project, article) DO NOTHING
        """,
        (topic.project, topic.article, topic_label, added_by_opportunity_id),
    )


def fetch_tracked_topics(conn: psycopg.Connection[Any]) -> list[TrackedTopic]:
    rows = conn.execute("SELECT project, article FROM tracked_topics").fetchall()
    return [TrackedTopic(project=project, article=article) for project, article in rows]
