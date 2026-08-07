"""DetectionStrategy: pain-driven and arbitrage exist from day one, which is
what justifies this being an interface at all (see CLAUDE.md rule #5).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from opportunity_engine.domain.enums import DetectionStrategyName
from opportunity_engine.domain.models import CandidateEvidence, StrategyEvaluation


class DetectionStrategy(ABC):
    name: ClassVar[DetectionStrategyName]

    @abstractmethod
    def evaluate(self, evidence: CandidateEvidence) -> StrategyEvaluation:
        """Called before scoring. A rejection here is a hard elimination,
        checked before (and separate from) the buildability/vendability
        gates -- ScoringAgent skips momentum/proof/gate computation entirely
        when this rejects."""
        raise NotImplementedError
