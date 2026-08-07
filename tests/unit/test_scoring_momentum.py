from __future__ import annotations

from datetime import date, timedelta

from opportunity_engine.domain.enums import MomentumConfidence
from opportunity_engine.domain.models import DailyValue
from opportunity_engine.tools.scoring_tools import (
    MomentumConfig,
    compute_channel_zscore,
    compute_momentum,
)

AS_OF = date(2026, 8, 7)


def _series(as_of: date, days: int, value_fn) -> list[DailyValue]:  # type: ignore[no-untyped-def]
    return [DailyValue(day=as_of - timedelta(days=i), value=value_fn(i)) for i in range(days)]


def test_bootstrap_with_no_history_returns_insufficient_confidence() -> None:
    series = _series(AS_OF, 5, lambda i: 10.0)  # far fewer than min_baseline_days
    result = compute_momentum({"mention_count": series}, AS_OF)
    assert result.confidence == MomentumConfidence.INSUFFICIENT_HISTORY
    assert result.score == 0.0
    assert result.channel_scores == {}


def test_channel_zscore_none_when_baseline_too_short() -> None:
    cfg = MomentumConfig()
    series = _series(AS_OF, 20, lambda i: 10.0)
    assert compute_channel_zscore(series, AS_OF, cfg) is None


def test_zero_activity_with_full_history_is_neutral_not_insufficient() -> None:
    """Full 8-week history of literal zero activity is a real, known signal
    (confidence=ok) -- distinct from week-one bootstrap (confidence=
    insufficient_history), even though both currently produce score 0 vs 50."""
    series = _series(AS_OF, 63, lambda i: 0.0)
    result = compute_momentum({"mention_count": series}, AS_OF)
    assert result.confidence == MomentumConfidence.OK
    assert result.score == 50.0


def test_growth_over_baseline_scores_above_fifty() -> None:
    def value_fn(i: int) -> float:
        return 50.0 if i < 7 else 10.0  # last 7 days spiked vs a steady 10/day baseline

    series = _series(AS_OF, 63, value_fn)
    result = compute_momentum({"mention_count": series}, AS_OF)
    assert result.confidence == MomentumConfidence.OK
    assert result.score > 50.0


def test_decline_under_baseline_scores_below_fifty() -> None:
    def value_fn(i: int) -> float:
        return 2.0 if i < 7 else 10.0  # last 7 days dropped vs a steady 10/day baseline

    series = _series(AS_OF, 63, value_fn)
    result = compute_momentum({"mention_count": series}, AS_OF)
    assert result.confidence == MomentumConfidence.OK
    assert result.score < 50.0


def test_zero_variance_baseline_with_increase_clamps_to_max_score() -> None:
    def value_fn(i: int) -> float:
        return 99.0 if i < 7 else 5.0  # baseline has zero variance (constant 5.0)

    series = _series(AS_OF, 63, value_fn)
    cfg = MomentumConfig()
    z = compute_channel_zscore(series, AS_OF, cfg)
    assert z == 3.0
    result = compute_momentum({"mention_count": series}, AS_OF, cfg)
    assert result.score == 100.0


def test_zero_variance_baseline_with_decrease_clamps_to_min_score() -> None:
    def value_fn(i: int) -> float:
        return 0.0 if i < 7 else 5.0

    series = _series(AS_OF, 63, value_fn)
    result = compute_momentum({"mention_count": series}, AS_OF)
    assert result.score == 0.0
    assert result.confidence == MomentumConfidence.OK


def test_channels_without_enough_history_are_excluded_not_zeroed() -> None:
    full_history = _series(AS_OF, 63, lambda i: 50.0 if i < 7 else 10.0)
    too_short = _series(AS_OF, 10, lambda i: 999.0)

    result = compute_momentum(
        {"mention_count": full_history, "edgar_filing_count": too_short}, AS_OF
    )

    assert result.confidence == MomentumConfidence.OK
    assert set(result.channel_scores.keys()) == {"mention_count"}


def test_weighted_combination_matches_manual_calculation() -> None:
    cfg = MomentumConfig(channel_weights={"a": 1.0, "b": 3.0})
    # channel 'a': strong growth -> z clamps to 3.0 (zero-variance baseline)
    series_a = _series(AS_OF, 63, lambda i: 99.0 if i < 7 else 5.0)
    # channel 'b': strong decline -> z clamps to -3.0
    series_b = _series(AS_OF, 63, lambda i: 0.0 if i < 7 else 5.0)

    result = compute_momentum({"a": series_a, "b": series_b}, AS_OF, cfg)

    expected_weighted_z = (3.0 * 1.0 + -3.0 * 3.0) / 4.0  # = -1.5
    expected_score = 50 + expected_weighted_z / 3 * 50
    assert result.score == expected_score
