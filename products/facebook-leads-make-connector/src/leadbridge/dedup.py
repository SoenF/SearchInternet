"""Tracks which leadgen_ids have already been forwarded to Make. Facebook can
redeliver the same webhook notification (documented retry-on-timeout
behavior), and without this a slow Make scenario execution would cause the
same lead to be created twice downstream. A single SQLite file is enough at
this scale (one Page's worth of leads) -- no need for a real database server
for a product this size; see docs/SETUP.md for the upgrade note if a customer
ever needs multi-instance deployment."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class DedupStore:
    def __init__(self, db_path: str) -> None:
        # check_same_thread=False: uvicorn/TestClient can dispatch the async
        # request handler onto a different OS thread than the one that
        # constructed this store. Safe here because asyncio's single event
        # loop still serializes access -- there's no real concurrent writer.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS seen_leads (leadgen_id TEXT PRIMARY KEY, seen_at TEXT NOT NULL)"
        )
        self._conn.commit()

    def already_processed(self, leadgen_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_leads WHERE leadgen_id = ?", (leadgen_id,)
        ).fetchone()
        return row is not None

    def mark_processed(self, leadgen_id: str, seen_at: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen_leads (leadgen_id, seen_at) VALUES (?, ?)",
            (leadgen_id, seen_at),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def in_memory_store() -> DedupStore:
    """Tests use this instead of a temp file on disk."""
    return DedupStore(":memory:")


def file_store(db_path: str) -> DedupStore:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return DedupStore(db_path)
