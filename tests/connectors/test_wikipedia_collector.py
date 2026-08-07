from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opportunity_engine.clock import fixed_clock
from opportunity_engine.collectors.wikipedia_pageviews import WikipediaPageviewsCollector
from opportunity_engine.domain.models import TrackedTopic

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "wikipedia"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())  # type: ignore[no-any-return]


def test_collect_yields_one_document_per_tracked_topic() -> None:
    response = _load("pageviews_response.json")
    topics = [
        TrackedTopic(project="en.wikipedia", article="ChatGPT"),
        TrackedTopic(project="ja.wikipedia", article="ChatGPT"),
    ]

    def fake_fetch(url: str, headers: dict[str, str]) -> dict[str, Any]:
        assert headers["User-Agent"]
        return response

    collector = WikipediaPageviewsCollector(
        topics=topics,
        user_agent="OpportunityEngine/0.1 (contact: davide@vamur.com)",
        fetch=fake_fetch,
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 10, tzinfo=UTC))
    )

    assert len(docs) == 2
    assert {d.category for d in docs} == {"en.wikipedia", "ja.wikipedia"}
    assert all(d.doc_type == "wikipedia_pageviews_series" for d in docs)
    assert all(d.raw_json == response for d in docs)


def test_collect_skips_a_topic_whose_fetch_fails() -> None:
    response = _load("pageviews_response.json")
    topics = [
        TrackedTopic(project="en.wikipedia", article="ChatGPT"),
        TrackedTopic(project="en.wikipedia", article="Brand_New_Article_With_No_Data_Yet"),
    ]

    def flaky_fetch(url: str, headers: dict[str, str]) -> dict[str, Any]:
        if "Brand_New_Article" in url:
            raise RuntimeError("404 Not Found")
        return response

    collector = WikipediaPageviewsCollector(
        topics=topics,
        user_agent="OpportunityEngine/0.1 (contact: davide@vamur.com)",
        fetch=flaky_fetch,
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 10, tzinfo=UTC))
    )

    assert len(docs) == 1
