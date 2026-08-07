from __future__ import annotations

from opportunity_engine.domain.enums import DetectionStrategyName, RejectionReason
from opportunity_engine.domain.models import CandidateEvidence
from opportunity_engine.tools.scoring_tools import evaluate_vendability


def _evidence(**overrides) -> CandidateEvidence:  # type: ignore[no-untyped-def]
    defaults = {
        "opportunity_id": 1,
        "primary_strategy": DetectionStrategyName.PAIN_DRIVEN,
        "text": "A subscription tool to auto-renew SaaS SSL certificates.",
    }
    defaults.update(overrides)
    return CandidateEvidence(**defaults)


def test_ordinary_subscription_saas_passes_with_no_warnings() -> None:
    result = evaluate_vendability(_evidence())
    assert result.passed
    assert result.reasons == []


def test_regulated_domain_is_rejected() -> None:
    result = evaluate_vendability(_evidence(sic_code="6311"))  # insurance
    assert not result.passed
    assert result.reasons == [RejectionReason.VENDABILITY_REGULATORY_RISK]


def test_lifetime_deal_is_rejected_as_non_recurring() -> None:
    result = evaluate_vendability(_evidence(text="Selling as a one-time lifetime deal on AppSumo."))
    assert not result.passed
    assert result.reasons == [RejectionReason.VENDABILITY_NON_RECURRING_MODEL]


def test_consulting_is_rejected_as_non_recurring() -> None:
    result = evaluate_vendability(
        _evidence(text="Offering consulting services around this workflow.")
    )
    assert not result.passed
    assert result.reasons == [RejectionReason.VENDABILITY_NON_RECURRING_MODEL]


def test_logistics_is_rejected_as_requiring_daily_intervention() -> None:
    result = evaluate_vendability(_evidence(text="A last-mile logistics coordination platform."))
    assert not result.passed
    assert result.reasons == [RejectionReason.VENDABILITY_REQUIRES_DAILY_INTERVENTION]


def test_franchise_is_rejected_as_requiring_daily_intervention() -> None:
    result = evaluate_vendability(_evidence(text="A franchise management tool for on-site staff."))
    assert not result.passed
    assert result.reasons == [RejectionReason.VENDABILITY_REQUIRES_DAILY_INTERVENTION]


def test_personal_blog_source_passes_with_a_warning_not_a_rejection() -> None:
    """The weakest rule here, given only Phase-1 sources: this must never
    auto-reject, only warn -- real judgment is deferred to Phase 4."""
    result = evaluate_vendability(_evidence(source_domain="janedoe.substack.com"))
    assert result.passed
    assert result.reasons == [RejectionReason.VENDABILITY_PERSONAL_BRAND_RISK_WARNING]


def test_distinct_product_domain_has_no_personal_brand_warning() -> None:
    result = evaluate_vendability(_evidence(source_domain="chatmcp.pro"))
    assert result.passed
    assert result.reasons == []


def test_high_competitor_match_count_passes_with_a_warning_not_a_rejection() -> None:
    """Competitors existing isn't itself disqualifying -- it can just as
    easily mean a validated market -- so this must never auto-reject."""
    result = evaluate_vendability(_evidence(competitor_match_count=6))
    assert result.passed
    assert result.reasons == [RejectionReason.VENDABILITY_COMPETITOR_SATURATION_WARNING]


def test_low_competitor_match_count_has_no_saturation_warning() -> None:
    result = evaluate_vendability(_evidence(competitor_match_count=5))
    assert result.passed
    assert result.reasons == []


def test_unchecked_competitor_count_has_no_saturation_warning() -> None:
    result = evaluate_vendability(_evidence(competitor_match_count=None))
    assert result.passed
    assert result.reasons == []
