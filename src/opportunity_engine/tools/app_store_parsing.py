"""Pure parsing: an iTunes RSS chart entry -> a RawDocument. No I/O here."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Any

from opportunity_engine.domain.models import RawDocument


def _extract_app_url(entry: dict[str, Any]) -> str | None:
    links = entry.get("link")
    candidates = links if isinstance(links, list) else [links] if links else []
    for link in candidates:
        if not isinstance(link, dict):
            continue
        attributes = link.get("attributes", {})
        if attributes.get("rel") == "alternate":
            href = attributes.get("href")
            return str(href) if href is not None else None
    return None


def parse_rss_entry(
    entry: dict[str, Any],
    country: str,
    feed: str,
    rank: int,
    observed_date: date,
    fetched_at: datetime,
) -> RawDocument:
    track_id = str(entry["id"]["attributes"]["im:id"])
    name = str(entry["im:name"]["label"])
    genre = str(entry["category"]["attributes"]["label"])
    app_url = _extract_app_url(entry)

    external_id = f"{country}:{feed}:{track_id}:{observed_date.isoformat()}"
    content_hash = hashlib.sha256(f"{track_id}\n{rank}\n{observed_date}".encode()).hexdigest()

    return RawDocument(
        connector_name="itunes_app_store",
        external_id=external_id,
        doc_type="app_store_ranking",
        fetched_at=fetched_at,
        published_at=datetime.combine(observed_date, datetime.min.time(), tzinfo=UTC),
        source_url=app_url,
        title=name,
        country_code=country,
        category=genre,
        content_hash=content_hash,
        raw_json={"entry": entry, "rank": rank, "feed": feed, "track_id": track_id},
    )
