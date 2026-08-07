"""Phase 4: on-demand LLM deep-dive dossier for a single opportunity -- the
only place in this codebase allowed to spend money on an LLM call, and only
when a human asks for one opportunity at a time via the `deep-dive` CLI
command. Never invoked from the daily ingest/dedup/score/rank pipeline.

Model policy (enforced here, not just documented): default is Haiku;
escalating to Sonnet requires the caller to supply a written reason (the
CLI's `--escalate --reason "..."` flags) -- "no escalation by precaution"
per the project's model policy. `AnthropicProvider` independently rejects
anything outside its own allowlist, so Opus is unreachable even if this
check were bypassed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import psycopg

from opportunity_engine.clock import Clock, utc_now
from opportunity_engine.domain.enums import EventType
from opportunity_engine.events import append_event
from opportunity_engine.providers.llm_provider import (
    MODEL_HAIKU,
    LLMProvider,
    LLMRequest,
    compute_cost,
)

logger = logging.getLogger(__name__)

# ~3 EUR per the project's cost policy, expressed in USD (what Anthropic
# actually bills) at an approximate, documented conversion -- not a live FX
# rate. Adjust if real-money precision on this ceiling ever matters.
DEFAULT_BUDGET_USD = 3.30
MAX_OUTPUT_TOKENS = 2000

SYSTEM_PROMPT = (
    "You are an analyst drafting an acquisition-readiness dossier for a single "
    "micro-SaaS opportunity, for a solo operator who builds, launches, and "
    "resells small SaaS products within a 12-18 month horizon. Be concrete and "
    "skeptical: call out real risks (regulatory exposure, dependency on a "
    "specific person or brand, buildability concerns) as plainly as you note "
    "the upside. Do not pad with generic advice. Base every claim only on the "
    "evidence given -- if the evidence doesn't support a claim, say so "
    "explicitly rather than inferring or using outside knowledge."
)

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2-3 sentence summary of the opportunity"},
        "market_evidence": {
            "type": "string",
            "description": "What the evidence actually shows about demand and market proof",
        },
        "buildability_assessment": {"type": "string"},
        "vendability_assessment": {"type": "string"},
        "key_risks": {"type": "array", "items": {"type": "string"}},
        "recommendation": {"type": "string", "enum": ["pursue", "pursue_with_caution", "pass"]},
    },
    "required": [
        "summary",
        "market_evidence",
        "buildability_assessment",
        "vendability_assessment",
        "key_risks",
        "recommendation",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class DeepDiveResult:
    opportunity_id: int
    model: str
    content: dict[str, Any]
    cost_usd: float
    input_tokens: int
    output_tokens: int


class EscalationReasonRequired(ValueError):
    pass


class BudgetExceeded(RuntimeError):
    pass


def run_deep_dive(
    conn: psycopg.Connection[Any],
    llm_provider: LLMProvider,
    opportunity_id: int,
    *,
    model: str = MODEL_HAIKU,
    escalation_reason: str | None = None,
    budget_usd: float = DEFAULT_BUDGET_USD,
    clock: Clock = utc_now,
) -> DeepDiveResult:
    if model != MODEL_HAIKU and not escalation_reason:
        raise EscalationReasonRequired(
            f"using {model!r} instead of the default {MODEL_HAIKU!r} requires a written "
            "reason (--reason) demonstrating that Haiku specifically failed this "
            "opportunity -- no escalation 'by precaution', per this project's model policy"
        )

    evidence = _gather_evidence(conn, opportunity_id)
    prompt = _build_prompt(evidence)

    estimated_cost = _estimate_cost_ceiling(model, prompt)
    if estimated_cost > budget_usd:
        raise BudgetExceeded(
            f"estimated worst-case cost ${estimated_cost:.2f} for opportunity "
            f"{opportunity_id} exceeds the ${budget_usd:.2f} per-dossier budget before the "
            "call was even made -- this opportunity's evidence is unusually large; trim it "
            "or pass a higher budget_usd explicitly"
        )

    purpose = "phase4_dossier" if model == MODEL_HAIKU else "phase4_dossier_escalated"
    response = llm_provider.complete(
        LLMRequest(
            prompt=prompt,
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            purpose=purpose,
            system=SYSTEM_PROMPT,
            output_schema=OUTPUT_SCHEMA,
            metadata={"opportunity_id": opportunity_id},
        )
    )

    try:
        content = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"model {response.model!r} did not return valid JSON despite a forced schema: "
            f"{response.text[:200]!r}"
        ) from exc

    now = clock()
    conn.execute(
        """
        INSERT INTO opportunity_dossiers
            (opportunity_id, model, purpose, escalation_reason, content,
             input_tokens, output_tokens, cost_usd, latency_ms, generated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            opportunity_id,
            response.model,
            purpose,
            escalation_reason,
            json.dumps(content),
            response.input_tokens,
            response.output_tokens,
            response.cost_usd,
            response.latency_ms,
            now,
        ),
    )
    append_event(
        conn,
        EventType.LLM_CALL,
        opportunity_id=opportunity_id,
        payload={
            "model": response.model,
            "purpose": purpose,
            "cost_usd": response.cost_usd,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "escalation_reason": escalation_reason,
        },
    )
    conn.commit()

    return DeepDiveResult(
        opportunity_id=opportunity_id,
        model=response.model,
        content=content,
        cost_usd=response.cost_usd,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )


