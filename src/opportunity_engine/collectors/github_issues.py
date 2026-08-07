"""GitHub Search Issues API, scoped by default to open, `enhancement`-labeled
issues -- "please add this one feature" is a strong, low-noise pain-point
signal, especially for developer-tool-shaped opportunities. Works fully
unauthenticated (10 requests/min); a personal access token
(GITHUB_TOKEN, self-service, instant, no approval process) raises that to 30
requests/min for the search endpoint specifically. Enabled by default, like
StackExchangeCollector -- no credential is required, only recommended.
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
from opportunity_engine.tools.github_issues_parsing import parse_github_issue
from opportunity_engine.tools.http import fetch_json

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.github.com/search/issues"
_PER_PAGE = 100
_MAX_RESULTS = 1000  # GitHub Search API's hard cap on results per query, regardless of paging

DEFAULT_SEARCH_QUERY = "is:issue is:open label:enhancement"

FetchFn = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]


class GitHubIssuesCollector(Collector):
    manifest: ClassVar[ConnectorManifest] = ConnectorManifest(
        name="github_issues",
        source_description=(
            "GitHub issues matching a configurable search query (default: open, "
            "'enhancement'-labeled) via the official Search API, date-filtered."
        ),
        source_url=_SEARCH_URL,
        quota_description=(
            "Search endpoint: 10 requests/min unauthenticated, 30/min with a "
            "personal access token. Results capped at 1000 per query."
        ),
        tos_url="https://docs.github.com/en/site-policy/github-terms/github-terms-of-service",
        tos_status="compliant",
        last_verified=date(2026, 8, 7),
    )

    def __init__(
        self,
        *,
        search_query: str = DEFAULT_SEARCH_QUERY,
        token: str = "",
        fetch: FetchFn | None = None,
        clock: Clock = utc_now,
        client: httpx.Client | None = None,
    ) -> None:
        self._search_query = search_query
        self._token = token
        if fetch is not None:
            self._fetch: FetchFn = fetch
        else:
            owned_client = client or httpx.Client(timeout=10.0)
            self._fetch = lambda url, params, headers: fetch_json(
                owned_client, url, params=params, headers=headers
            )
        self._clock = clock

    def collect(self, since: datetime, until: datetime) -> Iterator[RawDocument]:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        query = (
            f"{self._search_query} created:{since.strftime('%Y-%m-%dT%H:%M:%S')}"
            f"..{until.strftime('%Y-%m-%dT%H:%M:%S')}"
        )
        page = 1
        seen = 0
        while True:
            params: dict[str, Any] = {
                "q": query,
                "sort": "created",
                "order": "desc",
                "per_page": _PER_PAGE,
                "page": page,
            }
            data = self._fetch(_SEARCH_URL, params, headers)
            items = data.get("items", [])
            fetched_at = self._clock()
            for item in items:
                try:
                    yield parse_github_issue(item, fetched_at)
                except (KeyError, ValueError, TypeError):
                    logger.warning(
                        "skipping malformed GitHub issue", extra={"item_id": item.get("id")}
                    )
                    continue
            seen += len(items)
            if not items or seen >= min(data.get("total_count", 0), _MAX_RESULTS):
                return
            page += 1
