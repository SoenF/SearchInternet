"""Against a real (local Docker) Postgres, using the already-cached local
embedding model (mirrors tests/integration/test_dedup_agent.py's pattern) --
exercises the full import -> dedup -> multi-day backfill path that gives a
freshly imported opportunity an instant momentum baseline instead of one
built up over weeks of live daily ingestion.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import psycopg
import pytest

from opportunity_engine.agents.archive_import_agent import run_archive_import
from opportunity_engine.clock import fixed_clock
from opportunity_engine.providers.embedding_provider import LocalE5EmbeddingProvider

_DAY1 = datetime(2025, 1, 1, 12, tzinfo=UTC)
_DAY2 = datetime(2025, 1, 15, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def embedding_provider() -> LocalE5EmbeddingProvider:
    try:
        return LocalE5EmbeddingProvider()
    except OSError as exc:
        pytest.skip(f"multilingual-e5-base not cached locally yet: {exc}")


def _write_dump(path: Path) -> None:
    lines = [
        json.dumps(
            {
                "id": "abc1",
                "subreddit": "SaaS",
                "title": "Ask: is there a tool to auto-renew my SaaS SSL certificates?",
                "selftext": "",
                "created_utc": _DAY1.timestamp(),
                "permalink": "/r/SaaS/comments/abc1/x/",
                "score": 12,
                "num_comments": 3,
            }
        ),
        json.dumps(
            {
                "id": "abc2",
                "subreddit": "SaaS",
                "title": "Is there a tool that automatically renews SSL certs for my SaaS?",
                "selftext": "",
                "created_utc": _DAY2.timestamp(),
                "permalink": "/r/SaaS/comments/abc2/x/",
                "score": 30,
                "num_comments": 5,
            }
        ),
        json.dumps(
            {
                "id": "cat1",
                "subreddit": "cats",
                "title": "My cat knocked another plant off the balcony",
                "selftext": "",
                "created_utc": _DAY1.timestamp(),
                "permalink": "/r/cats/comments/cat1/x/",
            }
        ),
        "{not valid json",
        "",  # blank line, must be skipped silently and not counted anywhere
    ]
    path.write_text("\n".join(lines) + "\n")


def test_import_filters_dedups_and_backfills_multiple_days(
    db_conn: psycopg.Connection[Any], embedding_provider: LocalE5EmbeddingProvider, tmp_path: Path
) -> None:
    dump_path = tmp_path / "dump.jsonl"
    _write_dump(dump_path)

    stats = run_archive_import(
        db_conn,
        embedding_provider,
        dump_path,
        subreddits=frozenset({"SaaS"}),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    assert stats.lines_read == 4  # the blank line isn't counted as a line read
    assert stats.documents_stored == 2
    assert stats.skipped_wrong_subreddit == 1
    assert stats.skipped_malformed == 1

    connector_row = db_conn.execute(
        "SELECT enabled FROM connectors WHERE name = 'reddit'"
    ).fetchone()
    assert connector_row == (True,)

    opportunity_row = db_conn.execute("SELECT id, primary_strategy FROM opportunities").fetchone()
    assert opportunity_row is not None
    opportunity_id, primary_strategy = opportunity_row
    assert primary_strategy == "pain_driven"  # the two near-duplicate SaaS posts merged into one

    source_count = db_conn.execute(
        "SELECT count(*) FROM opportunity_sources WHERE opportunity_id = %s", (opportunity_id,)
    ).fetchone()
    assert source_count == (2,)

    signal_days = db_conn.execute(
        """
        SELECT signal_date, mention_count FROM opportunity_daily_signal
        WHERE opportunity_id = %s ORDER BY signal_date
        """,
        (opportunity_id,),
    ).fetchall()
    assert [d for d, _ in signal_days] == [_DAY1.date(), _DAY2.date()]
    assert all(count == 1 for _, count in signal_days)
    assert stats.opportunity_days_backfilled == 2


def test_import_with_no_subreddit_filter_imports_everything(
    db_conn: psycopg.Connection[Any], embedding_provider: LocalE5EmbeddingProvider, tmp_path: Path
) -> None:
    dump_path = tmp_path / "dump.jsonl"
    _write_dump(dump_path)

    stats = run_archive_import(
        db_conn, embedding_provider, dump_path, clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC))
    )

    assert stats.skipped_wrong_subreddit == 0
    assert stats.documents_stored == 3
