"""Pure parsing: an Algolia HN Search API hit -> a RawDocument. No I/O here."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from html import unescape
from typing import Any

from opportunity_engine.domain.models import RawDocument

DOC_TYPE_BY_TAG = {"ask_hn": "hn_ask", "show_hn": "hn_show"}
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return unescape(_HTML_TAG_RE.sub(" ", text)).strip()


def parse_hn_hit(hit: dict[str, Any], tag: str, fetched_at: datetime) -> RawDocument:
    doc_type = DOC_TYPE_BY_TAG[tag]
    object_id = str(hit["objectID"])
    title = hit.get("title") or ""
    body = _strip_html(hit.get("story_text") or "")
    content_hash = hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()
    return RawDocument(
        connector_name="hackernews_algolia",
        external_id=object_id,
        doc_type=doc_type,
        fetched_at=fetched_at,
        published_at=datetime.fromtimestamp(hit["created_at_i"], tz=UTC),
        source_url=hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}",
        title=title or None,
        body=body or None,
        content_hash=content_hash,
        raw_json=hit,
    )
