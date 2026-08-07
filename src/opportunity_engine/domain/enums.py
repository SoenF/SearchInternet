"""Closed vocabularies used by application code.

Note the asymmetry with the database: `opportunities.status` and
`primary_strategy` are native Postgres enums (small, closed, lifecycle-defined)
and mirrored here as StrEnum. `rejection_reason`, `proof_type`, and
`event_type` are free `text` columns in the database (so the rule/event set
can grow without an `ALTER TYPE` migration) -- but the values *this* codebase
emits today are still centralized as plain string constants below, so nothing
hardcodes a typo-prone literal in multiple places.
"""

from __future__ import annotations

from enum import StrEnum


class LifecycleStatus(StrEnum):
    CANDIDATE = "candidate"
    QUALIFIED = "qualified"
    IN_BUILD = "in_build"
    LAUNCHED = "launched"
    SOLD = "sold"
    REJECTED = "rejected"


class DetectionStrategyName(StrEnum):
    ARBITRAGE = "arbitrage"
    PAIN_DRIVEN = "pain_driven"


class MomentumConfidence(StrEnum):
    OK = "ok"
    INSUFFICIENT_HISTORY = "insufficient_history"


class DedupDecision(StrEnum):
    MERGE = "merge"
    NOVEL = "novel"
    GRAY_ZONE = "gray_zone"


class EventType(StrEnum):
    DOCUMENT_INGESTED = "document_ingested"
    OPPORTUNITY_CREATED = "opportunity_created"
    OPPORTUNITY_CREATED_GRAY_ZONE_REVIEW = "opportunity_created_gray_zone_review"
    OPPORTUNITY_MERGED = "opportunity_merged"
    OPPORTUNITY_REJECTED = "opportunity_rejected"
    OPPORTUNITY_SCORED = "opportunity_scored"
    OPPORTUNITY_PROPOSED = "opportunity_proposed"
    LLM_CALL = "llm_call"  # phase 4: emitted only by agents/deep_dive_agent.py
    COMPETITOR_CHECKED = "competitor_checked"  # agents/competitor_check_agent.py
    # Reserved for a future phase -- not emitted by any code today: a human
    # explicitly flagging that a past rejection or score was wrong. Phase 5's
    # rejection feedback loop (tools/feedback.py) is automatic, not this.
    # HUMAN_FEEDBACK = "human_feedback"


class ProofType(StrEnum):
    EDGAR_FUNDING = "edgar_funding"
    DISCLOSED_REVENUE = "disclosed_revenue"
    APP_STORE_RANKING = "app_store_ranking"


class RejectionReason:
    """`<gate>:<rule>` string constants -- the canonical source of truth for
    values written to `opportunities.rejection_reason` (plain text in the DB).
    Not a StrEnum: the rule set is expected to grow, and a plain namespace of
    constants avoids an enum migration exercise for something that was
    deliberately kept as open text in the schema.
    """

    ARBITRAGE_NO_BARRIER_IDENTIFIED = "arbitrage:no_barrier_identified"

    BUILDABILITY_REGULATED_DOMAIN = "buildability:regulated_domain"
    BUILDABILITY_HEAVY_INTEGRATION = "buildability:heavy_integration"
    BUILDABILITY_CAPITAL_INTENSIVE_ENTERPRISE = "buildability:capital_intensive_enterprise"

    VENDABILITY_REGULATORY_RISK = "vendability:regulatory_risk"
    VENDABILITY_NON_RECURRING_MODEL = "vendability:non_recurring_model"
    VENDABILITY_REQUIRES_DAILY_INTERVENTION = "vendability:requires_daily_intervention"

    # Warning-only tags: appear in a GateResult's `reasons` list without
    # failing the gate. See CLAUDE.md "Known, deliberate limitations".
    VENDABILITY_PERSONAL_BRAND_RISK_WARNING = "vendability:personal_brand_risk"
    VENDABILITY_COMPETITOR_SATURATION_WARNING = "vendability:competitor_saturation"
