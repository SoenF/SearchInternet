"""Stack Exchange API 2.3 (`/questions`), scoped by default to Software
Recommendations (site=softwarerecs) -- a Q&A site whose entire premise is
"is there a tool that does X", making it a strong, low-noise pain-point
source. Unlike Reddit/Product Hunt, no auth is required at all: an API key
(STACKEXCHANGE_API_KEY) only raises the daily quota from 300 to 10,000
requests, it doesn't gate access -- so this connector is enabled by default,
like the four Phase 1 connectors, not opt-in like Phase 3's credentialed ones.
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
from opportunity_engine.tools.http import fetch_json
from opportunity_engine.tools.stackexchange_parsing import parse_stackexchange_question

logger = logging.getLogger(__name__)

_QUESTIONS_URL = "https://api.stackexchange.com/2.3/questions"
_PAGE_SIZE = 100

FetchFn = Callable[[str, dict[str, Any]], dict[str, Any]]


class StackExchangeCollector(Collector):
    manifest: ClassVar[ConnectorManifest] = ConnectorManifest(
        name="stackexchange",
        source_description=(
            "Stack Exchange questions (default: Software Recommendations) via the "
            "official public Questions API, date-filtered."
        ),
        source_url=_QUESTIONS_URL,
        quota_description=(
            "300 requests/day per IP without a key, 10,000/day with a free "
            "app key from stackapps.com/apps/oauth/register."
        ),
        tos_url="https://stackoverflow.com/legal/api-terms-of-use",
        tos_status="compliant",
        last_verified=date(2026, 8, 7),
    )

    def __init__(
        self,
        *,
        sites: frozenset[str] = frozenset({"softwarerecs"}),
        api_key: str = "",
        fetch: FetchFn | None = None,
        clock: Clock = utc_now,
        client: httpx.Client | None = None,
    ) -> None:
        self._sites = sites
        self._api_key = api_key
        if fetch is not None:
            self._fetch: FetchFn = fetch
        else:
            owned_client = client or httpx.Client(timeout=10.0)
            self._fetch = lambda url, params: fetch_json(owned_client, url, params=params)
        self._clock = clock

    def collect(self, since: datetime, until: datetime) -> Iterator[RawDocument]:
        for site in sorted(self._sites):
            yield from self._collect_site(site, since, until)

    def _collect_site(self, site: str, since: datetime, until: datetime) -> Iterator[RawDocument]:
        page = 1
        while True:
            params: dict[str, Any] = {
                "site": site,
                "order": "desc",
                "sort": "creation",
                "fromdate": int(since.timestamp()),
                "todate": int(until.timestamp()),
                "pagesize": _PAGE_SIZE,
                "page": page,
                "filter": "withbody",
            }
            if self._api_key:
                params["key"] = self._api_key
            data = self._fetch(_QUESTIONS_URL, params)
            items = data.get("items", [])
            fetched_at = self._clock()
            for item in items:
                try:
                    yield parse_stackexchange_question(item, site, fetched_at)
                except (KeyError, ValueError, TypeError):
                    logger.warning(
                        "skipping malformed Stack Exchange question",
                        extra={"site": site, "question_id": item.get("question_id")},
                    )
                    continue
            if not data.get("has_more"):
                return
            page += 1
