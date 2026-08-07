"""Applies migrations/*.sql in order, tracking what's been applied.

Deliberately not Alembic/SQLAlchemy: migrations are plain, numbered SQL files
and this ~40-line runner is the entire "ORM" this project has.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import psycopg


class MigrationDriftError(RuntimeError):
    """Raised when an already-applied migration file's contents changed on disk."""


def ensure_schema_migrations_table(conn: psycopg.Connection[Any]) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    text PRIMARY KEY,
            checksum   text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    conn.commit()


def apply_migrations(conn: psycopg.Connection[Any], migrations_dir: Path) -> list[str]:
    ensure_schema_migrations_table(conn)
    applied = dict(conn.execute("SELECT version, checksum FROM schema_migrations").fetchall())
    newly_applied: list[str] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        version = path.stem
        sql = path.read_text()
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        if version in applied:
            if applied[version] != checksum:
                raise MigrationDriftError(
                    f"{version} was modified after being applied "
                    f"(recorded checksum {applied[version]!r}, on-disk {checksum!r})"
                )
            continue
        with conn.transaction():
            conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                (version, checksum),
            )
        newly_applied.append(version)
    conn.commit()
    return newly_applied
