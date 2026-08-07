"""The single hardest rule in the spec: no identified barrier -> automatic
rejection. Every sub-case here traces back to that one rule.
"""

from __future__ import annotations

from datetime import date

from opportunity_engine.domain.enums import DetectionStrategyName, RejectionReason
from opportunity_engine.domain.models import CandidateEvidence, DailyValue
from opportunity_engine.strategies.arbitrage import ArbitrageStrategy


def _evidence(**overrides) -> CandidateEvidence:  # type: ignore[no-untyped-def]
    defaults = {
        "opportunity_id": 1,
        "primary_strategy": DetectionStrategyName.ARBITRAGE,
        "text": "A note-taking app charting in Japan.",
    }
    defaults.update(overrides)
    return CandidateEvidence(**defaults)


def test_no_signals_at_all_is_rejected() -> None:
    result = ArbitrageStrategy().evaluate(_evidence())
    assert not result.accepted
    assert result.rejection_reason == RejectionReason.ARBITRAGE_NO_BARRIER_IDENTIFIED
    assert result.barriers == []


def test_charting_abroad_but_also_present_in_target_market_is_rejected() -> None:
    """Charting in Japan alone proves nothing if the product is already in
    the US market too -- the incumbent can (and did) internationalize."""
    result = ArbitrageStrategy().evaluate(
        _evidence(app_store_chart_countries=frozenset({"jp", "us"}))
    )
    assert not result.accepted
    assert result.rejection_reason == RejectionReason.ARBITRAGE_NO_BARRIER_IDENTIFIED


def test_charting_abroad_with_localized_target_listing_is_rejected() -> None:
    result = ArbitrageStrategy().evaluate(
        _evidence(
            app_store_chart_countries=frozenset({"jp"}),
            app_store_listing_countries=frozenset({"jp", "us"}),
            has_localized_target_listing=True,
        )
    )
    assert not result.accepted


def test_charting_abroad_with_no_target_listing_is_accepted_via_language_barrier() -> None:
    result = ArbitrageStrategy().evaluate(
        _evidence(
            app_store_chart_countries=frozenset({"jp"}),
            app_store_listing_countries=frozenset({"jp"}),
            has_localized_target_listing=False,
        )
    )
    assert result.accepted
    kinds = {b["kind"] for b in result.barriers}
    assert "language_localization_barrier" in kinds


def test_payment_distribution_signal_alone_is_never_sufficient() -> None:
    """Explicitly the weak-alone case from the spec: pricing differences and
    no target-market competitor, with NO language barrier, must still be
    rejected -- "no competitor" alone might just mean "no demand"."""
    result = ArbitrageStrategy().evaluate(
        _evidence(
            app_store_chart_countries=frozenset(),  # no origin-market charting at all
            pricing_varies_by_country=True,
            competitor_in_target_country=False,
        )
    )
    assert not result.accepted
    assert result.rejection_reason == RejectionReason.ARBITRAGE_NO_BARRIER_IDENTIFIED


def test_payment_distribution_signal_combined_with_language_barrier_is_recorded() -> None:
    result = ArbitrageStrategy().evaluate(
        _evidence(
            app_store_chart_countries=frozenset({"jp"}),
            has_localized_target_listing=False,
            pricing_varies_by_country=True,
            competitor_in_target_country=False,
        )
    )
    assert result.accepted
    kinds = {b["kind"] for b in result.barriers}
    assert {"language_localization_barrier", "payment_distribution_barrier"} <= kinds


def test_wikipedia_asymmetry_alone_is_never_sufficient() -> None:
    """Corroborating only -- must never stand alone, even with a strong
    cross-language pageview asymmetry."""
    result = ArbitrageStrategy().evaluate(
        _evidence(
            wikipedia_pageviews_by_project={
                "en.wikipedia": [DailyValue(day=date(2026, 1, 1), value=10.0)],
                "ja.wikipedia": [DailyValue(day=date(2026, 1, 1), value=1000.0)],
            }
        )
    )
    assert not result.accepted
    assert result.rejection_reason == RejectionReason.ARBITRAGE_NO_BARRIER_IDENTIFIED


def test_wikipedia_asymmetry_combined_with_language_barrier_is_recorded() -> None:
    result = ArbitrageStrategy().evaluate(
        _evidence(
            app_store_chart_countries=frozenset({"jp"}),
            has_localized_target_listing=False,
            wikipedia_pageviews_by_project={
                "en.wikipedia": [DailyValue(day=date(2026, 1, 1), value=10.0)],
                "ja.wikipedia": [DailyValue(day=date(2026, 1, 1), value=1000.0)],
            },
        )
    )
    assert result.accepted
    kinds = {b["kind"] for b in result.barriers}
    assert {"language_localization_barrier", "wikipedia_cross_language_asymmetry"} <= kinds


def test_regulatory_barrier_stands_on_its_own() -> None:
    result = ArbitrageStrategy().evaluate(_evidence(sic_code="6022"))  # bank holding company
    assert result.accepted
    kinds = {b["kind"] for b in result.barriers}
    assert kinds == {"regulatory_barrier"}
