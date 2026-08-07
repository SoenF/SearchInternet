"""Pure dedup decision: merge / novel / gray_zone, given only the similarity
to the single nearest existing opportunity centroid. No DB access here --
agents/dedup_agent.py does the querying (via tools.clustering) and the
merge/create side effects; this module is the decision rule alone, which is
exactly what acceptance criterion #2 (no semantic duplicate in the top-20)
needs to be independently unit-testable with synthetic vectors.

Calibration note: empirically, multilingual-e5-base's cosine similarity for
short English sentences (HN-post-title length) is compressed into a
surprisingly narrow band -- genuinely unrelated pairs still often score
~0.79-0.83, not near 0. The 0.75/0.92 defaults below are therefore a
reasonable starting point, not a validated calibration; expect the gray zone
to catch more than a hand-wavy "10-17% width" estimate would suggest until
these are tuned against real production data.
"""

from __future__ import annotations

from dataclasses import dataclass

from opportunity_engine.domain.enums import DedupDecision
from opportunity_engine.tools.clustering import CentroidMatch


@dataclass(frozen=True)
class DedupResult:
    decision: DedupDecision
    matched_opportunity_id: int | None = None
    similarity: float | None = None


def classify_document(
    nearest: CentroidMatch | None,
    *,
    merge_threshold: float = 0.92,
    novel_threshold: float = 0.75,
) -> DedupResult:
    if nearest is None:
        return DedupResult(decision=DedupDecision.NOVEL)
    if nearest.similarity >= merge_threshold:
        return DedupResult(DedupDecision.MERGE, nearest.opportunity_id, nearest.similarity)
    if nearest.similarity < novel_threshold:
        return DedupResult(DedupDecision.NOVEL, similarity=nearest.similarity)
    return DedupResult(DedupDecision.GRAY_ZONE, nearest.opportunity_id, nearest.similarity)
