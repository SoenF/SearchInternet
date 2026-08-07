"""Pure parsing: one line of a Pushshift-format Reddit submissions dump
(RS_*.zst -- the community-standard historical Reddit archive format) ->
a RawDocument. Field names (id, subreddit, title, selftext, created_utc,
permalink, url, score, num_comments) match Pushshift's schema.

Deliberately separate from tools/reddit_parsing.py (a live PRAW Submission
object) even though both produce the same doc_type="reddit_post" shape: a
Pushshift JSON record and a PRAW Submission expose overlapping information
through different shapes (a plain string `subreddit` field here vs a lazy
Subreddit object there), so sharing one parser would mean branching on input
type internally instead of having two small, honest functions.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from opportunity_engine.domain.models import RawDocument

DOC_TYPE = "reddit_post"
_REMOVED_OR_DELETED = {"[removed]", "[deleted]"}


def parse_pushshift_submission(record: dict[str, Any], fetched_at: datetime) -> RawDocument:
    external_id = str(record["id"])
    title = record.get("title") or ""
    body = record.get("selftext") or ""
    if body in _REMOVED_OR_DELETED:
        body = ""
    subreddit = str(record.get("subreddit") or "") or None
    content_hash = hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()
    permalink = record.get("permalink")
    permalink_url = f"https://reddit.com{permalink}" if permalink else None
    source_url = record.get("url") or permalink_url
    return RawDocument(
        connector_name="reddit",
        external_id=external_id,
        doc_type=DOC_TYPE,
        fetched_at=fetched_at,
        published_at=datetime.fromtimestamp(float(record["created_utc"]), tz=UTC),
        source_url=source_url,
        title=title or None,
        body=body or None,
        category=subreddit,
        content_hash=content_hash,
        raw_json={
            "id": external_id,
            "title": title,
            "selftext": body,
            "subreddit": subreddit,
            "score": record.get("score"),
            "num_comments": record.get("num_comments"),
            "created_utc": record.get("created_utc"),
            "permalink": permalink,
            "url": record.get("url"),
        },
    )
