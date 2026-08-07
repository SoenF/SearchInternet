from __future__ import annotations

from datetime import UTC, datetime

import pytest

from opportunity_engine.tools.reddit_archive_parsing import parse_pushshift_submission

_FETCHED_AT = datetime(2026, 8, 7, tzinfo=UTC)


def test_parses_a_well_formed_record() -> None:
    record = {
        "id": "abc123",
        "subreddit": "SaaS",
        "title": "Struggling to reconcile invoices across five tools",
        "selftext": "We hit $5k MRR trying to solve this by hand.",
        "created_utc": 1735732800.0,  # 2025-01-01T12:00:00Z
        "permalink": "/r/SaaS/comments/abc123/x/",
        "url": "https://reddit.com/r/SaaS/comments/abc123/x/",
        "score": 42,
        "num_comments": 7,
    }

    doc = parse_pushshift_submission(record, _FETCHED_AT)

    assert doc.connector_name == "reddit"
    assert doc.external_id == "abc123"
    assert doc.doc_type == "reddit_post"
    assert doc.category == "SaaS"
    assert doc.title == "Struggling to reconcile invoices across five tools"
    assert doc.body == "We hit $5k MRR trying to solve this by hand."
    assert doc.published_at == datetime(2025, 1, 1, 12, tzinfo=UTC)
    assert doc.fetched_at == _FETCHED_AT
    assert doc.source_url == "https://reddit.com/r/SaaS/comments/abc123/x/"


def test_falls_back_to_permalink_when_url_is_missing() -> None:
    record = {
        "id": "abc124",
        "subreddit": "SaaS",
        "title": "Self post with no external url",
        "selftext": "",
        "created_utc": 1735732800.0,
        "permalink": "/r/SaaS/comments/abc124/x/",
    }

    doc = parse_pushshift_submission(record, _FETCHED_AT)

    assert doc.source_url == "https://reddit.com/r/SaaS/comments/abc124/x/"


def test_removed_and_deleted_selftext_is_treated_as_empty() -> None:
    record = {
        "id": "abc125",
        "subreddit": "SaaS",
        "title": "A post whose body got nuked",
        "selftext": "[removed]",
        "created_utc": 1735732800.0,
    }

    doc = parse_pushshift_submission(record, _FETCHED_AT)

    assert doc.body is None


def test_missing_required_field_raises() -> None:
    with pytest.raises(KeyError):
        parse_pushshift_submission(
            {"subreddit": "SaaS", "title": "no id or created_utc"}, _FETCHED_AT
        )
