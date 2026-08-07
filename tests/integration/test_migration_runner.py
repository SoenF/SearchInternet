"""Requires a real (local Docker) Postgres -- see conftest.migrated_test_db_url.

Uses a fabricated, throwaway migration file rather than the project's real
migrations, so this test never mutates real migration files and cleans up
after itself regardless of the real schema's state.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from opportunity_engine.migration_runner import MigrationDriftError, apply_migrations

_VERSION = "9001_migration_runner_test_marker"
_SQL = "CREATE TABLE IF NOT EXISTS _migration_runner_test_marker (id int);"


@pytest.fixture
def fabricated_migrations_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / f"{_VERSION}.sql").write_text(_SQL)
    return directory


def _cleanup(conn: psycopg.Connection[object]) -> None:
    conn.execute("DROP TABLE IF EXISTS _migration_runner_test_marker")
    conn.execute("DELETE FROM schema_migrations WHERE version = %s", (_VERSION,))
    conn.commit()


def test_apply_migrations_is_idempotent(
    migrated_test_db_url: str, fabricated_migrations_dir: Path
) -> None:
    conn = psycopg.connect(migrated_test_db_url)
    try:
        first_run = apply_migrations(conn, fabricated_migrations_dir)
        assert first_run == [_VERSION]

        second_run = apply_migrations(conn, fabricated_migrations_dir)
        assert second_run == []
    finally:
        _cleanup(conn)
        conn.close()


def test_apply_migrations_detects_drift(
    migrated_test_db_url: str, fabricated_migrations_dir: Path
) -> None:
    conn = psycopg.connect(migrated_test_db_url)
    try:
        apply_migrations(conn, fabricated_migrations_dir)

        tampered_file = fabricated_migrations_dir / f"{_VERSION}.sql"
        tampered_file.write_text(_SQL + "\n-- tampered after being applied\n")

        with pytest.raises(MigrationDriftError):
            apply_migrations(conn, fabricated_migrations_dir)
    finally:
        _cleanup(conn)
        conn.close()
