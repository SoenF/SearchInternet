"""Phase 4 end to end: run_deep_dive against a real DB with a fake LLMProvider
(no real Anthropic call, no spent money -- consistent with the zero-network-
calls-in-tests rule; only Postgres is real here).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from opportunity_engine.agents.deep_dive_agent import (
    BudgetExceeded,
    EscalationReasonRequired,
    run_deep_dive,
)
from opportunity_engine.clock import fixed_clock
from opportunity_engine.providers.llm_provider import (
    MODEL_HAIKU,
    MODEL_SONNET,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    compute_cost,
)

AS_OF = datetime(2026, 8, 7, tzinfo=UTC)

_DOSSIER_CONTENT = {
    "summary": "A pain-driven micro-SaaS idea with early HN traction.",
    "market_evidence": "One HN post mentioning $5k MRR.",
    "buildability_assessment": "Straightforward CRUD app, no heavy integrations.",
    "vendability_assessment": "Recurring revenue model, no daily intervention needed.",
    "key_risks": ["Small sample size of evidence."],
    "recommendation": "pursue_with_caution",
}


class _FakeLLMProvider(LLMProvider):
    def __init__(self, *, response_text: str | None = None) -> None:
        self.last_request: LLMRequest | None = None
        self._response_text = response_text or json.dumps(_DOSSIER_CONTENT)

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.last_request = request
        input_tokens, output_tokens = 500, 150
        return LLMResponse(
            text=self._response_text,
            model=request.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=compute_cost(request.model, input_tokens, output_tokens),
            latency_ms=42.0,
        )


def _insert_opportunity_with_evidence(conn: psycopg.Connection[Any]) -> int:
    row = conn.execute(
        """
        INSERT INTO opportunities (title, description, category, primary_strategy, status, current_score)
        VALUES ('CSV importer for accountants', 'niche tool', 'productivity', 'pain_driven', 'candidate', 42.5)
        RETURNING id
        """
    ).fetchone()
    assert row is not None
    opportunity_id = int(row[0])

    conn.execute(
        """
        INSERT INTO connectors (name, source_description, source_url, quota_description,
                                 tos_url, tos_status, last_verified)
        VALUES ('hackernews_algolia', 't', 'http://t', 't', 'http://t', 'compliant', '2026-08-07')
        ON CONFLICT (name) DO NOTHING
        """
    )
    doc_row = conn.execute(
        """
        INSERT INTO raw_documents
            (connector_name, external_id, doc_type, fetched_at, published_at, title, body, content_hash, raw_json)
        VALUES ('hackernews_algolia', 'hn1', 'hn_ask', %s, %s, 'Show HN: CSV importer', 'We hit $5k MRR', 'h1', %s)
        RETURNING id
        """,
        (AS_OF, AS_OF, json.dumps({})),
    ).fetchone()
    assert doc_row is not None
    conn.execute(
        "INSERT INTO opportunity_sources (opportunity_id, raw_document_id) VALUES (%s, %s)",
        (opportunity_id, int(doc_row[0])),
    )
    conn.execute(
        """
        INSERT INTO proof_events (opportunity_id, proof_type, observed_at, weight, confidence, extracted_value)
        VALUES (%s, 'disclosed_revenue', %s, 40.0, 0.8, %s)
        """,
        (opportunity_id, AS_OF.date(), json.dumps({"amount_usd": 5000})),
    )
    conn.commit()
    return opportunity_id


def test_run_deep_dive_writes_dossier_and_event(db_conn: psycopg.Connection[Any]) -> None:
    opportunity_id = _insert_opportunity_with_evidence(db_conn)
    provider = _FakeLLMProvider()

    result = run_deep_dive(db_conn, provider, opportunity_id, clock=fixed_clock(AS_OF))

    assert result.model == MODEL_HAIKU
    assert result.content == _DOSSIER_CONTENT
    assert result.cost_usd > 0

    assert provider.last_request is not None
    assert provider.last_request.output_schema is not None
    assert "$5k MRR" in provider.last_request.prompt

    dossier_row = db_conn.execute(
        "SELECT model, purpose, content, cost_usd FROM opportunity_dossiers WHERE opportunity_id = %s",
        (opportunity_id,),
    ).fetchone()
    assert dossier_row is not None
    model, purpose, content, cost_usd = dossier_row
    assert model == MODEL_HAIKU
    assert purpose == "phase4_dossier"
    assert content == _DOSSIER_CONTENT
    assert float(cost_usd) > 0

    event_row = db_conn.execute(
        "SELECT event_type, payload FROM events WHERE opportunity_id = %s", (opportunity_id,)
    ).fetchone()
    assert event_row is not None
    event_type, payload = event_row
    assert event_type == "llm_call"
    assert payload["model"] == MODEL_HAIKU
    assert payload["escalation_reason"] is None


def test_run_deep_dive_escalation_requires_reason(db_conn: psycopg.Connection[Any]) -> None:
    opportunity_id = _insert_opportunity_with_evidence(db_conn)
    provider = _FakeLLMProvider()

    with pytest.raises(EscalationReasonRequired):
        run_deep_dive(
            db_conn, provider, opportunity_id, model=MODEL_SONNET, clock=fixed_clock(AS_OF)
        )
    assert provider.last_request is None


def test_run_deep_dive_escalation_with_reason_uses_sonnet(db_conn: psycopg.Connection[Any]) -> None:
    opportunity_id = _insert_opportunity_with_evidence(db_conn)
    provider = _FakeLLMProvider()

    result = run_deep_dive(
        db_conn,
        provider,
        opportunity_id,
        model=MODEL_SONNET,
        escalation_reason="Haiku's first dossier missed the regulatory angle entirely.",
        clock=fixed_clock(AS_OF),
    )

    assert result.model == MODEL_SONNET
    payload = db_conn.execute(
        "SELECT payload FROM events WHERE opportunity_id = %s", (opportunity_id,)
    ).fetchone()[0]
    assert (
        payload["escalation_reason"]
        == "Haiku's first dossier missed the regulatory angle entirely."
    )


def test_run_deep_dive_raises_on_unknown_opportunity(db_conn: psycopg.Connection[Any]) -> None:
    provider = _FakeLLMProvider()
    with pytest.raises(ValueError, match="no opportunity with id"):
        run_deep_dive(db_conn, provider, 999_999, clock=fixed_clock(AS_OF))


def test_run_deep_dive_enforces_budget_ceiling(db_conn: psycopg.Connection[Any]) -> None:
    opportunity_id = _insert_opportunity_with_evidence(db_conn)
    provider = _FakeLLMProvider()

    with pytest.raises(BudgetExceeded):
        run_deep_dive(
            db_conn, provider, opportunity_id, budget_usd=0.0000001, clock=fixed_clock(AS_OF)
        )
    assert provider.last_request is None
