"""Pure parsing: a Product Hunt GraphQL v2 `Post` node -> a RawDocument. No
I/O here -- mirrors tools/hn_parsing.py. Field names verified against the
public schema at github.com/producthunt/producthunt-api/blob/master/schema.graphql
(id, name, tagline, description, url, votesCount, commentsCount, createdAt,
topics.edges[].node.name are all real `Post` fields there).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from opportunity_engine.domain.models import RawDocument

DOC_TYPE = "producthunt_post"


def parse_producthunt_post(node: dict[str, Any], fetched_at: datetime) -> RawDocument:
    external_id = str(node["id"])
    name = node.get("name") or ""
    tagline = node.get("tagline") or ""
    description = node.get("description") or ""
    body = "\n".join(part for part in (tagline, description) if part)
    content_hash = hashlib.sha256(f"{name}\n{body}".encode()).hexdigest()
    topics = [
        edge["node"]["name"]
        for edge in (node.get("topics", {}).get("edges") or [])
        if edge.get("node")
    ]
    return RawDocument(
        connector_name="producthunt",
        external_id=external_id,
        doc_type=DOC_TYPE,
        fetched_at=fetched_at,
        published_at=datetime.fromisoformat(node["createdAt"]),
        source_url=node.get("url"),
        title=name or None,
        body=body or None,
        category=topics[0] if topics else None,
        content_hash=content_hash,
        raw_json=node,
    )
