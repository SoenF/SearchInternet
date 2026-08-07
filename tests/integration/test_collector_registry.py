from __future__ import annotations

from typing import Any

import psycopg

from opportunity_engine.collectors.app_store import AppStoreCollector
from opportunity_engine.collectors.edgar import EdgarFormDCollector
from opportunity_engine.collectors.hackernews import HackerNewsCollector
from opportunity_engine.collectors.producthunt import ProductHuntCollector
from opportunity_engine.collectors.reddit import RedditCollector
from opportunity_engine.collectors.registry import build_enabled_collectors
from opportunity_engine.collectors.wikipedia_pageviews import WikipediaPageviewsCollector
from opportunity_engine.config import Settings


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "database_url": "unused",
        "edgar_user_agent": "OpportunityEngine/0.1 (contact: davide@vamur.com)",
        "wikipedia_user_agent": "OpportunityEngine/0.1 (contact: davide@vamur.com)",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_build_enabled_collectors_returns_all_four_by_default(
    db_conn: psycopg.Connection[Any],
) -> None:
    # Reddit is opt-in (needs REDDIT_CLIENT_ID) and isn't among these four --
    # see test_reddit_is_included_once_credentials_are_configured below.
    collectors = build_enabled_collectors(_settings(), db_conn)
    types = {type(c) for c in collectors}
    assert types == {
        HackerNewsCollector,
        EdgarFormDCollector,
        WikipediaPageviewsCollector,
        AppStoreCollector,
    }


def test_disabled_connectors_are_excluded(db_conn: psycopg.Connection[Any]) -> None:
    settings = _settings(disabled_connectors=frozenset({"sec_edgar_formd"}))
    collectors = build_enabled_collectors(settings, db_conn)
    types = {type(c) for c in collectors}
    assert EdgarFormDCollector not in types
    assert len(collectors) == 3


def test_reddit_is_skipped_without_credentials(db_conn: psycopg.Connection[Any]) -> None:
    collectors = build_enabled_collectors(_settings(), db_conn)
    assert RedditCollector not in {type(c) for c in collectors}


def test_reddit_is_included_once_credentials_are_configured(
    db_conn: psycopg.Connection[Any],
) -> None:
    settings = _settings(
        reddit_client_id="id", reddit_client_secret="secret", reddit_user_agent="ua"
    )
    collectors = build_enabled_collectors(settings, db_conn)
    assert RedditCollector in {type(c) for c in collectors}


def test_reddit_can_still_be_explicitly_disabled(db_conn: psycopg.Connection[Any]) -> None:
    settings = _settings(
        reddit_client_id="id",
        reddit_client_secret="secret",
        reddit_user_agent="ua",
        disabled_connectors=frozenset({"reddit"}),
    )
    collectors = build_enabled_collectors(settings, db_conn)
    assert RedditCollector not in {type(c) for c in collectors}


def test_producthunt_is_skipped_without_a_token(db_conn: psycopg.Connection[Any]) -> None:
    collectors = build_enabled_collectors(_settings(), db_conn)
    assert ProductHuntCollector not in {type(c) for c in collectors}


def test_producthunt_is_included_once_a_token_is_configured(
    db_conn: psycopg.Connection[Any],
) -> None:
    settings = _settings(producthunt_access_token="token")
    collectors = build_enabled_collectors(settings, db_conn)
    assert ProductHuntCollector in {type(c) for c in collectors}


def test_producthunt_can_still_be_explicitly_disabled(db_conn: psycopg.Connection[Any]) -> None:
    settings = _settings(
        producthunt_access_token="token", disabled_connectors=frozenset({"producthunt"})
    )
    collectors = build_enabled_collectors(settings, db_conn)
    assert ProductHuntCollector not in {type(c) for c in collectors}
