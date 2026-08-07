"""Pure parsing: a Discourse forum's `/latest.json` topic entry -> a
RawDocument. No I/O here -- mirrors tools/hn_parsing.py. Discourse's `.json`
suffix on every page is a first-class, documented, intentional feature of
the software (not a scraping workaround) -- verified against live calls to
forum.bubble.io and community.make.com.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from opportunity_engine.domain.models import RawDocument

DOC_TYPE = "discourse_topic"


def parse_topic(
    topic: dict[str, Any], forum_label: str, category_name: str | None, fetched_at: datetime
) -> RawDocument:
    topic_id = str(topic["id"])
    title = str(topic["title"])
    excerpt = str(topic.get("excerpt") or "")
    content_hash = hashlib.sha256(f"{title}\n{excerpt}".encode()).hexdigest()
    category = f"{forum_label}/{category_name}" if category_name else forum_label
    slug = topic.get("slug")
    return RawDocument(
        connector_name="discourse_forums",
        external_id=f"{forum_label}:{topic_id}",
        doc_type=DOC_TYPE,
        fetched_at=fetched_at,
        published_at=datetime.fromisoformat(topic["created_at"]),
        source_url=f"https://{forum_label}/t/{slug}/{topic_id}" if slug else None,
        title=title,
        body=excerpt or None,
        category=category,
        content_hash=content_hash,
        raw_json={
            "id": topic_id,
            "title": title,
            "excerpt": excerpt,
            "slug": slug,
            "category_id": topic.get("category_id"),
            "posts_count": topic.get("posts_count"),
            "views": topic.get("views"),
            "like_count": topic.get("like_count"),
        },
    )
