from __future__ import annotations

import random

from opportunity_engine.domain.enums import DetectionStrategyName
from opportunity_engine.domain.models import ScoredOpportunity
from opportunity_engine.tools.ranking import (
    RankingConfig,
    build_backlog,
    is_eligible_for_resurfacing,
)


def _scored(
    opportunity_id: int,
    strategy: DetectionStrategyName,
    score: float,
    category: str | None = None,
    last_proposed_score: float | None = None,
) -> ScoredOpportunity:
    return ScoredOpportunity(
        opportunity_id=opportunity_id,
        strategy=strategy,
        category=category,
        composite_score=score,
        last_proposed_score=last_proposed_score,
    )


def test_never_proposed_is_always_eligible() -> None:
    assert is_eligible_for_resurfacing(_scored(1, DetectionStrategyName.PAIN_DRIVEN, 50.0))


def test_small_score_change_is_not_eligible_for_resurfacing() -> None:
    scored = _scored(1, DetectionStrategyName.PAIN_DRIVEN, 52.0, last_proposed_score=50.0)
    assert not is_eligible_for_resurfacing(scored, resurface_score_delta_pct=0.40)


def test_large_score_change_is_eligible_for_resurfacing() -> None:
    scored = _scored(1, DetectionStrategyName.PAIN_DRIVEN, 80.0, last_proposed_score=50.0)
    assert is_eligible_for_resurfacing(scored, resurface_score_delta_pct=0.40)


def test_score_change_exactly_at_threshold_is_eligible() -> None:
    scored = _scored(1, DetectionStrategyName.PAIN_DRIVEN, 70.0, last_proposed_score=50.0)
    assert is_eligible_for_resurfacing(scored, resurface_score_delta_pct=0.40)


def test_build_backlog_is_deterministic_with_a_seeded_rng() -> None:
    candidates = [
        _scored(i, DetectionStrategyName.PAIN_DRIVEN, float(i), category=f"cat{i % 3}")
        for i in range(30)
    ]
    cfg = RankingConfig(top_n=10, strategy_quota={"pain_driven": 1.0}, exploration_share=0.3)

    result_a = build_backlog(candidates, cfg, set(), random.Random(42))
    result_b = build_backlog(candidates, cfg, set(), random.Random(42))

    ids_a = [slot.scored.opportunity_id for slot in result_a]
    ids_b = [slot.scored.opportunity_id for slot in result_b]
    assert ids_a == ids_b


def test_exploit_slots_are_highest_scored_first() -> None:
    candidates = [_scored(i, DetectionStrategyName.PAIN_DRIVEN, float(i)) for i in range(20)]
    cfg = RankingConfig(top_n=10, strategy_quota={"pain_driven": 1.0}, exploration_share=0.0)

    result = build_backlog(candidates, cfg, set(), random.Random(1))

    scores = [slot.scored.composite_score for slot in result]
    assert scores == sorted(scores, reverse=True)
    assert all(not slot.is_exploration_slot for slot in result)


def test_strategy_quota_is_respected_when_enough_candidates_exist() -> None:
    arbitrage = [_scored(i, DetectionStrategyName.ARBITRAGE, 100.0 - i) for i in range(20)]
    pain_driven = [
        _scored(100 + i, DetectionStrategyName.PAIN_DRIVEN, 100.0 - i) for i in range(20)
    ]
    cfg = RankingConfig(
        top_n=10,
        strategy_quota={"arbitrage": 0.60, "pain_driven": 0.40},
        exploration_share=0.0,
        max_category_share=1.0,
    )

    result = build_backlog(arbitrage + pain_driven, cfg, set(), random.Random(1))

    strategies = [str(slot.scored.strategy) for slot in result]
    assert strategies.count("arbitrage") == 6
    assert strategies.count("pain_driven") == 4


