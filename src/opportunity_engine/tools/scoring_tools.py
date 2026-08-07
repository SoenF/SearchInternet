"""Pure scoring functions: momentum, market proof, and the buildability /
vendability eliminatory gates. No DB access -- agents/scoring_agent.py reads
the inputs and writes the results; this module is the decision logic alone,
which is what makes it independently, exhaustively unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean, stdev

from opportunity_engine.domain.enums import MomentumConfidence, RejectionReason
from opportunity_engine.domain.models import (
    CandidateEvidence,
    DailyValue,
    GateResult,
    MomentumResult,
    ProofEvent,
)
from opportunity_engine.tools.regulatory import classify_regulatory_risk


@dataclass(frozen=True)
class MomentumConfig:
    recent_days: int = 7
    baseline_days: int = 56  # 8 weeks
    min_baseline_days: int = 28  # bootstrap guard: need >= half the baseline populated
    channel_weights: dict[str, float] = field(
        default_factory=lambda: {
            "mention_count": 1.0,
            "pageview_count": 1.0,
            "app_rank_best": 1.0,
            "edgar_filing_count": 0.5,
        }
    )


DEFAULT_MOMENTUM_CONFIG = MomentumConfig()


def compute_channel_zscore(
    series: list[DailyValue], as_of: date, cfg: MomentumConfig
) -> float | None:
    """z-score of the last `recent_days` average against an 8-week baseline
    average -- never absolute volume, which is near-static and would produce
    the same ranking every time. Returns None (not zero) when there isn't
    enough baseline history yet, so callers can distinguish "no momentum" from
    "we can't tell yet" (see MomentumConfidence)."""
    recent_start = as_of - timedelta(days=cfg.recent_days - 1)
    baseline_start = as_of - timedelta(days=cfg.recent_days + cfg.baseline_days - 1)
    baseline_end = as_of - timedelta(days=cfg.recent_days)

    recent = [v.value for v in series if recent_start <= v.day <= as_of]
    baseline = [v.value for v in series if baseline_start <= v.day <= baseline_end]

    if len(baseline) < cfg.min_baseline_days:
        return None

    recent_avg = mean(recent) if recent else 0.0
    baseline_avg = mean(baseline)

    if baseline_avg == 0 and recent_avg == 0:
        return 0.0

    baseline_std = stdev(baseline) if len(baseline) > 1 else 0.0
    if baseline_std == 0:
        if recent_avg > baseline_avg:
            return 3.0
        if recent_avg < baseline_avg:
            return -3.0
        return 0.0

    return max(-3.0, min(3.0, (recent_avg - baseline_avg) / baseline_std))


def compute_momentum(
    channel_series: dict[str, list[DailyValue]],
    as_of: date,
    cfg: MomentumConfig = DEFAULT_MOMENTUM_CONFIG,
) -> MomentumResult:
    """Combines per-channel z-scores into a single 0-100 score, weighted by
    `cfg.channel_weights`. Channels without enough baseline history are
    dropped from the combination (not zeroed) -- if *no* channel has enough
    history yet (week one of a brand-new opportunity), the result is
    score=0.0 with confidence=insufficient_history: callers must treat that
    combination as "unknown, don't penalize or favor" rather than as a
    genuinely low momentum score."""
    channel_scores: dict[str, float] = {}
    for channel, series in channel_series.items():
        z = compute_channel_zscore(series, as_of, cfg)
        if z is not None:
            channel_scores[channel] = z

    if not channel_scores:
        return MomentumResult(
            score=0.0, confidence=MomentumConfidence.INSUFFICIENT_HISTORY, channel_scores={}
        )

    weights = {channel: cfg.channel_weights.get(channel, 1.0) for channel in channel_scores}
    total_weight = sum(weights.values())
    weighted_z = sum(z * weights[channel] for channel, z in channel_scores.items()) / total_weight
    score = max(0.0, min(100.0, 50 + weighted_z / 3 * 50))
    return MomentumResult(
        score=score, confidence=MomentumConfidence.OK, channel_scores=channel_scores
    )


# --- Market proof -----------------------------------------------------------
#
# A monetary proof is worth ten intent signals *by construction*, not by
# coincidence of numbers: intent signals (HN mentions, Wikipedia pageviews)
# never generate a ProofEvent at all -- they feed momentum, only actual
# revenue/funding/ranking evidence feeds this function. EDGAR_FUNDING_WEIGHT
# alone hits the 100 cap on its own.

PROOF_HALF_LIFE_DAYS: dict[str, int] = {
    "edgar_funding": 365,
    "disclosed_revenue": 180,
    "app_store_ranking": 30,
}
_DEFAULT_HALF_LIFE_DAYS = 90

EDGAR_FUNDING_WEIGHT = 100.0
EDGAR_FUNDING_CONFIDENCE = 1.0  # an official filing, not a claim

DISCLOSED_REVENUE_CONFIDENCE = 0.6  # self-reported on a public forum, unverified
APP_STORE_RANKING_CONFIDENCE = 0.8  # observed directly, but ranking != revenue


def revenue_weight_for_monthly_amount(monthly_amount_usd: float) -> float:
    if monthly_amount_usd >= 10_000:
        return 90.0
    if monthly_amount_usd >= 1_000:
        return 70.0
    return 40.0


def app_store_rank_weight(rank: int) -> float:
    if rank <= 10:
        return 60.0
    if rank <= 50:
        return 40.0
    return 25.0


def compute_market_proof(proof_events: list[ProofEvent], as_of: date) -> float:
    """Sum of weight * confidence * exponential time-decay across all proof
    events, capped at 100. Each proof_type decays on its own half-life --
    a funding event stays meaningful for roughly a year, an App Store rank
    for a month."""
    total = 0.0
    for event in proof_events:
        half_life = PROOF_HALF_LIFE_DAYS.get(event.proof_type, _DEFAULT_HALF_LIFE_DAYS)
        age_days = max((as_of - event.observed_at).days, 0)
        decay = 0.5 ** (age_days / half_life)
        total += event.weight * event.confidence * decay
    return min(total, 100.0)


# --- Buildability / vendability gates ---------------------------------------
#
# Both eliminatory, not weighted: a failing opportunity is REJECTED, not
# deranked. Phase 1-2 makes these rule-based approximations of what the
# user's spec actually asks for ("MVP in 2-4 weeks", "no dependency on a
# specific person/brand", ...) since there's no LLM judgment available yet --
# see CLAUDE.md "Known, deliberate limitations" for what that approximation
# gets wrong and why it's left that way until Phase 4.

HEAVY_INTEGRATION_KEYWORDS = (
    "enterprise sales",
    "hardware",
    "fda",
    "hipaa",
    "soc 2",
    "soc2",
    "government contract",
    "iso 27001",
    "on-premise deployment",
)
CAPITAL_INTENSIVE_ENTERPRISE_KEYWORDS = ("enterprise", "government", "fortune 500")
LARGE_RAISE_THRESHOLD_USD = 2_000_000.0

NON_RECURRING_KEYWORDS = (
    "lifetime deal",
    "one-time payment",
    "consulting",
    "freelance services",
)
DAILY_INTERVENTION_KEYWORDS = (
    "logistics",
    "field service",
    "on-site",
    "franchise",
    "manual fulfillment",
)
# A conservative signal only -- see evaluate_vendability's docstring on why
# this produces a warning, never an automatic rejection.
PERSONAL_BRAND_ONLY_DOMAINS = ("medium.com", "substack.com", "blogspot.com", "wordpress.com")


def _find_keyword(text: str | None, keywords: tuple[str, ...]) -> str | None:
    lowered = (text or "").lower()
    for keyword in keywords:
        if keyword in lowered:
            return keyword
    return None


def evaluate_buildability(evidence: CandidateEvidence) -> GateResult:
    """Default PASS; reject only on a matched red flag -- the spec describes
    exclusions (certification, heavy integration, capital-intensive), not
    required positive evidence, so a candidate with no red flags passes."""
    risk = classify_regulatory_risk(evidence.text, evidence.sic_code, evidence.app_store_genre)
    if risk.regulated:
        return GateResult(
            passed=False,
            reasons=[RejectionReason.BUILDABILITY_REGULATED_DOMAIN],
            detail={"regulatory_reasons": risk.reasons},
        )

    heavy_integration_match = _find_keyword(evidence.text, HEAVY_INTEGRATION_KEYWORDS)
    if heavy_integration_match is not None:
        return GateResult(
            passed=False,
            reasons=[RejectionReason.BUILDABILITY_HEAVY_INTEGRATION],
            detail={"matched_keyword": heavy_integration_match},
        )

    capital_intensive_match = _find_keyword(evidence.text, CAPITAL_INTENSIVE_ENTERPRISE_KEYWORDS)
    if (
        evidence.edgar_offering_amount is not None
        and evidence.edgar_offering_amount > LARGE_RAISE_THRESHOLD_USD
        and capital_intensive_match is not None
    ):
        return GateResult(
            passed=False,
            reasons=[RejectionReason.BUILDABILITY_CAPITAL_INTENSIVE_ENTERPRISE],
            detail={
                "matched_keyword": capital_intensive_match,
                "edgar_offering_amount": evidence.edgar_offering_amount,
            },
        )

    return GateResult(passed=True)


def evaluate_vendability(evidence: CandidateEvidence) -> GateResult:
    """Default PASS; reject only on a matched red flag. "Transferability" (no
    dependency on a specific person/brand) is the weakest rule here given only
    Phase-1 sources: `is_personal_brand_only_source` below only ever adds a
    *warning* to a passing result, never an automatic rejection -- real
    judgment on that dimension is deliberately deferred to Phase 4's LLM
    deep-dive."""
    risk = classify_regulatory_risk(evidence.text, evidence.sic_code, evidence.app_store_genre)
    if risk.regulated:
        return GateResult(
            passed=False,
            reasons=[RejectionReason.VENDABILITY_REGULATORY_RISK],
            detail={"regulatory_reasons": risk.reasons},
        )

    non_recurring_match = _find_keyword(evidence.text, NON_RECURRING_KEYWORDS)
    if non_recurring_match is not None:
        return GateResult(
            passed=False,
            reasons=[RejectionReason.VENDABILITY_NON_RECURRING_MODEL],
            detail={"matched_keyword": non_recurring_match},
        )

    daily_intervention_match = _find_keyword(evidence.text, DAILY_INTERVENTION_KEYWORDS)
    if daily_intervention_match is not None:
        return GateResult(
            passed=False,
            reasons=[RejectionReason.VENDABILITY_REQUIRES_DAILY_INTERVENTION],
            detail={"matched_keyword": daily_intervention_match},
        )

    reasons = []
    if is_personal_brand_only_source(evidence.source_domain):
        reasons.append(RejectionReason.VENDABILITY_PERSONAL_BRAND_RISK_WARNING)
    return GateResult(passed=True, reasons=reasons)


def is_personal_brand_only_source(source_domain: str | None) -> bool:
    if not source_domain:
        return False
    return any(domain in source_domain for domain in PERSONAL_BRAND_ONLY_DOMAINS)


# --- Composite score ---------------------------------------------------------

COMPOSITE_MOMENTUM_WEIGHT = 0.5
COMPOSITE_MARKET_PROOF_WEIGHT = 0.5


def compute_composite_score(momentum: MomentumResult, market_proof_score: float) -> float:
    """Combines the two weighted dimensions into the ranking score. The
    50/50 split is a documented starting point, not a value mandated by the
    spec (which specifies momentum and market proof as "weighted" without a
    fixed ratio) -- tune the two COMPOSITE_*_WEIGHT constants once real
    production data suggests a better split."""
    return (
        momentum.score * COMPOSITE_MOMENTUM_WEIGHT
        + market_proof_score * COMPOSITE_MARKET_PROOF_WEIGHT
    )
