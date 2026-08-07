from __future__ import annotations

from datetime import date

from opportunity_engine.domain.models import ProofEvent
from opportunity_engine.tools.scoring_tools import (
    APP_STORE_RANKING_CONFIDENCE,
    DISCLOSED_REVENUE_CONFIDENCE,
    EDGAR_FUNDING_CONFIDENCE,
    EDGAR_FUNDING_WEIGHT,
    app_store_rank_weight,
    compute_market_proof,
    revenue_weight_for_monthly_amount,
)

AS_OF = date(2026, 8, 7)


def test_single_recent_edgar_event_hits_the_cap() -> None:
    """A single official funding filing alone reaches the maximum score --
    this is what makes "money beats ten intent signals" true by construction:
    intent signals never generate a ProofEvent at all, only this kind of
    evidence does."""
    events = [
        ProofEvent(
            proof_type="edgar_funding",
            observed_at=AS_OF,
            weight=EDGAR_FUNDING_WEIGHT,
            confidence=EDGAR_FUNDING_CONFIDENCE,
        )
    ]
    assert compute_market_proof(events, AS_OF) == 100.0


def test_self_reported_revenue_alone_scores_well_below_edgar() -> None:
    events = [
        ProofEvent(
            proof_type="disclosed_revenue",
            observed_at=AS_OF,
            weight=revenue_weight_for_monthly_amount(5_000),  # $1k-10k/mo bucket -> 70
            confidence=DISCLOSED_REVENUE_CONFIDENCE,
        )
    ]
    score = compute_market_proof(events, AS_OF)
    assert score == 70.0 * DISCLOSED_REVENUE_CONFIDENCE
    assert score < 100.0


def test_decay_halves_score_at_one_half_life() -> None:
    one_year_ago = date(AS_OF.year - 1, AS_OF.month, AS_OF.day)
    events = [
        ProofEvent(
            proof_type="edgar_funding",  # 365-day half-life
            observed_at=one_year_ago,
            weight=EDGAR_FUNDING_WEIGHT,
            confidence=EDGAR_FUNDING_CONFIDENCE,
        )
    ]
    assert compute_market_proof(events, AS_OF) == 50.0


def test_app_store_ranking_decays_fast_but_sustained_charting_accumulates() -> None:
    top_ten_today = ProofEvent(
        proof_type="app_store_ranking",
        observed_at=AS_OF,
        weight=app_store_rank_weight(3),
        confidence=APP_STORE_RANKING_CONFIDENCE,
    )
    assert compute_market_proof([top_ten_today], AS_OF) == app_store_rank_weight(3) * 0.8

    # a month-old ranking (one 30-day half-life) has decayed by half
    a_month_ago = date(2026, 7, 8)
    top_ten_last_month = ProofEvent(
        proof_type="app_store_ranking",
        observed_at=a_month_ago,
        weight=app_store_rank_weight(3),
        confidence=APP_STORE_RANKING_CONFIDENCE,
    )
    decayed_score = compute_market_proof([top_ten_last_month], AS_OF)
    assert decayed_score < compute_market_proof([top_ten_today], AS_OF)


def test_multiple_events_sum_but_are_capped_at_one_hundred() -> None:
    events = [
        ProofEvent(proof_type="edgar_funding", observed_at=AS_OF, weight=100.0, confidence=1.0),
        ProofEvent(proof_type="disclosed_revenue", observed_at=AS_OF, weight=90.0, confidence=0.6),
    ]
    assert compute_market_proof(events, AS_OF) == 100.0


def test_no_proof_events_scores_zero() -> None:
    assert compute_market_proof([], AS_OF) == 0.0


def test_unknown_proof_type_falls_back_to_default_half_life() -> None:
    events = [
        ProofEvent(proof_type="real_transaction", observed_at=AS_OF, weight=80.0, confidence=1.0)
    ]
    # at age 0 the half-life doesn't matter yet -- decay is 1.0 regardless
    assert compute_market_proof(events, AS_OF) == 80.0


def test_revenue_weight_buckets() -> None:
    assert revenue_weight_for_monthly_amount(500) == 40.0
    assert revenue_weight_for_monthly_amount(1_000) == 70.0
    assert revenue_weight_for_monthly_amount(9_999) == 70.0
    assert revenue_weight_for_monthly_amount(10_000) == 90.0


def test_app_store_rank_weight_tiers() -> None:
    assert app_store_rank_weight(1) == 60.0
    assert app_store_rank_weight(10) == 60.0
    assert app_store_rank_weight(11) == 40.0
    assert app_store_rank_weight(50) == 40.0
    assert app_store_rank_weight(51) == 25.0
