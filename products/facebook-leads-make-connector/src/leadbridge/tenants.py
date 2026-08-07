"""Per-tenant config for hosted subscription customers, keyed by Facebook
Page ID -- this is what makes running both monetization models (one-time
code sale, hosted subscription) off a single deployment possible: the
webhook handler checks this store first, and only falls back to the
single global Settings config (self-hosted buyer's own .env) when no
tenant record matches the incoming lead's page_id. Same SQLite-file
pattern as dedup.py -- fine at this scale, no server needed."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TenantConfig:
    page_id: str
    fb_page_access_token: str
    make_webhook_url: str
    stripe_customer_id: str
    status: str


class TenantStore:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                page_id TEXT PRIMARY KEY,
                fb_page_access_token TEXT NOT NULL,
                make_webhook_url TEXT NOT NULL,
                stripe_customer_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def get_tenant(self, page_id: str) -> TenantConfig | None:
        row = self._conn.execute(
            "SELECT page_id, fb_page_access_token, make_webhook_url, stripe_customer_id, status "
            "FROM tenants WHERE page_id = ?",
            (page_id,),
        ).fetchone()
        return TenantConfig(*row) if row else None

    def upsert_tenant(
        self,
        *,
        page_id: str,
        fb_page_access_token: str,
        make_webhook_url: str,
        stripe_customer_id: str,
        created_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO tenants (page_id, fb_page_access_token, make_webhook_url,
                                  stripe_customer_id, status, created_at)
            VALUES (?, ?, ?, ?, 'active', ?)
            ON CONFLICT(page_id) DO UPDATE SET
                fb_page_access_token = excluded.fb_page_access_token,
                make_webhook_url = excluded.make_webhook_url,
                stripe_customer_id = excluded.stripe_customer_id,
                status = 'active'
            """,
            (page_id, fb_page_access_token, make_webhook_url, stripe_customer_id, created_at),
        )
        self._conn.commit()

    def deactivate_by_customer_id(self, stripe_customer_id: str) -> None:
        self._conn.execute(
            "UPDATE tenants SET status = 'inactive' WHERE stripe_customer_id = ?",
            (stripe_customer_id,),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def in_memory_store() -> TenantStore:
    return TenantStore(":memory:")


def file_store(db_path: str) -> TenantStore:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return TenantStore(db_path)
