"""Arbitrage detection: proven traction in market A, absent (with an
identified barrier) in market B. Enforces the spec's single hardest rule --
no identified barrier means automatic rejection. Without a barrier, the
original market's incumbent can simply internationalize and crush a clone,
so an arbitrage opportunity with no barrier isn't deranked, it's REJECTED.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import ClassVar

from opportunity_engine.domain.enums import DetectionStrategyName, RejectionReason
from opportunity_engine.domain.models import CandidateEvidence, StrategyEvaluation
from opportunity_engine.strategies.base import DetectionStrategy
from opportunity_engine.tools.arbitrage_signals import (
    language_localization_barrier,
    payment_distribution_barrier,
    regulatory_barrier,
    wikipedia_cross_language_asymmetry,
)


class ArbitrageStrategy(DetectionStrategy):
    name: ClassVar[DetectionStrategyName] = DetectionStrategyName.ARBITRAGE

    def evaluate(self, evidence: CandidateEvidence) -> StrategyEvaluation:
        barriers = []

        primary = language_localization_barrier(evidence)
        if primary is not None:
            barriers.append(primary)

        regulatory = regulatory_barrier(evidence)
        if regulatory is not None:
            barriers.append(regulatory)

        has_standalone_barrier = bool(barriers)  # primary or regulatory, so far

        secondary = payment_distribution_barrier(evidence, has_primary_barrier=primary is not None)
        if secondary is not None:
            barriers.append(secondary)

        corroborating = wikipedia_cross_language_asymmetry(evidence)
        if corroborating is not None and has_standalone_barrier:
            barriers.append(corroborating)

        if not barriers:
            return StrategyEvaluation(
                accepted=False,
                rejection_reason=RejectionReason.ARBITRAGE_NO_BARRIER_IDENTIFIED,
            )
        return StrategyEvaluation(accepted=True, barriers=[asdict(b) for b in barriers])
