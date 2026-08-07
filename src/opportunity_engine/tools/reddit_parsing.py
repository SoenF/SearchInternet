"""Pure parsing: a PRAW Submission (or a test double with the same shape) ->
a RawDocument. No I/O here -- mirrors tools/hn_parsing.py.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from opportunity_engine.domain.models import RawDocument

DOC_TYPE = "reddit_post"


def parse_reddit_submission(submission: Any, fetched_at: datetime) -> RawDocument:
    external_id = str(submission.id)
    title = submission.title or ""
    body = submission.selftext or ""
    subreddit = str(submission.subreddit)
    content_hash = hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()
    permalink = getattr(submission, "permalink", None)
    permalink_url = f"https://reddit.com{permalink}" if permalink else None
    # `.url` is the external link for a link post, and equal to the permalink
    # for a self (text) post -- same external-link-preferred shape as HN's
    # `hit.get("url")`, which is what feeds is_personal_brand_only_source().
    source_url = getattr(submission, "url", None) or permalink_url
    return RawDocument(
        connector_name="reddit",
        external_id=external_id,
        doc_type=DOC_TYPE,
        fetched_at=fetched_at,
        published_at=datetime.fromtimestamp(submission.created_utc, tz=UTC),
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
            "score": getattr(submission, "score", None),
            "num_comments": getattr(submission, "num_comments", None),
            "created_utc": submission.created_utc,
            "permalink": permalink,
            "url": getattr(submission, "url", None),
        },
    )
