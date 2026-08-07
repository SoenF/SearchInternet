from __future__ import annotations

from typing import Any

import psycopg
import pytest

from opportunity_engine.domain.enums import EventType
from opportunity_engine.events import append_event


def test_append_event_inserts_and_returns_id(db_conn: psycopg.Connection[Any]) -> None:
    event_id = append_event(
        db_conn,
        EventType.DOCUMENT_INGESTED,
        connector_name="hackernews_algolia",
        payload={"count": 3},
    )
    assert event_id > 0

    row = db_conn.execute(
        "SELECT event_type, connector_name, payload FROM events WHERE id = %s",
        (event_id,),
    ).fetchone()
    assert row == ("document_ingested", "hackernews_algolia", {"count": 3})


def test_events_table_rejects_update(db_conn: psycopg.Connection[Any]) -> None:
    event_id = append_event(db_conn, EventType.OPPORTUNITY_SCORED)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db_conn.execute("UPDATE events SET actor = 'tampered' WHERE id = %s", (event_id,))
    db_conn.rollback()


def test_events_table_rejects_delete(db_conn: psycopg.Connection[Any]) -> None:
    event_id = append_event(db_conn, EventType.OPPORTUNITY_SCORED)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db_conn.execute("DELETE FROM events WHERE id = %s", (event_id,))
    db_conn.rollback()
