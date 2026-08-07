"""Shared test fixtures.

Zero-network enforcement is configured once, globally, via
``--disable-socket --allow-hosts=127.0.0.1,::1,localhost`` in pyproject.toml's
pytest addopts (pytest-socket) -- every test gets it for free. Only
``tests/integration/*`` opts into touching the allowed hosts, and only to reach
a local Postgres; no test ever reaches a real external API.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from pgvector.psycopg import register_vector

from opportunity_engine.clock import Clock
from opportunity_engine.migration_runner import apply_migrations

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


@pytest.fixture
def frozen_now() -> datetime:
    return datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def clock(frozen_now: datetime) -> Clock:
    return lambda: frozen_now


def _test_database_url() -> str | None:
    return os.environ.get("OPPORTUNITY_ENGINE_TEST_DATABASE_URL") or None


@pytest.fixture(scope="session")
def migrated_test_db_url() -> str:
    """Real, local (Docker) Postgres, migrated once per test session.

    Skips the requesting test entirely if OPPORTUNITY_ENGINE_TEST_DATABASE_URL
    isn't set -- integration tests are opt-in, never required for the fast
    unit-test loop.
    """
    url = _test_database_url()
    if not url:
        pytest.skip("OPPORTUNITY_ENGINE_TEST_DATABASE_URL not set")
    with psycopg.connect(url) as conn:
        apply_migrations(conn, MIGRATIONS_DIR)
    return url


# Every app table except schema_migrations (meta, applied once per session).
# Agents commit internally by design (a connector's failure durably records
# connector_runs/events without losing other connectors' committed work), so
# rollback-based isolation doesn't work here -- a test's data would outlive
# its own connection. TRUNCATE is used instead: it does not fire the events
# table's row-level BEFORE UPDATE/DELETE triggers (TRUNCATE is neither an
# UPDATE nor a DELETE), so the append-only guard against *application* code
# stays intact while tests still get a clean slate.
_APP_TABLES = (
    "backlog_snapshots",
    "opportunity_dossiers",
    "score_history",
    "proof_events",
    "opportunity_daily_signal",
    "opportunity_sources",
    "wikipedia_pageviews_daily",
    "tracked_topics",
    "document_embeddings",
    "raw_documents",
    "events",
    "opportunities",
    "connector_runs",
    "connectors",
)


@pytest.fixture
def db_conn(migrated_test_db_url: str) -> Iterator[psycopg.Connection[Any]]:
    """One connection per test, against tables truncated immediately before
    the test runs -- deterministic regardless of whether the previous test
    committed or rolled back."""
    conn = psycopg.connect(migrated_test_db_url)
    register_vector(conn)
    conn.execute(f"TRUNCATE TABLE {', '.join(_APP_TABLES)} RESTART IDENTITY CASCADE")
    conn.commit()
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
