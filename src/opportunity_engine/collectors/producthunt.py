"""Product Hunt GraphQL v2 API. Phase 3 connector.

Every request requires a bearer token (developer token or OAuth client-
credentials token from https://www.producthunt.com/v2/oauth/applications) --
there is no anonymous tier, unlike HN/EDGAR/Wikipedia/iTunes. ToS status is
`review_needed` for the same reason as Reddit's: commercial-use terms this
project has not had legal review against -- see CLAUDE.md. Set
DISABLED_CONNECTORS=producthunt to keep it off; the registry also skips it
automatically when no PRODUCTHUNT_ACCESS_TOKEN is configured.

The `posts` query's `postedAfter`/`postedBefore` arguments (verified against
the public schema at github.com/producthunt/producthunt-api) give a real
server-side date-range filter, unlike Reddit's client-side-only window.
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
from opportunity_engine.tools.http import post_json
from opportunity_engine.tools.producthunt_parsing import parse_producthunt_post

logger = logging.getLogger(__name__)

_GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"

_POSTS_QUERY = """
query ($after: String, $postedAfter: DateTime, $postedBefore: DateTime) {
  posts(first: 50, after: $after, order: NEWEST, postedAfter: $postedAfter, postedBefore: $postedBefore) {
    edges {
      node {
        id
        name
        tagline
        description
        url
        votesCount
        commentsCount
        createdAt
        topics {
          edges {
            node {
              name
            }
          }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

FetchFn = Callable[[dict[str, Any], dict[str, str]], dict[str, Any]]


class ProductHuntCollector(Collector):
    manifest: ClassVar[ConnectorManifest] = ConnectorManifest(
        name="producthunt",
        source_description=(
            "Product Hunt launches (name, tagline, description) via the official "
            "GraphQL v2 API, date-filtered server-side."
        ),
        source_url=_GRAPHQL_URL,
        quota_description=(
            "Complexity-limited (1000/query) with a rolling 15-minute rate-limit "
            "window; exact request quota undocumented, see CLAUDE.md."
        ),
        tos_url="https://www.producthunt.com/api-terms",
        tos_status="review_needed",
        last_verified=date(2026, 8, 7),
        requires_auth=True,
    )

    def __init__(
        self,
        access_token: str = "",
        *,
        fetch: FetchFn | None = None,
        clock: Clock = utc_now,
        client: httpx.Client | None = None,
    ) -> None:
        if fetch is not None:
            self._fetch: FetchFn = fetch
        else:
            owned_client = client or httpx.Client(timeout=15.0)
            headers = {"Authorization": f"Bearer {access_token}"}
            self._fetch = lambda variables, extra_headers: post_json(
                owned_client,
                _GRAPHQL_URL,
                json_body={"query": _POSTS_QUERY, "variables": variables},
                headers={**headers, **extra_headers},
            )
        self._clock = clock

    def collect(self, since: datetime, until: datetime) -> Iterator[RawDocument]:
        cursor: str | None = None
        while True:
            variables: dict[str, Any] = {
                "after": cursor,
                "postedAfter": since.isoformat(),
                "postedBefore": until.isoformat(),
            }
            data = self._fetch(variables, {})
            posts = data.get("data", {}).get("posts", {})
            edges = posts.get("edges", [])
            fetched_at = self._clock()
            for edge in edges:
                node = edge.get("node", {})
                try:
                    yield parse_producthunt_post(node, fetched_at)
                except (KeyError, ValueError, TypeError):
                    logger.warning(
                        "skipping malformed Product Hunt post", extra={"post_id": node.get("id")}
                    )
                    continue
            page_info = posts.get("pageInfo", {})
            if not edges or not page_info.get("hasNextPage"):
                return
            cursor = page_info.get("endCursor")
