"""Wikimedia Pageviews API: topical-interest proxy with historical depth.

Explicitly replaces Google Trends -- there is no official Trends API, and
`pytrends` (unofficial, scrapes a private endpoint) is exactly the kind of
scraping-against-ToS dependency this project avoids as a matter of policy.

Unlike the other three Phase-1 connectors, this one is candidate-driven, not
world-scanning: it needs a list of articles to watch, sourced from the
`tracked_topics` table (seeded manually via the `track-topic` CLI command, or
automatically when DedupAgent creates a new opportunity). The topic list is
passed in at construction time rather than queried by the collector itself,
so `collect()` stays a pure fetch with no DB dependency, consistent with the
other collectors.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterator
from datetime import date, datetime
from typing import Any, ClassVar

import httpx

from opportunity_engine.clock import Clock, utc_now
from opportunity_engine.collectors.base import Collector, ConnectorManifest
from opportunity_engine.domain.models import RawDocument, TrackedTopic
from opportunity_engine.tools.http import fetch_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"

FetchFn = Callable[[str, dict[str, str]], dict[str, Any]]


class WikipediaPageviewsCollector(Collector):
    manifest: ClassVar[ConnectorManifest] = ConnectorManifest(
        name="wikipedia_pageviews",
        source_description=(
            "Wikimedia Pageviews API, per-article daily series for a watched set of "
            "topics -- a topical-interest proxy standing in for Google Trends."
        ),
        source_url=_BASE_URL,
        quota_description=(
            "No documented hard rate limit; Wikimedia's User-Agent policy asks for a "
            "descriptive identifier on every request."
        ),
        tos_url="https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy",
        tos_status="compliant",
        last_verified=date(2026, 8, 7),
    )

    def __init__(
        self,
        topics: list[TrackedTopic],
        user_agent: str,
        *,
        fetch: FetchFn | None = None,
        clock: Clock = utc_now,
        client: httpx.Client | None = None,
    ) -> None:
        self._topics = topics
        self._user_agent = user_agent
        if fetch is not None:
            self._fetch: FetchFn = fetch
        else:
            owned_client = client or httpx.Client(timeout=15.0)
            self._fetch = lambda url, headers: fetch_json(owned_client, url, headers=headers)
        self._clock = clock

    def collect(self, since: datetime, until: datetime) -> Iterator[RawDocument]:
        headers = {"User-Agent": self._user_agent}
        for topic in self._topics:
            url = (
                f"{_BASE_URL}/{topic.project}/all-access/user/{topic.article}/daily/"
                f"{since.strftime('%Y%m%d')}/{until.strftime('%Y%m%d')}"
            )
            try:
                data = self._fetch(url, headers)
            except Exception:  # noqa: BLE001 -- one topic with no data yet (404) must not abort the run
                logger.warning(
                    "failed fetching pageviews for tracked topic",
                    extra={"project": topic.project, "article": topic.article},
                )
                continue

            fetched_at = self._clock()
            external_id = (
                f"{topic.project}:{topic.article}:"
                f"{since.date().isoformat()}:{until.date().isoformat()}"
            )
            content_hash = hashlib.sha256(
                json.dumps(data, sort_keys=True, default=str).encode()
            ).hexdigest()
            yield RawDocument(
                connector_name="wikipedia_pageviews",
                external_id=external_id,
                doc_type="wikipedia_pageviews_series",
                fetched_at=fetched_at,
                title=f"{topic.project}: {topic.article}",
                category=topic.project,
                content_hash=content_hash,
                raw_json=data,
            )
