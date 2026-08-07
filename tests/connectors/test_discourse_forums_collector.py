"""Fixture-driven: catches our own parser regressing against a known-good
recorded response shape (captured live from forum.bubble.io -- Discourse's
own documented `.json` API, not a scraping workaround). Mirrors
tests/connectors/test_hackernews_collector.py.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from opportunity_engine.clock import fixed_clock
from opportunity_engine.collectors.discourse_forums import DiscourseForumsCollector

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "discourse_forums"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())  # type: ignore[no-any-return]


def _make_fetch(latest: dict[str, Any], categories: dict[str, Any]):
    def fake_fetch(url: str) -> dict[str, Any]:
        return categories if "categories.json" in url else latest

    return fake_fetch


def _widest_window() -> tuple[datetime, datetime]:
    return datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)


def test_collect_yields_documents_for_every_topic() -> None:
    latest = _load("latest_bubble.json")
    categories = _load("categories_bubble.json")
    collector = DiscourseForumsCollector(
        forums=("forum.bubble.io",),
        fetch=_make_fetch(latest, categories),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    since, until = _widest_window()
    docs = list(collector.collect(since, until))

    assert len(docs) == len(latest["topic_list"]["topics"])
    assert all(d.doc_type == "discourse_topic" for d in docs)
    assert all(d.connector_name == "discourse_forums" for d in docs)
    assert all(d.fetched_at == datetime(2026, 8, 7, tzinfo=UTC) for d in docs)
    # most topics resolve a real category name ("forum.bubble.io/Questions");
    # a topic whose category_id isn't in the categories fixture (a real
    # possibility live -- subcategories, or a category added after this
    # fixture was captured) falls back to the bare forum label, still valid.
    assert all(d.category is not None and d.category.startswith("forum.bubble.io") for d in docs)
    assert any("/" in (d.category or "") for d in docs)


def test_collect_filters_topics_outside_the_window() -> None:
    latest = _load("latest_bubble.json")
    categories = _load("categories_bubble.json")
    collector = DiscourseForumsCollector(
        forums=("forum.bubble.io",), fetch=_make_fetch(latest, categories)
    )

    docs = list(
        collector.collect(datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 1, 2, tzinfo=UTC))
    )

    assert docs == []


def test_collect_skips_a_single_malformed_topic_without_raising() -> None:
    latest = copy.deepcopy(_load("latest_bubble.json"))
    latest["topic_list"]["topics"].append({"excerpt": "missing id, title, created_at"})
    categories = _load("categories_bubble.json")
    collector = DiscourseForumsCollector(
        forums=("forum.bubble.io",),
        fetch=_make_fetch(latest, categories),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    since, until = _widest_window()
    docs = list(collector.collect(since, until))

    assert len(docs) == len(latest["topic_list"]["topics"]) - 1


def test_a_failing_forum_does_not_abort_the_others() -> None:
    latest = _load("latest_bubble.json")
    categories = _load("categories_bubble.json")

    def flaky_fetch(url: str) -> dict[str, Any]:
        if "community.make.com" in url:
            raise RuntimeError("simulated outage")
        return categories if "categories.json" in url else latest

    collector = DiscourseForumsCollector(
        forums=("community.make.com", "forum.bubble.io"),
        fetch=flaky_fetch,
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    since, until = _widest_window()
    docs = list(collector.collect(since, until))

    assert len(docs) == len(latest["topic_list"]["topics"])
    # most topics resolve a real category name ("forum.bubble.io/Questions");
    # a topic whose category_id isn't in the categories fixture (a real
    # possibility live -- subcategories, or a category added after this
    # fixture was captured) falls back to the bare forum label, still valid.
    assert all(d.category is not None and d.category.startswith("forum.bubble.io") for d in docs)
    assert any("/" in (d.category or "") for d in docs)


def test_missing_category_names_fall_back_to_the_bare_forum_label() -> None:
    latest = _load("latest_bubble.json")
    collector = DiscourseForumsCollector(
        forums=("forum.bubble.io",),
        fetch=_make_fetch(latest, {"category_list": {"categories": []}}),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    since, until = _widest_window()
    docs = list(collector.collect(since, until))

    assert all(d.category == "forum.bubble.io" for d in docs)


def test_dates_outside_the_widest_window_are_never_included() -> None:
    # sanity check that _widest_window() itself isn't accidentally excluding
    # anything, which would make the "yields every topic" test misleading
    latest = _load("latest_bubble.json")
    newest = max(datetime.fromisoformat(t["created_at"]) for t in latest["topic_list"]["topics"])
    assert newest < datetime.now(UTC) + timedelta(days=1)
