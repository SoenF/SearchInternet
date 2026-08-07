"""Fixture-driven: catches our own parser regressing against a known-good
recorded response shape. Does not detect the live API changing shape --
scripts/refresh_fixtures.py is the (manual, non-CI) tool for that. Mirrors
tests/connectors/test_app_store_collector.py.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opportunity_engine.clock import fixed_clock
from opportunity_engine.collectors.app_store_reviews import AppStoreReviewsCollector

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "app_store_reviews"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())  # type: ignore[no-any-return]


def _make_fetch(chart: dict[str, Any], reviews: dict[str, Any]):
    def fake_fetch(url: str) -> dict[str, Any]:
        if "customerreviews" in url:
            return reviews
        return chart

    return fake_fetch


def test_collect_yields_reviews_for_apps_discovered_via_genre_charts() -> None:
    chart = _load("genre_chart_finance.json")
    reviews = _load("reviews_facebook.json")
    collector = AppStoreReviewsCollector(
        fetch=_make_fetch(chart, reviews),
        genres=(("6015", "Finance"),),
        apps_per_genre=5,
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2026, 8, 5, tzinfo=UTC), datetime(2026, 8, 7, tzinfo=UTC))
    )

    num_chart_apps = len(chart["feed"]["entry"])
    num_reviews_per_app = len(
        [
            e
            for e in reviews["feed"]["entry"]
            if datetime(2026, 8, 5, tzinfo=UTC)
            <= datetime.fromisoformat(e["updated"]["label"])
            < datetime(2026, 8, 7, tzinfo=UTC)
        ]
    )
    assert len(docs) == num_chart_apps * num_reviews_per_app
    assert all(d.doc_type == "app_store_review" for d in docs)
    assert all(d.connector_name == "itunes_app_store_reviews" for d in docs)
    assert all(d.category == "Finance" for d in docs)
    assert all(d.fetched_at == datetime(2026, 8, 7, tzinfo=UTC) for d in docs)


def test_collect_filters_reviews_outside_the_window() -> None:
    chart = _load("genre_chart_finance.json")
    reviews = _load("reviews_facebook.json")
    collector = AppStoreReviewsCollector(
        fetch=_make_fetch(chart, reviews), genres=(("6015", "Finance"),), apps_per_genre=1
    )

    docs = list(
        collector.collect(datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 1, 2, tzinfo=UTC))
    )

    assert docs == []


def test_collect_skips_a_single_malformed_review_without_raising() -> None:
    chart = _load("genre_chart_finance.json")
    reviews = copy.deepcopy(_load("reviews_facebook.json"))
    reviews["feed"]["entry"].append({"title": {"label": "missing id, updated, content"}})
    collector = AppStoreReviewsCollector(
        fetch=_make_fetch(chart, reviews),
        genres=(("6015", "Finance"),),
        apps_per_genre=1,
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2026, 8, 5, tzinfo=UTC), datetime(2026, 8, 7, tzinfo=UTC))
    )

    # the malformed entry is skipped; well-formed ones still come through
    assert all(d.title != "missing id, updated, content" for d in docs)


def test_a_failing_genre_chart_does_not_abort_the_others() -> None:
    reviews = _load("reviews_facebook.json")
    good_chart = _load("genre_chart_finance.json")

    def flaky_fetch(url: str) -> dict[str, Any]:
        if "genre=6000" in url:
            raise RuntimeError("simulated outage")
        if "customerreviews" in url:
            return reviews
        return good_chart

    collector = AppStoreReviewsCollector(
        fetch=flaky_fetch,
        genres=(("6000", "Business"), ("6015", "Finance")),
        apps_per_genre=1,
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2026, 8, 5, tzinfo=UTC), datetime(2026, 8, 7, tzinfo=UTC))
    )

    assert len(docs) > 0
    assert all(d.category == "Finance" for d in docs)
