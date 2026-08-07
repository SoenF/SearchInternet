"""iTunes RSS App Store charts: the core of geographic arbitrage detection.

One row per app/country/feed/day (snapshot semantics, keyed on the window's
end date) -- exactly the time series `opportunity_daily_signal.app_rank_best`
is later rolled up from. The iTunes `lookup` endpoint (cross-country listing
presence, used to build arbitrage barrier evidence for a *specific* candidate)
is deliberately not called here -- doing that for every charted app during
bulk ingestion would be hundreds of extra requests for signal that's only
needed once a candidate is already shortlisted. See tools/arbitrage_signals.py.
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
from opportunity_engine.tools.app_store_parsing import parse_rss_entry
from opportunity_engine.tools.http import fetch_json

logger = logging.getLogger(__name__)

_RSS_URL_TEMPLATE = "https://itunes.apple.com/{country}/rss/{feed}/limit={limit}/json"
_DEFAULT_COUNTRIES = ("us", "jp", "kr", "br")
_DEFAULT_FEEDS = ("topfreeapplications", "toppaidapplications")

FetchFn = Callable[[str], dict[str, Any]]


class AppStoreCollector(Collector):
    manifest: ClassVar[ConnectorManifest] = ConnectorManifest(
        name="itunes_app_store",
        source_description=(
            "iTunes RSS App Store charts, per country (US/JP/KR/BR) and feed (top-free, top-paid)."
        ),
        source_url="https://itunes.apple.com/",
        quota_description=(
            "No published hard limit; ~20 requests/minute is a commonly cited "
            "informal ceiling for the iTunes Search/RSS surface."
        ),
        tos_url="https://www.apple.com/legal/internet-services/itunes/us/terms.html",
        tos_status="compliant",
        last_verified=date(2026, 8, 7),
    )

    def __init__(
        self,
        *,
        fetch: FetchFn | None = None,
        clock: Clock = utc_now,
        client: httpx.Client | None = None,
        limit: int = 100,
        countries: tuple[str, ...] = _DEFAULT_COUNTRIES,
        feeds: tuple[str, ...] = _DEFAULT_FEEDS,
    ) -> None:
        if fetch is not None:
            self._fetch: FetchFn = fetch
        else:
            owned_client = client or httpx.Client(timeout=15.0)
            self._fetch = lambda url: fetch_json(owned_client, url)
        self._clock = clock
        self._limit = limit
        self._countries = countries
        self._feeds = feeds

    def collect(self, since: datetime, until: datetime) -> Iterator[RawDocument]:
        observed_date = until.date()  # snapshot semantics: "as of" the window's end
        for country in self._countries:
            for feed in self._feeds:
                yield from self._collect_chart(country, feed, observed_date)

    def _collect_chart(self, country: str, feed: str, observed_date: date) -> Iterator[RawDocument]:
        url = _RSS_URL_TEMPLATE.format(country=country, feed=feed, limit=self._limit)
        try:
            data = self._fetch(url)
        except Exception:  # noqa: BLE001 -- one chart failing must not abort the others (Collector contract)
            logger.warning(
                "failed fetching App Store chart", extra={"country": country, "feed": feed}
            )
            return
        fetched_at = self._clock()
        entries = data.get("feed", {}).get("entry", [])
        for rank, entry in enumerate(entries, start=1):
            try:
                yield parse_rss_entry(entry, country, feed, rank, observed_date, fetched_at)
            except (KeyError, ValueError, TypeError):
                logger.warning(
                    "skipping malformed App Store RSS entry",
                    extra={"country": country, "feed": feed, "rank": rank},
                )
                continue
