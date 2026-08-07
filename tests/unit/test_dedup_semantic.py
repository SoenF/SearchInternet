"""Backs acceptance criterion #2 (no semantic duplicate in the top-20) --
synthetic similarity scores, no embedding model needed.
"""

from __future__ import annotations

from opportunity_engine.domain.enums import DedupDecision
from opportunity_engine.tools.clustering import CentroidMatch
from opportunity_engine.tools.dedup import classify_document


def test_no_existing_opportunity_is_always_novel() -> None:
    result = classify_document(None)
    assert result.decision == DedupDecision.NOVEL
    assert result.matched_opportunity_id is None


def test_high_similarity_merges() -> None:
    result = classify_document(CentroidMatch(opportunity_id=42, similarity=0.95))
    assert result.decision == DedupDecision.MERGE
    assert result.matched_opportunity_id == 42


def test_similarity_at_merge_threshold_merges() -> None:
    result = classify_document(
        CentroidMatch(opportunity_id=1, similarity=0.92), merge_threshold=0.92
    )
    assert result.decision == DedupDecision.MERGE


def test_low_similarity_is_novel() -> None:
    result = classify_document(CentroidMatch(opportunity_id=7, similarity=0.3))
    assert result.decision == DedupDecision.NOVEL
    assert result.matched_opportunity_id is None


def test_similarity_just_below_novel_threshold_is_novel() -> None:
    result = classify_document(
        CentroidMatch(opportunity_id=7, similarity=0.749), novel_threshold=0.75
    )
    assert result.decision == DedupDecision.NOVEL


def test_mid_range_similarity_is_gray_zone() -> None:
    result = classify_document(CentroidMatch(opportunity_id=9, similarity=0.8))
    assert result.decision == DedupDecision.GRAY_ZONE
    assert result.matched_opportunity_id == 9


def test_gray_zone_boundaries_are_inclusive_of_novel_exclusive_of_merge() -> None:
    at_novel_threshold = classify_document(
        CentroidMatch(opportunity_id=1, similarity=0.75), novel_threshold=0.75
    )
    assert at_novel_threshold.decision == DedupDecision.GRAY_ZONE

    just_below_merge_threshold = classify_document(
        CentroidMatch(opportunity_id=1, similarity=0.9199), merge_threshold=0.92
    )
    assert just_below_merge_threshold.decision == DedupDecision.GRAY_ZONE
