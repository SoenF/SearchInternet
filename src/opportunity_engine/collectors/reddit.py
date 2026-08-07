"""Reddit via PRAW (OAuth script app, read-only). Phase 3 connector.

ToS status is deliberately `review_needed`, not `compliant`: Reddit's 2023
Data API Terms impose restrictions on commercial use and prohibit certain
kinds of aggregation/resale that this project has not had legal review
against -- see CLAUDE.md. Set DISABLED_CONNECTORS=reddit to keep it off
until that review happens; the registry also skips it automatically when no
REDDIT_CLIENT_ID is configured, so it is off by default in a fresh checkout.

Unlike HN Algolia, Reddit's read-only API has no arbitrary since/until range
query -- `subreddit.new()` only walks back through the most recent posts in
that subreddit. `collect()` fetches the most recent `limit_per_subreddit`
posts per subreddit and filters to the requested window client-side, which
is why the daily `ingest`/`run-daily` cadence (not a wide backfill) is the
intended use -- see agents/deep_dive_agent.py's sibling, the `import-archive`
CLI command, for bulk historical backfill from a Pushshift-format dump.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from datetime import date, datetime
from typing import Any, ClassVar

import praw

from opportunity_engine.clock import Clock, utc_now
from opportunity_engine.collectors.base import Collector, ConnectorManifest
from opportunity_engine.domain.models import RawDocument
from opportunity_engine.tools.reddit_parsing import parse_reddit_submission

logger = logging.getLogger(__name__)

SubredditFetchFn = Callable[[str, int], Iterator[Any]]


def _default_fetch(client: praw.Reddit, subreddit_name: str, limit: int) -> Iterator[Any]:
    return iter(client.subreddit(subreddit_name).new(limit=limit))


class RedditCollector(Collector):
    manifest: ClassVar[ConnectorManifest] = ConnectorManifest(
        name="reddit",
        source_description=(
            "Reddit submissions (title + selftext) from a configured list of "
            "pain-language-heavy subreddits, via the official read-only PRAW API."
        ),
        source_url="https://www.reddit.com/dev/api/",
        quota_description="OAuth script app: ~100 queries/minute per Reddit API rules.",
        tos_url="https://www.redditinc.com/policies/data-api-terms",
        tos_status="review_needed",
        last_verified=date(2026, 8, 7),
        requires_auth=True,
    )

    def __init__(
        self,
        *,
        subreddits: frozenset[str],
        client_id: str = "",
        client_secret: str = "",
        user_agent: str = "",
        client: praw.Reddit | None = None,
        fetch: SubredditFetchFn | None = None,
        limit_per_subreddit: int = 100,
        clock: Clock = utc_now,
    ) -> None:
        self._subreddits = subreddits
        self._limit = limit_per_subreddit
        self._clock = clock
        if fetch is not None:
            self._fetch = fetch
        else:
            owned_client = client or praw.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                user_agent=user_agent,
                read_only=True,
                # PRAW pings PyPI on construction to nag about new releases
                # unless told not to -- unwanted in a pipeline (and, as a
                # side effect, the thing that made this class construction
                # a real network call, tripping pytest-socket in tests that
                # only wanted to check *whether* a client gets built).
                check_for_updates=False,
            )
            self._fetch = lambda name, limit: _default_fetch(owned_client, name, limit)

    def collect(self, since: datetime, until: datetime) -> Iterator[RawDocument]:
        fetched_at = self._clock()
        for subreddit_name in sorted(self._subreddits):
            for submission in self._fetch(subreddit_name, self._limit):
                try:
                    doc = parse_reddit_submission(submission, fetched_at)
                except (AttributeError, ValueError, TypeError):
                    logger.warning(
                        "skipping malformed Reddit submission",
                        extra={"subreddit": subreddit_name},
                    )
                    continue
                if doc.published_at is not None and since <= doc.published_at < until:
                    yield doc
