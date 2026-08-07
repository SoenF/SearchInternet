"""Single-responsibility service: run enabled collectors, persist what they
find, record run stats and an event. Talks to other agents only through the
database and the events log, never directly (see CLAUDE.md rule #2).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import psycopg

from opportunity_engine.clock import Clock, utc_now
from opportunity_engine.collectors.base import Collector
from opportunity_engine.domain.enums import EventType
from opportunity_engine.events import append_event
from opportunity_engine.tools.storage import (
    store_raw_document,
    upsert_connector_manifest,
    upsert_wikipedia_series,
)

logger = logging.getLogger(__name__)


def run_ingestion(
    conn: psycopg.Connection[Any],
    collectors: list[Collector],
    since: datetime,
    until: datetime,
    *,
    clock: Clock = utc_now,
) -> dict[str, int]:
    """Returns {connector_name: items_stored}. One connector failing does not
    stop the others -- each is isolated in its own try/except and its own
    connector_runs row."""
    items_stored_by_connector: dict[str, int] = {}
    for collector in collectors:
        manifest = collector.manifest
        upsert_connector_manifest(conn, manifest, enabled=True)
        conn.commit()

        started_at = clock()
        items_fetched = 0
        items_stored = 0
        status = "success"
        error_message: str | None = None
        try:
            for doc in collector.collect(since, until):
                items_fetched += 1
                store_raw_document(conn, doc)
                if doc.doc_type == "wikipedia_pageviews_series":
                    # this doc_type also feeds a specialized table momentum math
                    # reads directly -- the audit row in raw_documents alone isn't enough
                    upsert_wikipedia_series(conn, doc.raw_json)
                items_stored += 1
        except Exception as exc:  # connector-level failure: isolate, record, keep going
            conn.rollback()
            status = "failure"
            error_message = str(exc)
            logger.exception("connector %s failed", manifest.name)
        finished_at = clock()

        conn.execute(
            """
            INSERT INTO connector_runs
                (connector_name, started_at, finished_at, status,
                 items_fetched, items_stored, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                manifest.name,
                started_at,
                finished_at,
                status,
                items_fetched,
                items_stored,
                error_message,
            ),
        )
        append_event(
            conn,
            EventType.DOCUMENT_INGESTED,
            connector_name=manifest.name,
            payload={
                "items_fetched": items_fetched,
                "items_stored": items_stored,
                "status": status,
            },
        )
        conn.commit()
        items_stored_by_connector[manifest.name] = items_stored
    return items_stored_by_connector
