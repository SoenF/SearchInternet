"""HN Algolia Search API: Ask HN pain points + Show HN launches.

Simplest of the four Phase-1 connectors (no auth, no per-country fan-out) --
built and validated first to prove the fixture -> parse -> store -> event path
end to end.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from datetime import date, datetime
from typing import Any, ClassVar

import httpx

from opportunity_engine.clock import Clock, utc_now
from opportunity_engine.collectors.base import Collector, ConnectorManifest
from opportunity_engine.domain.models import RawDocument
from opportunity_engine.tools.hn_parsing import parse_hn_hit
from opportunity_engine.tools.http import fetch_json

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
_TAGS = ("ask_hn", "show_hn")

FetchFn = Callable[[str, dict[str, Any]], dict[str, Any]]


class HackerNewsCollector(Collector):
    manifest: ClassVar[ConnectorManifest] = ConnectorManifest(
        name="hackernews_algolia",
        source_description=(
            "Hacker News full-text search via the Algolia HN Search API -- "
            "Ask HN pain points and Show HN launches, date-filtered."
        ),
        source_url=_SEARCH_URL,
        quota_description="No documented hard rate limit for reasonable use of the public API.",
        tos_url="https://www.algolia.com/policies/terms/",
        tos_status="compliant",
        last_verified=date(2026, 8, 7),
    )

    def __init__(
        self,
        *,
        fetch: FetchFn | None = None,
        clock: Clock = utc_now,
        hits_per_page: int = 100,
        client: httpx.Client | None = None,
    ) -> None:
        if fetch is not None:
            self._fetch: FetchFn = fetch
        else:
            owned_client = client or httpx.Client(timeout=10.0)
            self._fetch = lambda url, params: fetch_json(owned_client, url, params=params)
        self._clock = clock
        self._hits_per_page = hits_per_page

    def collect(self, since: datetime, until: datetime) -> Iterator[RawDocument]:
        for tag in _TAGS:
            yield from self._collect_tag(tag, since, until)

    def _collect_tag(self, tag: str, since: datetime, until: datetime) -> Iterator[RawDocument]:
        page = 0
        while True:
            params: dict[str, Any] = {
                "tags": tag,
                "numericFilters": (
                    f"created_at_i>={int(since.timestamp())},created_at_i<{int(until.timestamp())}"
                ),
                "hitsPerPage": self._hits_per_page,
                "page": page,
            }
            data = self._fetch(_SEARCH_URL, params)
            hits = data.get("hits", [])
            fetched_at = self._clock()
            for hit in hits:
                try:
                    yield parse_hn_hit(hit, tag, fetched_at)
                except (KeyError, ValueError, TypeError):
                    logger.warning(
                        "skipping malformed HN hit",
                        extra={"tag": tag, "hit_id": hit.get("objectID")},
                    )
                    continue
            if not hits or page + 1 >= data.get("nbPages", 1):
                return
            page += 1
