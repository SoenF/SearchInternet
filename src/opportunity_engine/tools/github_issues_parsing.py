"""Pure parsing: a GitHub Search Issues API item -> a RawDocument. No I/O
here -- mirrors tools/hn_parsing.py. Field names verified against a live call
to api.github.com/search/issues.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from opportunity_engine.domain.models import RawDocument

DOC_TYPE = "github_issue"


def _repo_full_name(repository_url: str) -> str:
    # "https://api.github.com/repos/owner/repo" -> "owner/repo"
    return "/".join(repository_url.rstrip("/").split("/")[-2:])


def parse_github_issue(item: dict[str, Any], fetched_at: datetime) -> RawDocument:
    repo = _repo_full_name(item["repository_url"])
    external_id = f"{repo}#{item['number']}"
    title = item.get("title") or ""
    body = item.get("body") or ""
    labels = [
        label["name"] if isinstance(label, dict) else label for label in (item.get("labels") or [])
    ]
    content_hash = hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()
    return RawDocument(
        connector_name="github_issues",
        external_id=external_id,
        doc_type=DOC_TYPE,
        fetched_at=fetched_at,
        published_at=datetime.fromisoformat(item["created_at"]),
        source_url=item.get("html_url"),
        title=title or None,
        body=body or None,
        category=labels[0] if labels else None,
        content_hash=content_hash,
        raw_json={
            "repo": repo,
            "number": item.get("number"),
            "title": title,
            "labels": labels,
            "comments": item.get("comments"),
            "created_at": item.get("created_at"),
            "html_url": item.get("html_url"),
        },
    )
