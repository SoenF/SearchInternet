"""iTunes RSS customer reviews, discovered via genre-scoped top charts.

Distinct from `collectors/app_store.py`'s overall top-free/top-paid charts
(dominated by mainstream consumer apps -- games, social, shopping): this
connector scopes chart discovery to Finance/Business/Lifestyle genres
specifically because that's where legal/accounting/real-estate/rental-
adjacent apps actually chart (verified live: Zillow Real Estate & Rentals
appears in the Lifestyle genre chart, ADP Mobile Solutions and Acrobat
Reader in Business). Reviews on an already-charting, already-monetizing app
are a stronger, more diverse pain-point signal than this pipeline's other
sources, which all skew toward a developer audience -- "I wish this app
also supported X" from a real paying user, across any consumer category,
not just software-for-developers.

Two-step discovery, not a flat list: fetch each genre's top-N chart to get
app IDs, then fetch each app's customer-reviews feed. Bounded (apps_per_genre)
to stay within iTunes RSS's informal ~20 requests/minute ceiling -- see
collectors/app_store.py's manifest for the same caveat.

A day-1 `ingest` run can legitimately return zero documents: review-feed
publish timing is uneven across apps, and which ~45 apps chart in these
three genres shifts day to day, so an exact rolling 24h window sometimes
lands between reviews for the whole discovered set (confirmed live
2026-08-07 -- a 1-day window returned 0, the same run's 3-day window
returned 880). Not a bug; widen `--days` if this connector looks empty.
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
from opportunity_engine.tools.app_store_review_parsing import (
    parse_genre_chart_app,
    parse_review_entry,
)
from opportunity_engine.tools.http import fetch_json

logger = logging.getLogger(__name__)

_CHART_URL_TEMPLATE = (
    "https://itunes.apple.com/{country}/rss/topfreeapplications/limit={limit}/genre={genre}/json"
)
_REVIEWS_URL_TEMPLATE = (
    "https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortby=mostrecent/json"
)

# App Store genre IDs -- Finance, Business, Lifestyle. Chosen because they're
# where legal/accounting/real-estate/rental-adjacent apps actually chart, not
# because they're the biggest genres. See module docstring.
_DEFAULT_GENRES = (("6015", "Finance"), ("6000", "Business"), ("6012", "Lifestyle"))
_DEFAULT_COUNTRY = "us"

FetchFn = Callable[[str], dict[str, Any]]


class AppStoreReviewsCollector(Collector):
    manifest: ClassVar[ConnectorManifest] = ConnectorManifest(
        name="itunes_app_store_reviews",
        source_description=(
            "iTunes RSS customer reviews for apps charting in Finance/Business/"
            "Lifestyle genres -- a non-developer-audience pain-point source from "
            "users of already-monetizing consumer apps."
        ),
        source_url="https://itunes.apple.com/",
        quota_description=(
            "No published hard limit; ~20 requests/minute is a commonly cited "
            "informal ceiling for the iTunes Search/RSS surface (same as "
            "collectors/app_store.py)."
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
        genres: tuple[tuple[str, str], ...] = _DEFAULT_GENRES,
        country: str = _DEFAULT_COUNTRY,
        apps_per_genre: int = 15,
    ) -> None:
        if fetch is not None:
            self._fetch: FetchFn = fetch
        else:
            owned_client = client or httpx.Client(timeout=15.0)
            self._fetch = lambda url: fetch_json(owned_client, url)
        self._clock = clock
        self._genres = genres
        self._country = country
        self._apps_per_genre = apps_per_genre

    def collect(self, since: datetime, until: datetime) -> Iterator[RawDocument]:
        for genre_id, genre_label in self._genres:
            for app_id, app_name in self._discover_apps(genre_id):
                yield from self._collect_reviews(app_id, app_name, genre_label, since, until)

    def _discover_apps(self, genre_id: str) -> list[tuple[str, str]]:
        url = _CHART_URL_TEMPLATE.format(
            country=self._country, limit=self._apps_per_genre, genre=genre_id
        )
        try:
            data = self._fetch(url)
        except Exception:  # noqa: BLE001 -- one genre failing must not abort the others
            logger.warning("failed fetching App Store genre chart", extra={"genre": genre_id})
            return []
        apps = []
        for entry in data.get("feed", {}).get("entry", []):
            try:
                apps.append(parse_genre_chart_app(entry))
            except (KeyError, ValueError, TypeError):
                continue
        return apps

    def _collect_reviews(
        self, app_id: str, app_name: str, genre_label: str, since: datetime, until: datetime
    ) -> Iterator[RawDocument]:
        url = _REVIEWS_URL_TEMPLATE.format(country=self._country, app_id=app_id)
        try:
            data = self._fetch(url)
        except Exception:  # noqa: BLE001 -- one app's reviews failing must not abort the others
            logger.warning("failed fetching App Store reviews", extra={"app_id": app_id})
            return
        fetched_at = self._clock()
        for entry in data.get("feed", {}).get("entry", []):
            try:
                doc = parse_review_entry(
                    entry, app_id, app_name, genre_label, self._country, fetched_at
                )
            except (KeyError, ValueError, TypeError):
                logger.warning("skipping malformed App Store review", extra={"app_id": app_id})
                continue
            if doc.published_at is not None and since <= doc.published_at < until:
                yield doc
