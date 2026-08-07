"""Fixture-driven: catches our own parser regressing against a recorded
Submission shape. PRAW's Submission is a rich lazy-loaded object, not plain
JSON -- a hand-built double exposing the handful of attributes this
connector actually reads is more honest here than a fake JSON fixture
pretending to be a captured live response we never made (see CLAUDE.md's
fixture-honesty principle). Mirrors tests/connectors/test_hackernews_collector.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from opportunity_engine.clock import fixed_clock
from opportunity_engine.collectors.reddit import RedditCollector


class _FakeSubmission:
    def __init__(
        self,
        *,
        id: str,
        title: str,
        selftext: str = "",
        subreddit: str = "SaaS",
        created_utc: float,
        url: str | None = None,
        permalink: str = "/r/SaaS/comments/abc123/some_post/",
        score: int = 10,
        num_comments: int = 2,
    ) -> None:
        self.id = id
        self.title = title
        self.selftext = selftext
        self.subreddit = subreddit
        self.created_utc = created_utc
        self.url = url if url is not None else f"https://reddit.com{permalink}"
        self.permalink = permalink
        self.score = score
        self.num_comments = num_comments


_JAN_1_2025_UTC = datetime(2025, 1, 1, 12, tzinfo=UTC).timestamp()
_JAN_5_2025_UTC = datetime(2025, 1, 5, 12, tzinfo=UTC).timestamp()

_SAAS_SUBMISSIONS = [
    _FakeSubmission(
        id="s1",
        title="Struggling to find a tool for invoice reconciliation",
        selftext="We hit $5k MRR trying to solve this ourselves.",
        subreddit="SaaS",
        created_utc=_JAN_1_2025_UTC,
    ),
    _FakeSubmission(
        id="s2",
        title="Show: my new CSV importer",
        selftext="",
        subreddit="SaaS",
        created_utc=_JAN_5_2025_UTC,  # outside the collect() window in the main test
        url="https://myimporter.example.com",
    ),
]
_ENTREPRENEUR_SUBMISSIONS = [
    _FakeSubmission(
        id="e1",
        title="Anyone else tired of manually tagging support tickets?",
        subreddit="Entrepreneur",
        created_utc=_JAN_1_2025_UTC,
    ),
]


def _make_fetch(
    by_subreddit: dict[str, list[_FakeSubmission]],
) -> Any:
    def fake_fetch(subreddit_name: str, limit: int) -> Iterator[_FakeSubmission]:
        return iter(by_subreddit.get(subreddit_name, []))

    return fake_fetch


def test_collect_yields_documents_within_the_window() -> None:
    collector = RedditCollector(
        subreddits=frozenset({"SaaS", "Entrepreneur"}),
        fetch=_make_fetch({"SaaS": _SAAS_SUBMISSIONS, "Entrepreneur": _ENTREPRENEUR_SUBMISSIONS}),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )

    assert {d.external_id for d in docs} == {"s1", "e1"}  # s2 falls outside the window
    assert all(d.doc_type == "reddit_post" for d in docs)
    assert all(d.connector_name == "reddit" for d in docs)
    assert all(d.fetched_at == datetime(2026, 8, 7, tzinfo=UTC) for d in docs)

    s1 = next(d for d in docs if d.external_id == "s1")
    assert s1.category == "SaaS"
    assert "$5k MRR" in (s1.body or "")


def test_collect_prefers_external_url_over_permalink() -> None:
    collector = RedditCollector(
        subreddits=frozenset({"SaaS"}),
        fetch=_make_fetch({"SaaS": _SAAS_SUBMISSIONS}),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2025, 1, 4, tzinfo=UTC), datetime(2025, 1, 6, tzinfo=UTC))
    )

    assert len(docs) == 1
    assert docs[0].source_url == "https://myimporter.example.com"


def test_collect_skips_a_single_malformed_submission_without_raising() -> None:
    class _Broken:
        pass  # missing every attribute the parser reads

    submissions: list[Any] = [_Broken(), *_SAAS_SUBMISSIONS]
    collector = RedditCollector(
        subreddits=frozenset({"SaaS"}),
        fetch=_make_fetch({"SaaS": submissions}),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))
    )

    assert {d.external_id for d in docs} == {"s1"}
