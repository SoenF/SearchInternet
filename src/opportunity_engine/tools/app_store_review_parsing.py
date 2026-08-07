"""Pure parsing for the App Store reviews connector: an iTunes RSS genre-chart
entry -> just the (app_id, app_name) pair used to discover which apps to
pull reviews for, and an iTunes RSS customer-review entry -> a RawDocument.
No I/O here -- mirrors tools/app_store_parsing.py.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from opportunity_engine.domain.models import RawDocument

DOC_TYPE = "app_store_review"


def parse_genre_chart_app(entry: dict[str, Any]) -> tuple[str, str]:
    """Returns (app_id, app_name) -- discovery only, not a RawDocument. The
    chart entry itself isn't stored; it's just the candidate list feeding
    the per-app review fetch."""
    app_id = str(entry["id"]["attributes"]["im:id"])
    name = str(entry["im:name"]["label"])
    return app_id, name


def parse_review_entry(
    entry: dict[str, Any],
    app_id: str,
    app_name: str,
    genre_label: str,
    country: str,
    fetched_at: datetime,
) -> RawDocument:
    review_id = str(entry["id"]["label"])
    title = str(entry.get("title", {}).get("label") or "")
    body = str(entry.get("content", {}).get("label") or "")
    rating = entry.get("im:rating", {}).get("label")
    content_hash = hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()
    review_url = entry.get("link", {}).get("attributes", {}).get("href")
    return RawDocument(
        connector_name="itunes_app_store_reviews",
        external_id=f"{app_id}:{review_id}",
        doc_type=DOC_TYPE,
        fetched_at=fetched_at,
        published_at=datetime.fromisoformat(entry["updated"]["label"]),
        source_url=review_url,
        title=title or None,
        body=body or None,
        country_code=country,
        category=genre_label,
        content_hash=content_hash,
        raw_json={
            "app_id": app_id,
            "app_name": app_name,
            "review_id": review_id,
            "rating": rating,
            "version": entry.get("im:version", {}).get("label"),
        },
    )
