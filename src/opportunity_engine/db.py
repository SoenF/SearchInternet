"""Postgres connection handling.

Postgres is a permanent, assumed choice for this project (see CLAUDE.md) --
this module is deliberately concrete, not an abstraction over "some
database". No connection pool: the CLI is a short-lived, single-connection-
per-invocation process, and nothing else in this codebase needs concurrent
connections yet -- add one if and when something actually does.
"""

from __future__ import annotations

from typing import Any

import psycopg
from pgvector.psycopg import register_vector


def connect(database_url: str) -> psycopg.Connection[Any]:
    conn = psycopg.connect(database_url, autocommit=False)
    register_vector(conn)
    return conn
