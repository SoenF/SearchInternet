"""Which collectors exist, and which ones are enabled right now.

Enable/disable is a config-level decision (`Settings.disabled_connectors`,
read once here) -- independent of the developer-maintained `ConnectorManifest`
on each collector class. This satisfies "every connector can be disabled
without touching the rest of the engine" without creating a second live
source of truth for a behavior-affecting flag.

`WikipediaPageviewsCollector` is candidate-driven (see its module docstring),
so building it needs a DB read of `tracked_topics` -- the only reason this
factory function takes a connection at all; the other three ignore it.

A factory may return `None` (Reddit's and Product Hunt's) to mean "not
configured" -- distinct from `disabled_connectors`, which is an explicit
opt-out. Missing API credentials is an implicit, silent opt-out: no
`REDDIT_CLIENT_ID`/`PRODUCTHUNT_ACCESS_TOKEN` means the connector is skipped
rather than crashing `build_enabled_collectors` at startup.

Stack Exchange and GitHub Issues need no credential at all (a key/token only
raises their rate limit, it doesn't gate access), so they're always
registered like the four Phase 1 connectors -- only `disabled_connectors`
can turn them off.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import psycopg

from opportunity_engine.collectors.app_store import AppStoreCollector
from opportunity_engine.collectors.app_store_reviews import AppStoreReviewsCollector
from opportunity_engine.collectors.base import Collector
from opportunity_engine.collectors.discourse_forums import DiscourseForumsCollector
from opportunity_engine.collectors.edgar import EdgarFormDCollector
from opportunity_engine.collectors.github_issues import GitHubIssuesCollector
from opportunity_engine.collectors.hackernews import HackerNewsCollector
from opportunity_engine.collectors.producthunt import ProductHuntCollector
from opportunity_engine.collectors.reddit import RedditCollector
from opportunity_engine.collectors.stackexchange import StackExchangeCollector
from opportunity_engine.collectors.wikipedia_pageviews import WikipediaPageviewsCollector
from opportunity_engine.config import Settings
from opportunity_engine.tools.storage import fetch_tracked_topics

CollectorFactory = Callable[[Settings, psycopg.Connection[Any]], Collector | None]


def _build_reddit(settings: Settings, conn: psycopg.Connection[Any]) -> Collector | None:
    if not settings.reddit_client_id:
        return None
    return RedditCollector(
        subreddits=settings.reddit_subreddits,
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        user_agent=settings.reddit_user_agent,
    )


def _build_producthunt(settings: Settings, conn: psycopg.Connection[Any]) -> Collector | None:
    if not settings.producthunt_access_token:
        return None
    return ProductHuntCollector(access_token=settings.producthunt_access_token)


CONNECTOR_FACTORIES: dict[str, CollectorFactory] = {
    HackerNewsCollector.manifest.name: lambda settings, conn: HackerNewsCollector(),
    EdgarFormDCollector.manifest.name: (
        lambda settings, conn: EdgarFormDCollector(user_agent=settings.edgar_user_agent)
    ),
    WikipediaPageviewsCollector.manifest.name: (
        lambda settings, conn: WikipediaPageviewsCollector(
            topics=fetch_tracked_topics(conn), user_agent=settings.wikipedia_user_agent
        )
    ),
    AppStoreCollector.manifest.name: lambda settings, conn: AppStoreCollector(),
    AppStoreReviewsCollector.manifest.name: lambda settings, conn: AppStoreReviewsCollector(),
    DiscourseForumsCollector.manifest.name: (
        lambda settings, conn: DiscourseForumsCollector(forums=settings.discourse_forums)
    ),
    RedditCollector.manifest.name: _build_reddit,
    ProductHuntCollector.manifest.name: _build_producthunt,
    StackExchangeCollector.manifest.name: (
        lambda settings, conn: StackExchangeCollector(
            sites=settings.stackexchange_sites, api_key=settings.stackexchange_api_key
        )
    ),
    GitHubIssuesCollector.manifest.name: (
        lambda settings, conn: GitHubIssuesCollector(
            search_query=settings.github_search_query, token=settings.github_token
        )
    ),
}


def build_enabled_collectors(settings: Settings, conn: psycopg.Connection[Any]) -> list[Collector]:
    collectors = []
    for name, factory in CONNECTOR_FACTORIES.items():
        if name in settings.disabled_connectors:
            continue
        collector = factory(settings, conn)
        if collector is not None:
            collectors.append(collector)
    return collectors
