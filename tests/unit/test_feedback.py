from __future__ import annotations

from opportunity_engine.tools.clustering import CentroidMatch
from opportunity_engine.tools.feedback import compute_rejection_penalty


def test_no_neighbors_is_zero_penalty() -> None:
    result = compute_rejection_penalty([])
    assert result.points == 0.0
    assert result.contributing_neighbors == []


def test_neighbor_below_threshold_contributes_nothing() -> None:
    result = compute_rejection_penalty(
        [CentroidMatch(opportunity_id=1, similarity=0.5)], threshold=0.85
    )
    assert result.points == 0.0
    assert result.contributing_neighbors == []


def test_neighbor_at_threshold_contributes_nothing() -> None:
    result = compute_rejection_penalty(
        [CentroidMatch(opportunity_id=1, similarity=0.85)], threshold=0.85
    )
    assert result.points == 0.0


def test_perfect_match_contributes_full_per_neighbor_points() -> None:
    result = compute_rejection_penalty(
        [CentroidMatch(opportunity_id=1, similarity=1.0)],
        threshold=0.85,
        per_neighbor_points=15.0,
    )
    assert result.points == 15.0
    assert result.contributing_neighbors == [
        {"opportunity_id": 1, "similarity": 1.0, "points": 15.0}
    ]


def test_midpoint_similarity_contributes_half_points() -> None:
    # threshold=0.80, similarity=0.90 -> halfway to a perfect match (1.0)
    result = compute_rejection_penalty(
        [CentroidMatch(opportunity_id=1, similarity=0.90)],
        threshold=0.80,
        per_neighbor_points=20.0,
    )
    assert result.points == 10.0


def test_multiple_neighbors_sum_but_cap_at_max_penalty() -> None:
    neighbors = [CentroidMatch(opportunity_id=i, similarity=1.0) for i in range(5)]
    result = compute_rejection_penalty(
        neighbors, threshold=0.85, max_penalty=30.0, per_neighbor_points=15.0
    )
    # 5 * 15.0 = 75.0 uncapped, but capped at 30.0
    assert result.points == 30.0
    assert len(result.contributing_neighbors) == 5


def test_mixed_neighbors_only_above_threshold_contribute() -> None:
    neighbors = [
        CentroidMatch(opportunity_id=1, similarity=0.95),
        CentroidMatch(opportunity_id=2, similarity=0.5),
    ]
    result = compute_rejection_penalty(neighbors, threshold=0.85, per_neighbor_points=15.0)
    assert len(result.contributing_neighbors) == 1
    assert result.contributing_neighbors[0]["opportunity_id"] == 1