def _estimate_cost_ceiling(model: str, prompt: str) -> float:
    """Cheap pre-flight guard, not a precise estimate: ~4 chars/token, and
    the worst case where the model uses its entire output budget. This is
    the safety net that stops an unusually large opportunity's evidence from
    silently blowing through the per-dossier budget -- it cannot prevent
    every overspend (the real bill is only known after the call), but it
    catches the case that matters: a request that was already going to be
    too expensive before it was ever sent."""
    estimated_input_tokens = max(1, len(prompt) // 4)
    return compute_cost(model, estimated_input_tokens, MAX_OUTPUT_TOKENS)


def _gather_evidence(conn: psycopg.Connection[Any], opportunity_id: int) -> dict[str, Any]:
    opportunity_row = conn.execute(
        """
        SELECT title, description, category, primary_strategy, status,
               rejection_reason, rejection_detail, current_score, current_score_breakdown
        FROM opportunities WHERE id = %s
        """,
        (opportunity_id,),
    ).fetchone()
    if opportunity_row is None:
        raise ValueError(f"no opportunity with id {opportunity_id}")
    (
        title,
        description,
        category,
        primary_strategy,
        status,
        rejection_reason,
        rejection_detail,
        current_score,
        current_score_breakdown,
    ) = opportunity_row

    documents = conn.execute(
        """
        SELECT rd.doc_type, rd.title, rd.body, rd.source_url, rd.country_code, rd.category
        FROM opportunity_sources os
        JOIN raw_documents rd ON rd.id = os.raw_document_id
        WHERE os.opportunity_id = %s
        ORDER BY rd.fetched_at
        """,
        (opportunity_id,),
    ).fetchall()

    proof_events = conn.execute(
        """
        SELECT proof_type, observed_at, weight, confidence, extracted_value
        FROM proof_events WHERE opportunity_id = %s ORDER BY observed_at DESC
        """,
        (opportunity_id,),
    ).fetchall()

    latest_score = conn.execute(
        """
        SELECT momentum_score, momentum_confidence, market_proof_score,
               buildability_pass, buildability_reasons, vendability_pass,
               vendability_reasons, barrier_pass, barrier_evidence, composite_score
        FROM score_history WHERE opportunity_id = %s ORDER BY computed_at DESC LIMIT 1
        """,
        (opportunity_id,),
    ).fetchone()

    return {
        "title": title,
        "description": description,
        "category": category,
        "primary_strategy": primary_strategy,
        "status": status,
        "rejection_reason": rejection_reason,
        "rejection_detail": rejection_detail,
        "current_score": float(current_score) if current_score is not None else None,
        "current_score_breakdown": current_score_breakdown,
        "documents": [
            {
                "doc_type": doc_type,
                "title": doc_title,
                "body": body,
                "source_url": source_url,
                "country_code": country_code,
                "category": doc_category,
            }
            for doc_type, doc_title, body, source_url, country_code, doc_category in documents
        ],
        "proof_events": [
            {
                "proof_type": proof_type,
                "observed_at": observed_at.isoformat(),
                "weight": float(weight),
                "confidence": float(confidence),
                "extracted_value": extracted_value,
            }
            for proof_type, observed_at, weight, confidence, extracted_value in proof_events
        ],
        "latest_score": (
            {
                "momentum_score": float(latest_score[0]) if latest_score[0] is not None else None,
                "momentum_confidence": latest_score[1],
                "market_proof_score": float(latest_score[2]),
                "buildability_pass": latest_score[3],
                "buildability_reasons": latest_score[4],
                "vendability_pass": latest_score[5],
                "vendability_reasons": latest_score[6],
                "barrier_pass": latest_score[7],
                "barrier_evidence": latest_score[8],
                "composite_score": float(latest_score[9]) if latest_score[9] is not None else None,
            }
            if latest_score is not None
            else None
        ),
    }


def _build_prompt(evidence: dict[str, Any]) -> str:
    return (
        "Write an acquisition-readiness dossier for this opportunity, using only "
        "the evidence below.\n\n"
        f"{json.dumps(evidence, indent=2, default=str)}"
    )
