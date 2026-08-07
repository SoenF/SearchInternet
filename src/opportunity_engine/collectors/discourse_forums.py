"""Public topics from Discourse-based no-code/small-business tool
communities (default: Bubble, Make) via Discourse's own free, official,
no-auth `.json` API -- a first-class documented feature of the software,
not a scraping workaround.

This reaches small-business/no-code builders who already pay for a SaaS
tool and want more from it, a step away from this pipeline's other sources
(which all skew toward a developer audience) without going all the way to
"no signal at all." Two requests per forum per run: `/categories.json` once
(to resolve category names) and `/latest.json` for the current front page of
topics -- deliberately not paginated further or fetching each topic's full
body, to keep this connector's footprint tiny; `excerpt` (Discourse's own
truncated summary of the first post) is the body text stored.

Not every Discourse community responds reliably to `.json` requests without
a browser (Cloudflare, redirects, or the domain simply not running Discourse
anymore) -- `DISCOURSE_FORUMS` lets you swap in ones that work for you;
Zapier's and Webflow's community domains did not respond cleanly to a plain
`.json` GET when this was verified (2026-08-07), so they're not defaults.
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
from opportunity_engine.tools.discourse_parsing import parse_topic
from opportunity_engine.tools.http import fetch_json

logger = logging.getLogger(__name__)

_DEFAULT_FORUMS = ("forum.bubble.io", "community.make.com")

FetchFn = Callable[[str], dict[str, Any]]


class DiscourseForumsCollector(Collector):
    manifest: ClassVar[ConnectorManifest] = ConnectorManifest(
        name="discourse_forums",
        source_description=(
            "Public topics from Discourse-based no-code/small-business tool "
            "communities (default: Bubble, Make), via Discourse's own documented "
            "no-auth JSON API."
        ),
        source_url="https://forum.bubble.io/",
        quota_description="No published hard limit for the public read-only JSON API.",
        tos_url="https://www.discourse.org/about",
        tos_status="compliant",
        last_verified=date(2026, 8, 7),
    )

    def __init__(
        self,
        *,
        fetch: FetchFn | None = None,
        clock: Clock = utc_now,
        client: httpx.Client | None = None,
        forums: tuple[str, ...] = _DEFAULT_FORUMS,
    ) -> None:
        if fetch is not None:
            self._fetch: FetchFn = fetch
        else:
            owned_client = client or httpx.Client(timeout=10.0, follow_redirects=True)
            self._fetch = lambda url: fetch_json(owned_client, url)
        self._clock = clock
        self._forums = forums

    def collect(self, since: datetime, until: datetime) -> Iterator[RawDocument]:
        for forum in self._forums:
            yield from self._collect_forum(forum, since, until)

    def _collect_forum(self, forum: str, since: datetime, until: datetime) -> Iterator[RawDocument]:
        categories = self._fetch_categories(forum)
        try:
            data = self._fetch(f"https://{forum}/latest.json?no_definitions=true")
        except Exception:  # noqa: BLE001 -- one forum failing must not abort the others
            logger.warning("failed fetching Discourse forum topics", extra={"forum": forum})
            return
        fetched_at = self._clock()
        topics = data.get("topic_list", {}).get("topics", [])
        for topic in topics:
            try:
                category_name = categories.get(topic.get("category_id"))
                doc = parse_topic(topic, forum, category_name, fetched_at)
            except (KeyError, ValueError, TypeError):
                logger.warning(
                    "skipping malformed Discourse topic",
                    extra={"forum": forum, "topic_id": topic.get("id")},
                )
                continue
            if doc.published_at is not None and since <= doc.published_at < until:
                yield doc

    def _fetch_categories(self, forum: str) -> dict[int, str]:
        try:
            data = self._fetch(f"https://{forum}/categories.json")
        except Exception:  # noqa: BLE001 -- category names are a nice-to-have, not required
            logger.warning("failed fetching Discourse categories", extra={"forum": forum})
            return {}
        return {
            c["id"]: c["name"]
            for c in data.get("category_list", {}).get("categories", [])
            if "id" in c and "name" in c
        }
