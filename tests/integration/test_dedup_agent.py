"""Against a real (local Docker) Postgres, using the already-cached local
embedding model (see README's cache-warming step) -- exercises novel, merge,
and Wikipedia-topic-linking paths end to end.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import psycopg
import pytest

from opportunity_engine.agents.dedup_agent import run_dedup
from opportunity_engine.clock import fixed_clock
from opportunity_engine.providers.embedding_provider import LocalE5EmbeddingProvider


@pytest.fixture(scope="module")
def embedding_provider() -> LocalE5EmbeddingProvider:
    try:
        return LocalE5EmbeddingProvider()
    except OSError as exc:
        pytest.skip(f"multilingual-e5-base not cached locally yet: {exc}")


def _insert_raw_document(
    conn: psycopg.Connection[Any],
    *,
    connector_name: str,
    external_id: str,
    doc_type: str,
    title: str,
    body: str | None = None,
) -> int:
    conn.execute(
        """
        INSERT INTO connectors (name, source_description, source_url, quota_description,
                                 tos_url, tos_status, last_verified)
        VALUES (%s, 'test', 'http://test', 'test', 'http://test', 'compliant', '2026-08-07')
        ON CONFLICT (name) DO NOTHING
        """,
        (connector_name,),
    )
    row = conn.execute(
        """
        INSERT INTO raw_documents
            (connector_name, external_id, doc_type, fetched_at, title, body, content_hash, raw_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            connector_name,
            external_id,
            doc_type,
            datetime(2026, 8, 7, tzinfo=UTC),
            title,
            body,
            external_id,
            json.dumps({}),
        ),
    ).fetchone()
    assert row is not None
    return int(row[0])


def test_two_near_duplicate_hn_posts_merge_into_one_opportunity(
    db_conn: psycopg.Connection[Any], embedding_provider: LocalE5EmbeddingProvider
) -> None:
    _insert_raw_document(
        db_conn,
        connector_name="hackernews_algolia",
        external_id="1",
        doc_type="hn_ask",
        title="Ask HN: is there a tool to auto-renew my SaaS SSL certificates?",
    )
    _insert_raw_document(
        db_conn,
        connector_name="hackernews_algolia",
        external_id="2",
        doc_type="hn_ask",
        title="Ask HN: tool that automatically renews SSL certs for my SaaS?",
    )
    db_conn.commit()

    stats = run_dedup(
        db_conn, embedding_provider, clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC))
    )

    assert stats.novel == 1
    assert stats.merged == 1

    opportunity_count = db_conn.execute("SELECT count(*) FROM opportunities").fetchone()
    assert opportunity_count == (1,)

    source_count = db_conn.execute("SELECT count(*) FROM opportunity_sources").fetchone()
    assert source_count == (2,)

    strategy = db_conn.execute("SELECT primary_strategy FROM opportunities").fetchone()
    assert strategy == ("pain_driven",)


def test_two_unrelated_hn_posts_create_two_opportunities(
    db_conn: psycopg.Connection[Any], embedding_provider: LocalE5EmbeddingProvider
) -> None:
    """Whether the second post lands in `novel` or `gray_zone` is a threshold
    calibration detail (empirically, multilingual-e5-base's cosine similarity
    for short unrelated English sentences sits ~0.79-0.83, not near 0 -- the
    default 0.75 novel_threshold is a starting point, not a tuned value). The
    behavior that actually matters and must hold regardless of calibration:
    two unrelated posts are never merged into a single opportunity."""
    _insert_raw_document(
        db_conn,
        connector_name="hackernews_algolia",
        external_id="1",
        doc_type="hn_ask",
        title="Ask HN: is there a tool to auto-renew my SaaS SSL certificates?",
    )
    _insert_raw_document(
        db_conn,
        connector_name="hackernews_algolia",
        external_id="2",
        doc_type="hn_ask",
        title="Ask HN: how do I convince my cat to stop knocking plants off the balcony?",
    )
    db_conn.commit()

    stats = run_dedup(
        db_conn, embedding_provider, clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC))
    )

    assert stats.merged == 0
    assert stats.novel + stats.gray_zone == 2

    opportunity_count = db_conn.execute("SELECT count(*) FROM opportunities").fetchone()
    assert opportunity_count == (2,)


def test_edgar_document_gets_arbitrage_strategy(
    db_conn: psycopg.Connection[Any], embedding_provider: LocalE5EmbeddingProvider
) -> None:
    _insert_raw_document(
        db_conn,
        connector_name="sec_edgar_formd",
        external_id="0001-26-000001",
        doc_type="edgar_formd",
        title="Some Startup Inc.",
    )
    db_conn.commit()

    run_dedup(db_conn, embedding_provider, clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)))

    strategy = db_conn.execute("SELECT primary_strategy FROM opportunities").fetchone()
    assert strategy == ("arbitrage",)


def test_wikipedia_document_links_to_its_tracked_opportunity(
    db_conn: psycopg.Connection[Any], embedding_provider: LocalE5EmbeddingProvider
) -> None:
    _insert_raw_document(
        db_conn,
        connector_name="hackernews_algolia",
        external_id="1",
        doc_type="hn_ask",
        title="Ask HN: is there a tool to auto-renew my SaaS SSL certificates?",
    )
    run_dedup(db_conn, embedding_provider, clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)))
    opportunity_row = db_conn.execute("SELECT id FROM opportunities").fetchone()
    assert opportunity_row is not None
    opportunity_id = opportunity_row[0]

    db_conn.execute(
        """
        INSERT INTO tracked_topics (project, article, topic_label, added_by_opportunity_id)
        VALUES ('en.wikipedia', 'SSL_certificate', 'SSL certificates', %s)
        """,
        (opportunity_id,),
    )
    db_conn.execute(
        """
        INSERT INTO connectors (name, source_description, source_url, quota_description,
                                 tos_url, tos_status, last_verified)
        VALUES ('wikipedia_pageviews', 'test', 'http://test', 'test', 'http://test',
                'compliant', '2026-08-07')
        """
    )
    wiki_raw_json = {
        "items": [
            {
                "project": "en.wikipedia",
                "article": "SSL_certificate",
                "timestamp": "2025010100",
                "views": 10,
            }
        ]
    }
    db_conn.execute(
        """
        INSERT INTO raw_documents
            (connector_name, external_id, doc_type, fetched_at, title, content_hash, raw_json)
        VALUES ('wikipedia_pageviews', 'en.wikipedia:SSL_certificate:2025-01-01:2025-01-02',
                'wikipedia_pageviews_series', %s, 'en.wikipedia: SSL_certificate', 'hash1', %s)
        """,
        (datetime(2026, 8, 7, tzinfo=UTC), json.dumps(wiki_raw_json)),
    )
    db_conn.commit()

    stats = run_dedup(
        db_conn, embedding_provider, clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC))
    )

    assert stats.wikipedia_linked == 1
    link = db_conn.execute(
        """
        SELECT 1 FROM opportunity_sources os
        JOIN raw_documents rd ON rd.id = os.raw_document_id
        WHERE os.opportunity_id = %s AND rd.doc_type = 'wikipedia_pageviews_series'
        """,
        (opportunity_id,),
    ).fetchone()
    assert link is not None
