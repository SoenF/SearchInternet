"""Pure, DB-free backlog ranking: quota-respecting exploitation + epsilon-
greedy exploration, deterministic given a seeded RNG. agents/ranking_agent.py
supplies the DB-sourced inputs and persists the result to backlog_snapshots.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from math import ceil

from opportunity_engine.domain.models import BacklogSlot, ScoredOpportunity


@dataclass(frozen=True)
class RankingConfig:
    top_n: int = 20
    strategy_quota: dict[str, float] = field(
        default_factory=lambda: {"arbitrage": 0.60, "pain_driven": 0.40}
    )
    max_category_share: float = 0.30
    exploration_share: float = 0.25
    resurface_score_delta_pct: float = 0.40


DEFAULT_RANKING_CONFIG = RankingConfig()


def is_eligible_for_resurfacing(
    scored: ScoredOpportunity, resurface_score_delta_pct: float = 0.40
) -> bool:
    """An opportunity already shown only reappears once its score has moved
    by at least `resurface_score_delta_pct` -- keeps the backlog from
    converging on a fixed set once every candidate has been surfaced once.
    Never proposed before (`last_proposed_score is None`) is always
    eligible."""
    if scored.last_proposed_score is None:
        return True
    denominator = max(abs(scored.last_proposed_score), 1e-6)
    delta = abs(scored.composite_score - scored.last_proposed_score) / denominator
    return delta >= resurface_score_delta_pct


def _fill_by_score_with_quota(
    candidates: list[ScoredOpportunity],
    n: int,
    strategy_quota: dict[str, float],
    max_category_share: float,
) -> list[ScoredOpportunity]:
    if n <= 0:
        return []
    ranked = sorted(candidates, key=lambda c: c.composite_score, reverse=True)
    strategy_caps = {strategy: ceil(n * quota) for strategy, quota in strategy_quota.items()}
    category_cap = max(1, int(n * max_category_share)) if max_category_share > 0 else n

    selected: list[ScoredOpportunity] = []
    selected_ids: set[int] = set()
    strategy_counts: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)

    def _category_room(candidate: ScoredOpportunity) -> bool:
        return candidate.category is None or category_counts[candidate.category] < category_cap

    # First pass: respect both the strategy quota and the category cap.
    for candidate in ranked:
        if len(selected) >= n:
            break
        strategy_key = str(candidate.strategy)
        cap = strategy_caps.get(strategy_key, n)
        if strategy_counts[strategy_key] >= cap or not _category_room(candidate):
            continue
        selected.append(candidate)
        selected_ids.add(candidate.opportunity_id)
        strategy_counts[strategy_key] += 1
        if candidate.category is not None:
            category_counts[candidate.category] += 1

    # Backfill: if quota constraints under-filled the slots (e.g. not enough
    # arbitrage candidates exist), relax the *strategy* quota -- but never the
    # category cap -- to still reach n from the remaining highest scores.
    if len(selected) < n:
        for candidate in ranked:
            if len(selected) >= n:
                break
            if candidate.opportunity_id in selected_ids or not _category_room(candidate):
                continue
            selected.append(candidate)
            selected_ids.add(candidate.opportunity_id)
            if candidate.category is not None:
                category_counts[candidate.category] += 1

    return selected


def build_backlog(
    candidates: list[ScoredOpportunity],
    cfg: RankingConfig,
    recently_surfaced_categories: set[str],
    rng: random.Random,
) -> list[BacklogSlot]:
    eligible = [
        c for c in candidates if is_eligible_for_resurfacing(c, cfg.resurface_score_delta_pct)
    ]

    exploration_n = round(cfg.top_n * cfg.exploration_share)
    exploit_n = cfg.top_n - exploration_n

    exploit_slots = _fill_by_score_with_quota(
        eligible, exploit_n, cfg.strategy_quota, cfg.max_category_share
    )
    exploit_ids = {c.opportunity_id for c in exploit_slots}
    remaining = [c for c in eligible if c.opportunity_id not in exploit_ids]

    underexplored = [c for c in remaining if c.category not in recently_surfaced_categories]
    exploration_pool = underexplored or remaining
    exploration_slots = (
        rng.sample(exploration_pool, min(exploration_n, len(exploration_pool)))
        if exploration_pool
        else []
    )

    return [BacklogSlot(scored=c, is_exploration_slot=False) for c in exploit_slots] + [
        BacklogSlot(scored=c, is_exploration_slot=True) for c in exploration_slots
    ]
