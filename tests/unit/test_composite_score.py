from __future__ import annotations

from opportunity_engine.domain.enums import MomentumConfidence
from opportunity_engine.domain.models import MomentumResult
from opportunity_engine.tools.scope_classifier import (
    COMPOSITE_SCOPE_WEIGHT,
    ScopeAssessment,
    classify_scope,
)
from opportunity_engine.tools.scoring_tools import (
    COMPOSITE_MARKET_PROOF_WEIGHT,
    COMPOSITE_MOMENTUM_WEIGHT,
    compute_composite_score,
)

_OK_MOMENTUM = MomentumResult(score=2.0, confidence=MomentumConfidence.OK)
_INSUFFICIENT_MOMENTUM = MomentumResult(
    score=0.0, confidence=MomentumConfidence.INSUFFICIENT_HISTORY
)


def test_no_scope_argument_behaves_exactly_as_before() -> None:
    assert compute_composite_score(_OK_MOMENTUM, 40.0) == (
        2.0 * COMPOSITE_MOMENTUM_WEIGHT + 40.0 * COMPOSITE_MARKET_PROOF_WEIGHT
    )
    assert compute_composite_score(_INSUFFICIENT_MOMENTUM, 40.0) == 40.0


def test_neutral_scope_does_not_change_the_score() -> None:
    neutral = ScopeAssessment(score=0.0)
    assert compute_composite_score(_INSUFFICIENT_MOMENTUM, 40.0, neutral) == 40.0


def test_narrow_scope_adds_a_bonus() -> None:
    narrow = classify_scope("A simple Chrome extension.")
    assert narrow.score == 0.5  # sanity-check the fixture before trusting the assertion below
    score = compute_composite_score(_INSUFFICIENT_MOMENTUM, 40.0, narrow)
    assert score == 40.0 + 0.5 * COMPOSITE_SCOPE_WEIGHT == 47.5


def test_broad_scope_subtracts_a_penalty() -> None:
    broad = classify_scope("An all-in-one enterprise-grade platform.")
    assert broad.score == -0.5  # sanity-check the fixture before trusting the assertion below
    score = compute_composite_score(_INSUFFICIENT_MOMENTUM, 40.0, broad)
    assert score == 40.0 - 0.5 * COMPOSITE_SCOPE_WEIGHT == 32.5


def test_broad_scope_can_push_a_weak_opportunity_below_zero_before_the_callers_floor() -> None:
    """agents/scoring_agent.py floors the final score at 0 itself (same as
    it already does for the rejection-feedback penalty) -- this function
    intentionally does not floor internally, so a broad-scope idea with
    weak evidence can reach that floor like any other weak idea."""
    broad = classify_scope("An all-in-one enterprise-grade platform ecosystem.")
    score = compute_composite_score(_INSUFFICIENT_MOMENTUM, 0.0, broad)
    assert score < 0.0
