"""Pain-driven detection: recurring complaints/friction -> clustering (done
upstream by DedupAgent) -> momentum. No hard elimination gate of its own
beyond the shared buildability/vendability gates -- a candidate reaching this
strategy already came from an HN Ask/Show document, so evaluate() records
which pain-language cues matched (informational) rather than filtering on it.
"""

from __future__ import annotations

from typing import ClassVar

from opportunity_engine.domain.enums import DetectionStrategyName
from opportunity_engine.domain.models import CandidateEvidence, StrategyEvaluation
from opportunity_engine.strategies.base import DetectionStrategy

PAIN_KEYWORDS = (
    "i wish there was",
    "is there a tool that",
    "is there a way to",
    "so tired of using",
    "why is there no",
    "someone should build",
    "does anyone know a tool",
    "looking for a tool",
    "sick of manually",
)

# Data-quality guard, not part of the original spec: a single unconfirmed
# complaint shouldn't be able to dominate momentum on its own. Tunable/
# removable if it proves too strict at Phase 1's low candidate volume --
# flagged here as an addition, not a spec requirement.
MIN_DISTINCT_SOURCES = 1


class PainDrivenStrategy(DetectionStrategy):
    name: ClassVar[DetectionStrategyName] = DetectionStrategyName.PAIN_DRIVEN

    def evaluate(self, evidence: CandidateEvidence) -> StrategyEvaluation:
        if evidence.distinct_source_count < MIN_DISTINCT_SOURCES:
            return StrategyEvaluation(
                accepted=False,
                rejection_reason="pain_driven:insufficient_distinct_sources",
                evidence={"distinct_source_count": evidence.distinct_source_count},
            )
        lowered = evidence.text.lower()
        matched = [keyword for keyword in PAIN_KEYWORDS if keyword in lowered]
        return StrategyEvaluation(accepted=True, evidence={"matched_pain_keywords": matched})
