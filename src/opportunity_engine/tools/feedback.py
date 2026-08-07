"""Phase 5: a persisted rejection is motivated *and* feeds future scoring --
this module is the "feeds future scoring" half. It is deliberately a soft
scoring penalty, not a hard gate: a candidate resembling past rejections is
suspicious, not automatically guilty. The hard gates (strategy barrier,
buildability, vendability) already ran and passed before this applies; this
only nudges the composite score down for candidates in a rejected
neighborhood, it never overrides a gate decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from opportunity_engine.tools.clustering import CentroidMatch

DEFAULT_PENALTY_THRESHOLD = 0.85
DEFAULT_MAX_PENALTY = 30.0
DEFAULT_PER_NEIGHBOR_POINTS = 15.0


@dataclass(frozen=True)
class RejectionPenalty:
    points: float
    contributing_neighbors: list[dict[str, Any]] = field(default_factory=list)


def compute_rejection_penalty(
    rejected_neighbors: list[CentroidMatch],
    *,
    threshold: float = DEFAULT_PENALTY_THRESHOLD,
    max_penalty: float = DEFAULT_MAX_PENALTY,
    per_neighbor_points: float = DEFAULT_PER_NEIGHBOR_POINTS,
) -> RejectionPenalty:
    """Each rejected neighbor closer than `threshold` contributes a share of
    `per_neighbor_points`, scaled linearly from 0 at the threshold to 1 at a
    perfect match -- a neighbor just past the threshold barely counts, a
    near-duplicate rejected opportunity counts fully. The total is capped at
    `max_penalty` so this can never zero out an otherwise-strong score by
    itself; it nudges, the eliminatory gates decide."""
    contributions = []
    total = 0.0
    for neighbor in rejected_neighbors:
        if neighbor.similarity < threshold:
            continue
        weight = (neighbor.similarity - threshold) / (1.0 - threshold)
        points = weight * per_neighbor_points
        total += points
        contributions.append(
            {
                "opportunity_id": neighbor.opportunity_id,
                "similarity": neighbor.similarity,
                "points": points,
            }
        )
    return RejectionPenalty(points=min(total, max_penalty), contributing_neighbors=contributions)
