"""Single-responsibility service: builds the ranked backlog for today's
window from opportunities already scored by ScoringAgent, and persists it to
backlog_snapshots -- the ranking cache, keyed by (window_start, window_end,
rank) so a query can never silently return a stale/frozen ranking (see
CLAUDE.md). Talks to other agents only through the database and the events
log.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

import psycopg

from opportunity_engine.clock import Clock, utc_now
from opportunity_engine.domain.enums import DetectionStrategyName, EventType
from opportunity_engine.domain.models import ScoredOpportunity
from opportunity_engine.events import append_event
from opportunity_engine.tools.ranking import DEFAULT_RANKING_CONFIG, RankingConfig, build_backlog


def run_ranking(
    conn: psycopg.Connection[Any],
    *,
    clock: Clock = utc_now,
    cfg: RankingConfig = DEFAULT_RANKING_CONFIG,
    seed: int | None = None,
) -> int:
    """Returns the number of slots written. window_start == window_end ==
    today, matching a daily cadence. Re-running for the same day is
    idempotent: today's prior snapshot (if any) is replaced, not appended
    to."""
    today = clock().date()
    candidates = _load_scored_opportunities(conn)
    recently_surfaced = _recently_surfaced_categories(conn, today)
    rng = random.Random(seed if seed is not None else today.toordinal())

    slots = build_backlog(candidates, cfg, recently_surfaced, rng)

    conn.execute(
        "DELETE FROM backlog_snapshots WHERE window_start = %s AND window_end = %s",
        (today, today),
    )
    for rank, slot in enumerate(slots, start=1):
        conn.execute(
            """
            INSERT INTO backlog_snapshots
                (window_start, window_end, rank, opportunity_id, composite_score,
                 strategy, category, is_exploration_slot)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                today,
                today,
                rank,
                slot.scored.opportunity_id,
                slot.scored.composite_score,
                str(slot.scored.strategy),
                slot.scored.category,
                slot.is_exploration_slot,
            ),
        )
        _mark_proposed(conn, slot.scored.opportunity_id, slot.scored.composite_score, clock)

    conn.commit()
    return len(slots)


def _load_scored_opportunities(conn: psycopg.Connection[Any]) -> list[ScoredOpportunity]:
    rows = conn.execute(
        """
        SELECT id, primary_strategy, category, current_score, last_proposed_score
        FROM opportunities
        WHERE status IN ('candidate', 'qualified') AND current_score IS NOT NULL
        """
    ).fetchall()
    return [
        ScoredOpportunity(
            opportunity_id=opportunity_id,
            strategy=DetectionStrategyName(strategy),
            category=category,
            composite_score=float(current_score),
            last_proposed_score=float(last_proposed_score)
            if last_proposed_score is not None
            else None,
        )
        for opportunity_id, strategy, category, current_score, last_proposed_score in rows
    ]


def _recently_surfaced_categories(conn: psycopg.Connection[Any], today: date) -> set[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT category FROM backlog_snapshots
        WHERE window_end >= %s AND window_end < %s AND category IS NOT NULL
        """,
        (today - timedelta(days=7), today),
    ).fetchall()
    return {category for (category,) in rows}


def _mark_proposed(
    conn: psycopg.Connection[Any], opportunity_id: int, composite_score: float, clock: Clock
) -> None:
    now = clock()
    conn.execute(
        """
        UPDATE opportunities
        SET last_proposed_at = %s,
            last_proposed_score = %s,
            status = CASE WHEN status = 'candidate' THEN 'qualified' ELSE status END,
            updated_at = %s
        WHERE id = %s
        """,
        (now, composite_score, now, opportunity_id),
    )
    append_event(
        conn,
        EventType.OPPORTUNITY_PROPOSED,
        opportunity_id=opportunity_id,
        payload={"composite_score": composite_score},
    )