def test_strategy_quota_backfills_when_one_strategy_is_scarce() -> None:
    """Only 2 arbitrage candidates exist -- the 60% quota (6 of 10) can't be
    met, so the remaining slots must still fill from pain_driven rather than
    leaving the backlog short."""
    arbitrage = [_scored(i, DetectionStrategyName.ARBITRAGE, 90.0 - i) for i in range(2)]
    pain_driven = [
        _scored(100 + i, DetectionStrategyName.PAIN_DRIVEN, 100.0 - i) for i in range(20)
    ]
    cfg = RankingConfig(
        top_n=10,
        strategy_quota={"arbitrage": 0.60, "pain_driven": 0.40},
        exploration_share=0.0,
        max_category_share=1.0,
    )

    result = build_backlog(arbitrage + pain_driven, cfg, set(), random.Random(1))

    assert len(result) == 10
    strategies = [str(slot.scored.strategy) for slot in result]
    assert strategies.count("arbitrage") == 2


def test_category_cap_prevents_one_category_from_dominating() -> None:
    candidates = [
        _scored(i, DetectionStrategyName.PAIN_DRIVEN, 100.0 - i, category="dominant")
        for i in range(20)
    ] + [
        _scored(100 + i, DetectionStrategyName.PAIN_DRIVEN, 50.0 - i, category=f"other{i}")
        for i in range(20)
    ]
    cfg = RankingConfig(
        top_n=10,
        strategy_quota={"pain_driven": 1.0},
        exploration_share=0.0,
        max_category_share=0.30,
    )

    result = build_backlog(candidates, cfg, set(), random.Random(1))

    dominant_count = sum(1 for slot in result if slot.scored.category == "dominant")
    assert dominant_count <= 3  # 30% of 10


def test_exploration_slots_are_present_and_flagged() -> None:
    candidates = [
        _scored(i, DetectionStrategyName.PAIN_DRIVEN, float(50 - i), category=f"cat{i}")
        for i in range(20)
    ]
    cfg = RankingConfig(top_n=10, strategy_quota={"pain_driven": 1.0}, exploration_share=0.3)

    result = build_backlog(candidates, cfg, set(), random.Random(1))

    exploration_slots = [slot for slot in result if slot.is_exploration_slot]
    assert len(exploration_slots) == round(10 * 0.3)


def test_exploration_prefers_underexplored_categories() -> None:
    seen_before = _scored(1, DetectionStrategyName.PAIN_DRIVEN, 40.0, category="seen")
    never_seen = _scored(2, DetectionStrategyName.PAIN_DRIVEN, 40.0, category="fresh")
    # both would-be exploit candidates are pushed out by a flood of higher scores
    filler = [
        _scored(100 + i, DetectionStrategyName.PAIN_DRIVEN, 90.0, category=f"filler{i}")
        for i in range(9)
    ]
    cfg = RankingConfig(top_n=10, strategy_quota={"pain_driven": 1.0}, exploration_share=0.1)

    result = build_backlog(filler + [seen_before, never_seen], cfg, {"seen"}, random.Random(1))

    exploration_slot = next(slot for slot in result if slot.is_exploration_slot)
    assert exploration_slot.scored.opportunity_id == 2


def test_already_proposed_opportunity_below_resurface_threshold_is_excluded() -> None:
    stale = _scored(1, DetectionStrategyName.PAIN_DRIVEN, 51.0, last_proposed_score=50.0)
    fresh = _scored(2, DetectionStrategyName.PAIN_DRIVEN, 90.0)
    cfg = RankingConfig(top_n=1, strategy_quota={"pain_driven": 1.0}, exploration_share=0.0)

    result = build_backlog([stale, fresh], cfg, set(), random.Random(1))

    assert [slot.scored.opportunity_id for slot in result] == [2]


def test_strong_momentum_opportunity_reaches_top_ten_against_established_competitors() -> None:
    """Acceptance criterion #6, pure-ranking half: given a composite score
    that reflects strong momentum, the opportunity must surface in the top 10
    even against a full field of pre-existing candidates. The momentum
    computation itself (7d vs 8-week baseline) is exercised end to end in
    the ScoringAgent/RankingAgent integration test."""
    established = [
        _scored(i, DetectionStrategyName.PAIN_DRIVEN, 60.0, category=f"cat{i}") for i in range(30)
    ]
    injected = _scored(999, DetectionStrategyName.PAIN_DRIVEN, 95.0, category="new")
    cfg = RankingConfig(top_n=10, strategy_quota={"pain_driven": 1.0}, exploration_share=0.0)

    result = build_backlog(established + [injected], cfg, set(), random.Random(1))

    assert 999 in [slot.scored.opportunity_id for slot in result]
