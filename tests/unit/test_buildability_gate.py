from __future__ import annotations

from opportunity_engine.domain.enums import DetectionStrategyName, RejectionReason
from opportunity_engine.domain.models import CandidateEvidence
from opportunity_engine.tools.scoring_tools import evaluate_buildability


def _evidence(**overrides) -> CandidateEvidence:  # type: ignore[no-untyped-def]
    defaults = {
        "opportunity_id": 1,
        "primary_strategy": DetectionStrategyName.PAIN_DRIVEN,
        "text": "A simple tool to auto-renew SaaS SSL certificates.",
    }
    defaults.update(overrides)
    return CandidateEvidence(**defaults)


def test_ordinary_saas_idea_passes() -> None:
    result = evaluate_buildability(_evidence())
    assert result.passed
    assert result.reasons == []


def test_regulated_domain_is_rejected() -> None:
    result = evaluate_buildability(_evidence(sic_code="6022"))
    assert not result.passed
    assert result.reasons == [RejectionReason.BUILDABILITY_REGULATED_DOMAIN]


def test_medical_app_store_genre_is_rejected() -> None:
    result = evaluate_buildability(_evidence(app_store_genre="Medical"))
    assert not result.passed
    assert result.reasons == [RejectionReason.BUILDABILITY_REGULATED_DOMAIN]


def test_heavy_integration_keyword_is_rejected() -> None:
    result = evaluate_buildability(
        _evidence(text="Needs SOC 2 certification before any enterprise sales.")
    )
    assert not result.passed
    assert result.reasons == [RejectionReason.BUILDABILITY_HEAVY_INTEGRATION]


def test_hardware_keyword_is_rejected() -> None:
    result = evaluate_buildability(_evidence(text="Requires custom hardware to manufacture."))
    assert not result.passed
    assert result.reasons == [RejectionReason.BUILDABILITY_HEAVY_INTEGRATION]


def test_large_raise_with_enterprise_keyword_is_rejected() -> None:
    result = evaluate_buildability(
        _evidence(
            text="Targeting enterprise customers exclusively.",
            edgar_offering_amount=5_000_000.0,
        )
    )
    assert not result.passed
    assert result.reasons == [RejectionReason.BUILDABILITY_CAPITAL_INTENSIVE_ENTERPRISE]


def test_large_raise_without_enterprise_keyword_is_not_capital_intensive_rejection() -> None:
    """A large raise alone isn't sufficient -- needs the enterprise-focus
    keyword too, otherwise a well-funded consumer app would be wrongly
    flagged."""
    result = evaluate_buildability(
        _evidence(text="A consumer mood-tracking app.", edgar_offering_amount=5_000_000.0)
    )
    assert result.passed


def test_enterprise_keyword_below_raise_threshold_passes() -> None:
    result = evaluate_buildability(
        _evidence(text="Targeting enterprise customers.", edgar_offering_amount=100_000.0)
    )
    assert result.passed
