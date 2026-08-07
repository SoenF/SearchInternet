"""Phase 3: bulk-import a local historical Reddit dump (Pushshift-format
NDJSON, optionally zstandard-compressed) into raw_documents, then run the
same dedup + daily-signal-rollup machinery Phase 1-2 already has -- so a
freshly imported opportunity gets an instant multi-week momentum baseline
instead of waiting MOMENTUM_MIN_BASELINE_DAYS of live daily `run_scoring`
calls to accumulate one from scratch.

This project does not bundle, link to, or hardcode a specific dump file or
download URL: Pushshift dumps are third-party-mirrored (Pushshift itself
lost official Reddit API access in 2023) and mirror availability changes
over time. Point `--file` at whatever dump you have separately obtained.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from opportunity_engine.agents.dedup_agent import run_dedup
from opportunity_engine.agents.scoring_agent import rollup_daily_signal
from opportunity_engine.clock import Clock, utc_now
from opportunity_engine.collectors.reddit import RedditCollector
from opportunity_engine.providers.embedding_provider import EmbeddingProvider
from opportunity_engine.tools.reddit_archive_parsing import parse_pushshift_submission
from opportunity_engine.tools.storage import store_raw_document, upsert_connector_manifest

logger = logging.getLogger(__name__)

_COMMIT_EVERY = 1000


@dataclass
class ArchiveImportStats:
    lines_read: int = 0
    documents_stored: int = 0
    skipped_wrong_subreddit: int = 0
    skipped_malformed: int = 0
    opportunity_days_backfilled: int = 0


def _iter_lines(path: Path) -> Iterator[str]:
    if path.suffix == ".zst":
        import zstandard

        with (
            path.open("rb") as raw,
            zstandard.ZstdDecompressor(max_window_size=2**31).stream_reader(raw) as reader,
        ):
            yield from io.TextIOWrapper(reader, encoding="utf-8", errors="ignore")
    else:
        with path.open("r", encoding="utf-8") as text_stream:
            yield from text_stream


def run_archive_import(
    conn: psycopg.Connection[Any],
    embedding_provider: EmbeddingProvider,
    path: Path,
    *,
    subreddits: frozenset[str] | None = None,
    clock: Clock = utc_now,
) -> ArchiveImportStats:
    stats = ArchiveImportStats()
    upsert_connector_manifest(conn, RedditCollector.manifest, enabled=True)
    conn.commit()

    fetched_at = clock()
    wanted = {name.lower() for name in subreddits} if subreddits else None
    imported_ids: list[int] = []

    for line in _iter_lines(path):
        line = line.strip()
        if not line:
            continue
        stats.lines_read += 1
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            stats.skipped_malformed += 1
            continue

        subreddit = str(record.get("subreddit") or "").lower()
        if wanted is not None and subreddit not in wanted:
            stats.skipped_wrong_subreddit += 1
            continue

        try:
            doc = parse_pushshift_submission(record, fetched_at)
        except (KeyError, ValueError, TypeError):
            stats.skipped_malformed += 1
            continue

        imported_ids.append(store_raw_document(conn, doc))
        stats.documents_stored += 1
        if stats.documents_stored % _COMMIT_EVERY == 0:
            conn.commit()
            logger.info(
                "archive import progress", extra={"documents_stored": stats.documents_stored}
            )
    conn.commit()

    run_dedup(conn, embedding_provider)

    if imported_ids:
        touched = conn.execute(
            """
            SELECT DISTINCT os.opportunity_id, rd.published_at::date
            FROM opportunity_sources os
            JOIN raw_documents rd ON rd.id = os.raw_document_id
            WHERE rd.id = ANY(%s) AND rd.published_at IS NOT NULL
            """,
            (imported_ids,),
        ).fetchall()
        for opportunity_id, signal_date in touched:
            rollup_daily_signal(conn, opportunity_id, signal_date)
            stats.opportunity_days_backfilled += 1
        conn.commit()

    return stats
