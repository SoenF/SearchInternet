"""The one channel agents use to communicate history to each other.

Per architecture rule: agents never call each other directly. They write rows
here (and to their own domain tables); anything downstream reads this log
instead of being invoked synchronously. The table itself is append-only at the
database level (see migrations/0010_events.sql) -- this module is just a thin,
typed way to insert into it.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

from opportunity_engine.domain.enums import EventType


def append_event(
    conn: psycopg.Connection[Any],
    event_type: EventType | str,
    *,
    opportunity_id: int | None = None,
    connector_name: str | None = None,
    payload: dict[str, Any] | None = None,
    actor: str = "system",
) -> int:
    row = conn.execute(
        """
        INSERT INTO events (event_type, opportunity_id, connector_name, payload, actor)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            str(event_type),
            opportunity_id,
            connector_name,
            json.dumps(payload or {}, default=str),
            actor,
        ),
    ).fetchone()
    assert row is not None
    return int(row[0])
