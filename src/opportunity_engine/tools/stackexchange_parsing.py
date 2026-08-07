"""Pure parsing: a Stack Exchange API 2.3 `/questions` item -> a RawDocument.
No I/O here -- mirrors tools/hn_parsing.py. Field names verified against a
live call to api.stackexchange.com/2.3/questions.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from html import unescape
from typing import Any

from opportunity_engine.domain.models import RawDocument

DOC_TYPE = "stackexchange_question"
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return unescape(_HTML_TAG_RE.sub(" ", text)).strip()


def parse_stackexchange_question(
    item: dict[str, Any], site: str, fetched_at: datetime
) -> RawDocument:
    question_id = str(item["question_id"])
    title = unescape(item.get("title") or "")
    body = _strip_html(item.get("body") or "")
    tags = item.get("tags") or []
    content_hash = hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()
    return RawDocument(
        connector_name="stackexchange",
        external_id=f"{site}:{question_id}",
        doc_type=DOC_TYPE,
        fetched_at=fetched_at,
        published_at=datetime.fromtimestamp(item["creation_date"], tz=UTC),
        source_url=item.get("link"),
        title=title or None,
        body=body or None,
        category=tags[0] if tags else None,
        content_hash=content_hash,
        raw_json={
            "question_id": question_id,
            "site": site,
            "title": title,
            "tags": tags,
            "score": item.get("score"),
            "view_count": item.get("view_count"),
            "answer_count": item.get("answer_count"),
            "is_answered": item.get("is_answered"),
            "creation_date": item.get("creation_date"),
            "link": item.get("link"),
        },
    )
