"""Pure, dependency-free dataclasses shared across the codebase.

Nothing here talks to the database, the network, or a model -- these are the
shapes that flow between collectors, tools, strategies, and agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from opportunity_engine.domain.enums import DetectionStrategyName, MomentumConfidence


@dataclass(frozen=True)
class TrackedTopic:
    """A Wikipedia article watched for pageview momentum -- the input list
    WikipediaPageviewsCollector needs, since (unlike the other three Phase-1
    connectors) it's candidate-driven rather than world-scanning."""

    project: str  # e.g. 'en.wikipedia', 'ja.wikipedia'
    article: str  # exact Wikipedia article title


@dataclass(frozen=True)
class RawDocument:
    connector_name: str
    external_id: str
    doc_type: str
    fetched_at: datetime
    content_hash: str
    raw_json: dict[str, Any]
    published_at: datetime | None = None
    source_url: str | None = None
    title: str | None = None
    body: str | None = None
    country_code: str | None = None
    category: str | None = None
    id: int | None = None  # set once persisted


@dataclass(frozen=True)
class DailyValue:
    day: date
    value: float


@dataclass(frozen=True)
class ProofEvent:
    proof_type: str
    observed_at: date
    weight: float
    confidence: float
    extracted_value: dict[str, Any] = field(default_factory=dict)
    opportunity_id: int | None = None
    raw_document_id: int | None = None
    id: int | None = None


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MomentumResult:
    score: float
    confidence: MomentumConfidence
    channel_scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Barrier:
    kind: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateEvidence:
    """Evidence bag assembled by ScoringAgent from an opportunity's linked
    documents/signals, and handed to a DetectionStrategy and to the
    buildability/vendability gates. Fields are additive as new signal types
    are wired in -- this is internal application data, not a DB row, so
    growing it costs nothing."""

    opportunity_id: int
    primary_strategy: DetectionStrategyName
    text: str
    category: str | None = None
    sic_code: str | None = None
    app_store_genre: str | None = None
    edgar_offering_amount: float | None = None
    app_store_chart_countries: frozenset[str] = field(default_factory=frozenset)
    app_store_listing_countries: frozenset[str] = field(default_factory=frozenset)
    has_localized_target_listing: bool | None = None
    pricing_varies_by_country: bool = False
    competitor_in_target_country: bool | None = None
    wikipedia_pageviews_by_project: dict[str, list[DailyValue]] = field(default_factory=dict)
    distinct_source_count: int = 1
    source_domain: str | None = None
    # GitHub repo search + npm registry search match count (see
    # agents/competitor_check_agent.py) -- None means not checked yet,
    # distinct from 0 (checked, found nothing).
    competitor_match_count: int | None = None


@dataclass(frozen=True)
class StrategyEvaluation:
    accepted: bool
    rejection_reason: str | None = None
    barriers: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoredOpportunity:
    opportunity_id: int
    strategy: DetectionStrategyName
    category: str | None
    composite_score: float
    last_proposed_score: float | None = None
    last_proposed_at: datetime | None = None


@dataclass(frozen=True)
class BacklogSlot:
    scored: ScoredOpportunity
    is_exploration_slot: bool
