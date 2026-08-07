"""SEC EDGAR full-text search, filtered to Form D (private capital raises).

The cleanest arbitrage/market-proof source in this project: an official,
reported raise, not an intent signal. Deliberately does NOT fetch each
filing's primary_doc.xml for the offering amount -- that would double the
number of SEC requests for a benefit (buildability's capital-intensive-raise
check) that mostly matters for a single already-shortlisted opportunity, not
bulk daily ingestion. `edgar_offering_amount` stays unset from this connector
in Phase 1-2; see CLAUDE.md limitations. SIC-code enrichment is also often
unavailable here: most Form D filers are newly formed single-purpose
entities with no SIC classification on file (confirmed against live data --
established filers like bank holding companies do have one).
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
from opportunity_engine.tools.edgar_parsing import parse_formd_hit
from opportunity_engine.tools.http import fetch_json

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

FetchFn = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]


class EdgarFormDCollector(Collector):
    manifest: ClassVar[ConnectorManifest] = ConnectorManifest(
        name="sec_edgar_formd",
        source_description=(
            "SEC EDGAR full-text search filtered to Form D (private placement "
            "notices of exempt securities offerings)."
        ),
        source_url=_SEARCH_URL,
        quota_description=(
            "SEC's fair-access guideline: roughly 10 requests/sec, with a "
            "descriptive User-Agent identifying the requester."
        ),
        tos_url="https://www.sec.gov/privacy",
        tos_status="compliant",
        last_verified=date(2026, 8, 7),
        requires_auth=False,
    )

    def __init__(
        self,
        user_agent: str,
        *,
        fetch: FetchFn | None = None,
        clock: Clock = utc_now,
        client: httpx.Client | None = None,
    ) -> None:
        if fetch is not None:
            self._fetch: FetchFn = fetch
        else:
            owned_client = client or httpx.Client(timeout=15.0)
            self._fetch = lambda url, params, headers: fetch_json(
                owned_client, url, params=params, headers=headers
            )
        self._user_agent = user_agent
        self._clock = clock

    def collect(self, since: datetime, until: datetime) -> Iterator[RawDocument]:
        headers = {"User-Agent": self._user_agent}
        start_from = 0
        while True:
            params: dict[str, Any] = {
                "forms": "D",
                "startdt": since.date().isoformat(),
                "enddt": until.date().isoformat(),
                "from": start_from,
            }
            data = self._fetch(_SEARCH_URL, params, headers)
            hits = data.get("hits", {}).get("hits", [])
            fetched_at = self._clock()
            for hit in hits:
                try:
                    yield parse_formd_hit(hit, fetched_at)
                except (KeyError, ValueError, TypeError, IndexError):
                    logger.warning(
                        "skipping malformed EDGAR Form D hit", extra={"hit_id": hit.get("_id")}
                    )
                    continue
            total = data.get("hits", {}).get("total", {}).get("value", 0)
            start_from += len(hits)
            if not hits or start_from >= total:
                return
