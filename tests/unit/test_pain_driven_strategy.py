from __future__ import annotations

from opportunity_engine.domain.enums import DetectionStrategyName
from opportunity_engine.domain.models import CandidateEvidence
from opportunity_engine.strategies.pain_driven import PainDrivenStrategy


def _evidence(**overrides) -> CandidateEvidence:  # type: ignore[no-untyped-def]
    defaults = {
        "opportunity_id": 1,
        "primary_strategy": DetectionStrategyName.PAIN_DRIVEN,
        "text": "Ask HN: is there a tool that auto-renews my SSL certs?",
    }
    defaults.update(overrides)
    return CandidateEvidence(**defaults)


def test_accepts_and_records_matched_pain_keywords() -> None:
    result = PainDrivenStrategy().evaluate(_evidence())
    assert result.accepted
    assert "is there a tool that" in result.evidence["matched_pain_keywords"]


def test_accepts_even_without_a_matched_keyword() -> None:
    """No hard elimination gate beyond distinct-source count -- a candidate
    reaching this strategy already came from an HN doc, keyword matching is
    informational only."""
    result = PainDrivenStrategy().evaluate(_evidence(text="Show HN: a tiny SSL cert renewer"))
    assert result.accepted
    assert result.evidence["matched_pain_keywords"] == []


def test_rejects_below_minimum_distinct_sources() -> None:
    result = PainDrivenStrategy().evaluate(_evidence(distinct_source_count=0))
    assert not result.accepted
    assert result.rejection_reason == "pain_driven:insufficient_distinct_sources"
