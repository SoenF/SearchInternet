"""CLI entrypoint: `python -m opportunity_engine.cli.main <command>`.

Each subcommand is a thin wrapper around one agent function -- all the real
logic lives in agents/, tools/, and collectors/, which is what's actually
tested. This file just wires Settings -> a DB connection -> the right agent
call, and prints a one-line summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg

from opportunity_engine.agents.archive_import_agent import run_archive_import
from opportunity_engine.agents.dedup_agent import run_dedup
from opportunity_engine.agents.deep_dive_agent import DEFAULT_BUDGET_USD, run_deep_dive
from opportunity_engine.agents.ingestion_agent import run_ingestion
from opportunity_engine.agents.ranking_agent import run_ranking
from opportunity_engine.agents.scoring_agent import run_scoring
from opportunity_engine.clock import utc_now
from opportunity_engine.collectors.registry import build_enabled_collectors
from opportunity_engine.config import Settings
from opportunity_engine.db import connect as _connect_db
from opportunity_engine.domain.models import TrackedTopic
from opportunity_engine.logging_setup import configure_logging
from opportunity_engine.migration_runner import apply_migrations
from opportunity_engine.providers.embedding_provider import LocalE5EmbeddingProvider
from opportunity_engine.providers.llm_provider import MODEL_HAIKU, MODEL_SONNET, AnthropicProvider
from opportunity_engine.tools.ranking import RankingConfig
from opportunity_engine.tools.scoring_tools import MomentumConfig
from opportunity_engine.tools.storage import add_tracked_topic, upsert_connector_manifest

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


def _connect(settings: Settings) -> psycopg.Connection[Any]:
    return _connect_db(settings.database_url)


def cmd_migrate(args: argparse.Namespace, settings: Settings) -> None:
    conn = _connect(settings)
    applied = apply_migrations(conn, MIGRATIONS_DIR)
    print(
        f"applied {len(applied)} migration(s): {applied}" if applied else "database is up to date"
    )


def cmd_ingest(args: argparse.Namespace, settings: Settings) -> None:
    conn = _connect(settings)
    until = utc_now()
    since = until - timedelta(days=args.days)
    collectors = build_enabled_collectors(settings, conn)
    result = run_ingestion(conn, collectors, since, until)
    for name, count in result.items():
        print(f"{name}: {count} document(s) stored")


def cmd_dedup(args: argparse.Namespace, settings: Settings) -> None:
    conn = _connect(settings)
    provider = LocalE5EmbeddingProvider(
        model_name=settings.embedding_model_name, device=settings.embedding_device
    )
    stats = run_dedup(
        conn,
        provider,
        merge_threshold=settings.dedup_merge_threshold,
        novel_threshold=settings.dedup_novel_threshold,
    )
    print(
        f"merged={stats.merged} novel={stats.novel} gray_zone={stats.gray_zone} "
        f"wikipedia_linked={stats.wikipedia_linked} skipped_no_text={stats.skipped_no_text}"
    )


def cmd_score(args: argparse.Namespace, settings: Settings) -> None:
    conn = _connect(settings)
    momentum_cfg = MomentumConfig(
        recent_days=settings.momentum_recent_days,
        baseline_days=settings.momentum_baseline_days,
        min_baseline_days=settings.momentum_min_baseline_days,
    )
    stats = run_scoring(conn, momentum_cfg=momentum_cfg)
    print(f"scored={stats.scored} rejected={stats.rejected}")


def cmd_rank(args: argparse.Namespace, settings: Settings) -> None:
    conn = _connect(settings)
    cfg = RankingConfig(
        top_n=settings.backlog_top_n,
        strategy_quota={
            "arbitrage": settings.backlog_arbitrage_quota,
            "pain_driven": 1.0 - settings.backlog_arbitrage_quota,
        },
        max_category_share=settings.backlog_max_category_share,
        exploration_share=settings.backlog_exploration_share,
        resurface_score_delta_pct=settings.resurface_score_delta_pct,
    )
    count = run_ranking(conn, cfg=cfg)
    print(f"wrote {count} backlog slot(s)")


def cmd_track_topic(args: argparse.Namespace, settings: Settings) -> None:
    conn = _connect(settings)
    topic = TrackedTopic(project=args.project, article=args.article)
    add_tracked_topic(
        conn, topic, args.label or args.article, added_by_opportunity_id=args.opportunity_id
    )
    conn.commit()
    print(f"tracking {topic.project}:{topic.article}")


def cmd_sync_connectors(args: argparse.Namespace, settings: Settings) -> None:
    conn = _connect(settings)
    for collector in build_enabled_collectors(settings, conn):
        upsert_connector_manifest(conn, collector.manifest, enabled=True)
    conn.commit()
    print("connector manifests synced")


def cmd_deep_dive(args: argparse.Namespace, settings: Settings) -> None:
    conn = _connect(settings)
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required to run deep-dive")
    provider = AnthropicProvider(api_key=settings.anthropic_api_key)
    model = MODEL_SONNET if args.escalate else MODEL_HAIKU
    result = run_deep_dive(
        conn,
        provider,
        args.opportunity_id,
        model=model,
        escalation_reason=args.reason,
        budget_usd=args.budget_usd,
    )
    print(f"model={result.model} cost_usd={result.cost_usd:.4f}")
    print(json.dumps(result.content, indent=2))


def cmd_import_archive(args: argparse.Namespace, settings: Settings) -> None:
    conn = _connect(settings)
    provider = LocalE5EmbeddingProvider(
        model_name=settings.embedding_model_name, device=settings.embedding_device
    )
    subreddits = frozenset(args.subreddits.split(",")) if args.subreddits else None
    stats = run_archive_import(conn, provider, Path(args.file), subreddits=subreddits)
    print(
        f"lines_read={stats.lines_read} documents_stored={stats.documents_stored} "
        f"skipped_wrong_subreddit={stats.skipped_wrong_subreddit} "
        f"skipped_malformed={stats.skipped_malformed} "
        f"opportunity_days_backfilled={stats.opportunity_days_backfilled}"
    )


def cmd_run_daily(args: argparse.Namespace, settings: Settings) -> None:
    """The composite command: ingest -> dedup -> score -> rank. Migrations
    are applied separately (`migrate`), not implicitly here, so a schema
    change is always a deliberate, visible step."""
    print("== ingest ==")
    cmd_ingest(args, settings)
    print("== dedup ==")
    cmd_dedup(args, settings)
    print("== score ==")
    cmd_score(args, settings)
    print("== rank ==")
    cmd_rank(args, settings)


COMMANDS: dict[str, Callable[[argparse.Namespace, Settings], None]] = {
    "migrate": cmd_migrate,
    "ingest": cmd_ingest,
    "dedup": cmd_dedup,
    "score": cmd_score,
    "rank": cmd_rank,
    "track-topic": cmd_track_topic,
    "sync-connectors": cmd_sync_connectors,
    "deep-dive": cmd_deep_dive,
    "import-archive": cmd_import_archive,
    "run-daily": cmd_run_daily,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opportunity-engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("migrate", help="apply pending database migrations")

    ingest_parser = subparsers.add_parser("ingest", help="run enabled collectors")
    ingest_parser.add_argument(
        "--days", type=int, default=1, help="how many days back to fetch (default: 1)"
    )

    subparsers.add_parser("dedup", help="embed new documents and merge/create opportunities")
    subparsers.add_parser("score", help="score active opportunities and apply rejection gates")
    subparsers.add_parser("rank", help="build today's ranked backlog")

    track_topic_parser = subparsers.add_parser(
        "track-topic", help="watch a Wikipedia article for pageview momentum"
    )
    track_topic_parser.add_argument("project", help="e.g. en.wikipedia")
    track_topic_parser.add_argument("article", help="exact Wikipedia article title")
    track_topic_parser.add_argument("--label", help="human-readable label (default: article title)")
    track_topic_parser.add_argument(
        "--opportunity-id", type=int, help="opportunity this topic corroborates, if any"
    )

    subparsers.add_parser(
        "sync-connectors", help="upsert connector manifests into the connectors table"
    )

    deep_dive_parser = subparsers.add_parser(
        "deep-dive", help="on-demand LLM dossier for a single opportunity (Phase 4, spends money)"
    )
    deep_dive_parser.add_argument("opportunity_id", type=int)
    deep_dive_parser.add_argument(
        "--escalate", action="store_true", help="use Sonnet instead of the default Haiku"
    )
    deep_dive_parser.add_argument(
        "--reason", help="required with --escalate: why Haiku wasn't good enough"
    )
    deep_dive_parser.add_argument(
        "--budget-usd", type=float, default=DEFAULT_BUDGET_USD, dest="budget_usd"
    )

    import_archive_parser = subparsers.add_parser(
        "import-archive",
        help=(
            "bulk-import a local historical Reddit dump (Pushshift-format NDJSON, "
            "optionally .zst) for an instant momentum baseline (Phase 3)"
        ),
    )
    import_archive_parser.add_argument("file", help="path to a .jsonl/.ndjson or .zst dump")
    import_archive_parser.add_argument(
        "--subreddits",
        help="comma-separated allowlist to filter the dump by (default: import every subreddit)",
    )

    run_daily_parser = subparsers.add_parser(
        "run-daily", help="composite: ingest -> dedup -> score -> rank"
    )
    run_daily_parser.add_argument("--days", type=int, default=1)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    COMMANDS[args.command](args, settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
