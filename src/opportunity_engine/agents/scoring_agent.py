"""Single-responsibility service: rolls up daily signal, syncs proof events,
runs the opportunity's DetectionStrategy and both eliminatory gates, computes
momentum/market-proof/composite score, and persists a fully traceable
score_history row. Talks to other agents only through the database and the
events log.

Known simplification (documented, not hidden): `app_store_chart_countries` is
derived purely from which countries' RSS charts a given app has appeared in
during ingestion -- there is no live iTunes `lookup` call here to confirm
genuine listing absence in the target market. An app that's listed in the US
but simply doesn't chart top-100 there will look identical, to this pipeline,
to one that's genuinely absent. This keeps Phase 2 fully DB/Python-only (no
network calls in scoring, matching acceptance criterion #5's spirit) at the
cost of a real but bounded false-barrier risk -- a good Phase 4 enrichment
candidate, not a Phase 1-2 requirement.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import psycopg

from opportunity_engine.clock import Clock, utc_now
from opportunity_engine.domain.enums import DetectionStrategyName, EventType
from opportunity_engine.domain.models import (
    CandidateEvidence,
    DailyValue,
    GateResult,
    MomentumResult,
    ProofEvent,
    StrategyEvaluation,
)
from opportunity_engine.events import append_event
from opportunity_engine.strategies.arbitrage import ArbitrageStrategy
from opportunity_engine.strategies.base import DetectionStrategy
from opportunity_engine.strategies.pain_driven import PainDrivenStrategy
from opportunity_engine.tools.clustering import nearest_centroids
from opportunity_engine.tools.demand_signals import (
    DEMAND_WILLINGNESS_TO_PAY,
    DemandAssessment,
    classify_demand,
    extract_demand_mentions,
)
from opportunity_engine.tools.feedback import RejectionPenalty, compute_rejection_penalty
from opportunity_engine.tools.revenue_extraction import extract_revenue_mentions
from opportunity_engine.tools.scope_classifier import ScopeAssessment, classify_scope
from opportunity_engine.tools.scoring_tools import (
    APP_STORE_RANKING_CONFIDENCE,
    DEFAULT_MOMENTUM_CONFIG,
    DISCLOSED_REVENUE_CONFIDENCE,
    EDGAR_FUNDING_CONFIDENCE,
    EDGAR_FUNDING_WEIGHT,
    WILLINGNESS_TO_PAY_CONFIDENCE,
    MomentumConfig,
    app_store_rank_weight,
    compute_composite_score,
    compute_market_proof,
    compute_momentum,
    evaluate_buildability,
    evaluate_vendability,
    revenue_weight_for_monthly_amount,
    willingness_to_pay_weight,
)

logger = logging.getLogger(__name__)

STRATEGIES: dict[DetectionStrategyName, DetectionStrategy] = {
    DetectionStrategyName.PAIN_DRIVEN: PainDrivenStrategy(),
    DetectionStrategyName.ARBITRAGE: ArbitrageStrategy(),
}

# app_rank_best stores the raw chart rank (lower = better); momentum z-scoring
# expects "higher = growth", so this is the fixed transform applied when
# loading the series -- see tools/scoring_tools.py's momentum docstring.
_APP_RANK_INVERSION_BASE = 101

# Every doc_type whose title+body is free-text pain/launch language, fed
# into evidence text, the daily mention-count rollup, and revenue-mention
# extraction identically -- as opposed to edgar_formd/app_store_ranking,
# which carry structured signal instead of prose.
_PAIN_DRIVEN_TEXT_DOC_TYPES = (
    "hn_ask",
    "hn_show",
    "reddit_post",
    "producthunt_post",
    "stackexchange_question",
    "github_issue",
    "app_store_review",
    "discourse_topic",
)


@dataclass
class ScoringStats:
    scored: int = 0
    rejected: int = 0


def run_scoring(
    conn: psycopg.Connection[Any],
    *,
    clock: Clock = utc_now,
    momentum_cfg: MomentumConfig = DEFAULT_MOMENTUM_CONFIG,
) -> ScoringStats:
    today = clock().date()
    stats = ScoringStats()

    opportunities = conn.execute(
        "SELECT id, primary_strategy, category, competitor_match_count FROM opportunities "
        "WHERE status IN ('candidate', 'qualified')"
    ).fetchall()

    for opportunity_id, primary_strategy_value, category, competitor_match_count in opportunities:
        rollup_daily_signal(conn, opportunity_id, today)
        _sync_proof_events(conn, opportunity_id, clock)
        conn.commit()

        primary_strategy = DetectionStrategyName(primary_strategy_value)
        evidence = _assemble_evidence(
            conn, opportunity_id, primary_strategy, category, competitor_match_count
        )

        strategy_eval = STRATEGIES[primary_strategy].evaluate(evidence)
        buildability = evaluate_buildability(evidence)
        vendability = evaluate_vendability(evidence)

        channel_series = _load_channel_series(conn, opportunity_id)
        momentum = compute_momentum(channel_series, today, momentum_cfg)
        proof_events = _load_proof_events(conn, opportunity_id)
        market_proof_score = compute_market_proof(proof_events, today)
        scope = classify_scope(evidence.text)
        demand = classify_demand(evidence.text)

        overall_pass = strategy_eval.accepted and buildability.passed and vendability.passed
        composite_score = (
            compute_composite_score(momentum, market_proof_score, scope, demand)
            if overall_pass
            else None
        )
        barrier_pass = (
            strategy_eval.accepted if primary_strategy == DetectionStrategyName.ARBITRAGE else None
        )

        rejection_penalty = RejectionPenalty(points=0.0)
        if not overall_pass:
            rejection_reason, rejection_detail = _first_rejection(
                strategy_eval, buildability, vendability
            )
            _reject_opportunity(conn, opportunity_id, rejection_reason, rejection_detail, clock)
            stats.rejected += 1
        else:
            assert composite_score is not None
            rejection_penalty = _compute_rejection_feedback(conn, opportunity_id)
            composite_score = max(0.0, composite_score - rejection_penalty.points)
            _update_opportunity_score(conn, opportunity_id, composite_score, momentum, clock)
            append_event(
                conn,
                EventType.OPPORTUNITY_SCORED,
                opportunity_id=opportunity_id,
                payload={
                    "composite_score": composite_score,
                    "rejection_penalty": rejection_penalty.points,
                },
            )
            stats.scored += 1

        _write_score_history(
            conn,
            opportunity_id=opportunity_id,
            window_end=today,
            momentum=momentum,
            market_proof_score=market_proof_score,
            buildability=buildability,
            vendability=vendability,
            barrier_pass=barrier_pass,
            barrier_evidence=strategy_eval.evidence if strategy_eval.barriers else {},
            composite_score=composite_score,
            strategy=primary_strategy,
            evidence=evidence,
            rejection_penalty=rejection_penalty,
            scope=scope,
            demand=demand,
        )
        conn.commit()

    return stats


def _first_rejection(
    strategy_eval: StrategyEvaluation, buildability: GateResult, vendability: GateResult
) -> tuple[str, dict[str, Any]]:
    if not strategy_eval.accepted:
        assert strategy_eval.rejection_reason is not None
        return strategy_eval.rejection_reason, {"strategy_evidence": strategy_eval.evidence}
    if not buildability.passed:
        return buildability.reasons[0], buildability.detail
    assert not vendability.passed
    return vendability.reasons[0], vendability.detail


def _assemble_evidence(
    conn: psycopg.Connection[Any],
    opportunity_id: int,
    primary_strategy: DetectionStrategyName,
    category: str | None,
    competitor_match_count: int | None,
) -> CandidateEvidence:
    rows = conn.execute(
        """
        SELECT rd.doc_type, rd.title, rd.body, rd.country_code, rd.category, rd.source_url
        FROM opportunity_sources os
        JOIN raw_documents rd ON rd.id = os.raw_document_id
        WHERE os.opportunity_id = %s
        """,
        (opportunity_id,),
    ).fetchall()

    text_parts: list[str] = []
    sic_code: str | None = None
    app_store_genre: str | None = None
    chart_countries: set[str] = set()
    source_domain: str | None = None

    for doc_type, title, body, country_code, doc_category, source_url in rows:
        if doc_type in _PAIN_DRIVEN_TEXT_DOC_TYPES:
            if title:
                text_parts.append(title)
            if body:
                text_parts.append(body)
            if source_url and source_domain is None:
                source_domain = _extract_domain(source_url)
        elif doc_type == "edgar_formd":
            if title:
                text_parts.append(title)
            sic_code = sic_code or doc_category
        elif doc_type == "app_store_ranking":
            if title:
                text_parts.append(title)
            app_store_genre = app_store_genre or doc_category
            if country_code:
                chart_countries.add(country_code)

    return CandidateEvidence(
        opportunity_id=opportunity_id,
        primary_strategy=primary_strategy,
        text="\n".join(text_parts),
        category=category,
        sic_code=sic_code,
        app_store_genre=app_store_genre,
        app_store_chart_countries=frozenset(chart_countries),
        app_store_listing_countries=frozenset(chart_countries),  # see module docstring limitation
        distinct_source_count=len(rows),
        source_domain=source_domain,
        wikipedia_pageviews_by_project=_load_wikipedia_series(conn, opportunity_id),
        competitor_match_count=competitor_match_count,
    )


def _extract_domain(url: str) -> str:
    without_scheme = url.split("://", 1)[-1]
    return without_scheme.split("/", 1)[0]


def _load_wikipedia_series(
    conn: psycopg.Connection[Any], opportunity_id: int
) -> dict[str, list[DailyValue]]:
    topics = conn.execute(
        "SELECT project, article FROM tracked_topics WHERE added_by_opportunity_id = %s",
        (opportunity_id,),
    ).fetchall()
    series: dict[str, list[DailyValue]] = {}
    for project, article in topics:
        rows = conn.execute(
            """
            SELECT pageview_date, views FROM wikipedia_pageviews_daily
            WHERE project = %s AND article = %s ORDER BY pageview_date
            """,
            (project, article),
        ).fetchall()
        series[project] = [DailyValue(day=day, value=float(views)) for day, views in rows]
    return series


def rollup_daily_signal(conn: psycopg.Connection[Any], opportunity_id: int, today: date) -> None:
    """Public (not `_`-prefixed) because agents/archive_import_agent.py also
    calls this directly, once per (opportunity_id, historical day) touched by
    a bulk import -- an instant multi-week momentum baseline instead of
    waiting for that many days of live daily `run_scoring` calls to build one
    up naturally. `today` is just this function's parameter name, not an
    assumption that it's actually today; run_scoring always calls it with the
    real current date, archive import calls it with a historical one.

    Buckets by `published_at`, not `fetched_at`: every Phase 1-3 parser sets
    published_at to the item's real-world date (post creation time, SEC
    filing date, chart-observation date), while fetched_at is when *this
    process* happened to see it -- identical for live daily ingestion, but
    for a bulk historical import fetched_at is just "whenever the import was
    run" for every row, which would collapse an entire archive onto one day."""
    row = conn.execute(
        """
        SELECT
            count(*) FILTER (WHERE rd.doc_type = ANY(%s)) AS mention_count,
            count(*) FILTER (WHERE rd.doc_type = 'edgar_formd') AS edgar_filing_count,
            min((rd.raw_json ->> 'rank')::int) FILTER (WHERE rd.doc_type = 'app_store_ranking')
                AS app_rank_best
        FROM opportunity_sources os
        JOIN raw_documents rd ON rd.id = os.raw_document_id
        WHERE os.opportunity_id = %s AND rd.published_at::date = %s
        """,
        (list(_PAIN_DRIVEN_TEXT_DOC_TYPES), opportunity_id, today),
    ).fetchone()
    assert row is not None
    mention_count, edgar_filing_count, app_rank_best = row

    pageview_row = conn.execute(
        """
        SELECT COALESCE(sum(wpd.views), 0)
        FROM tracked_topics tt
        JOIN wikipedia_pageviews_daily wpd
            ON wpd.project = tt.project AND wpd.article = tt.article
        WHERE tt.added_by_opportunity_id = %s AND wpd.pageview_date = %s
        """,
        (opportunity_id, today),
    ).fetchone()
    assert pageview_row is not None
    pageview_count = pageview_row[0]

    conn.execute(
        """
        INSERT INTO opportunity_daily_signal
            (opportunity_id, signal_date, mention_count, pageview_count, app_rank_best, edgar_filing_count)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (opportunity_id, signal_date) DO UPDATE SET
            mention_count = EXCLUDED.mention_count,
            pageview_count = EXCLUDED.pageview_count,
            app_rank_best = EXCLUDED.app_rank_best,
            edgar_filing_count = EXCLUDED.edgar_filing_count
        """,
        (opportunity_id, today, mention_count, pageview_count, app_rank_best, edgar_filing_count),
    )


def _load_channel_series(
    conn: psycopg.Connection[Any], opportunity_id: int
) -> dict[str, list[DailyValue]]:
    rows = conn.execute(
        """
        SELECT signal_date, mention_count, pageview_count, app_rank_best, edgar_filing_count
        FROM opportunity_daily_signal
        WHERE opportunity_id = %s
        ORDER BY signal_date
        """,
        (opportunity_id,),
    ).fetchall()

    mention: list[DailyValue] = []
    pageview: list[DailyValue] = []
    app_rank: list[DailyValue] = []
    edgar: list[DailyValue] = []
    for signal_date, mention_count, pageview_count, rank_best, edgar_count in rows:
        if mention_count is not None:
            mention.append(DailyValue(day=signal_date, value=float(mention_count)))
        if pageview_count is not None:
            pageview.append(DailyValue(day=signal_date, value=float(pageview_count)))
        if rank_best is not None:
            app_rank.append(
                DailyValue(day=signal_date, value=float(_APP_RANK_INVERSION_BASE - rank_best))
            )
        if edgar_count is not None:
            edgar.append(DailyValue(day=signal_date, value=float(edgar_count)))

    series = {}
    if mention:
        series["mention_count"] = mention
    if pageview:
        series["pageview_count"] = pageview
    if app_rank:
        series["app_rank_best"] = app_rank
    if edgar:
        series["edgar_filing_count"] = edgar
    return series


def _sync_proof_events(conn: psycopg.Connection[Any], opportunity_id: int, clock: Clock) -> None:
    """Detects newly linked, not-yet-scored raw_documents and creates the
    proof_events they warrant, if any. Docs that produce no proof (e.g. an
    HN post with no revenue mention) are simply revisited on the next run --
    cheap at this project's volume, and avoids a second "already checked, no
    proof" marker table."""
    rows = conn.execute(
        """
        SELECT rd.id, rd.doc_type, rd.title, rd.body, rd.published_at, rd.raw_json
        FROM opportunity_sources os
        JOIN raw_documents rd ON rd.id = os.raw_document_id
        WHERE os.opportunity_id = %s
          AND NOT EXISTS (SELECT 1 FROM proof_events pe WHERE pe.raw_document_id = rd.id)
        """,
        (opportunity_id,),
    ).fetchall()

    for raw_document_id, doc_type, title, body, published_at, raw_json in rows:
        observed_at = (published_at or clock()).date()
        if doc_type == "edgar_formd":
            _insert_proof_event(
                conn,
                opportunity_id,
                raw_document_id,
                "edgar_funding",
                EDGAR_FUNDING_WEIGHT,
                EDGAR_FUNDING_CONFIDENCE,
                observed_at,
                {},
            )
        elif doc_type in _PAIN_DRIVEN_TEXT_DOC_TYPES:
            text = "\n".join(part for part in (title, body) if part)
            mentions = extract_revenue_mentions(text)
            if mentions:
                best = max(mentions, key=lambda m: m.monthly_amount_usd)
                _insert_proof_event(
                    conn,
                    opportunity_id,
                    raw_document_id,
                    "disclosed_revenue",
                    revenue_weight_for_monthly_amount(best.monthly_amount_usd),
                    DISCLOSED_REVENUE_CONFIDENCE,
                    observed_at,
                    {"monthly_amount_usd": best.monthly_amount_usd, "raw_match": best.raw_match},
                )
            # A separate, additional proof_event, not mutually exclusive with
            # disclosed_revenue above -- a post can both report revenue and
            # separately state willingness to pay (e.g. in a comment thread).
            willingness_mentions = [
                m
                for m in extract_demand_mentions(text)
                if m.demand_type == DEMAND_WILLINGNESS_TO_PAY
            ]
            if willingness_mentions:
                best_willingness = max(
                    willingness_mentions,
                    key=lambda m: m.monthly_amount_usd if m.monthly_amount_usd is not None else -1,
                )
                _insert_proof_event(
                    conn,
                    opportunity_id,
                    raw_document_id,
                    "willingness_to_pay",
                    willingness_to_pay_weight(best_willingness.monthly_amount_usd),
                    WILLINGNESS_TO_PAY_CONFIDENCE,
                    observed_at,
                    {
                        "monthly_amount_usd": best_willingness.monthly_amount_usd,
                        "raw_match": best_willingness.raw_match,
                    },
                )
        elif doc_type == "app_store_ranking":
            rank = raw_json.get("rank")
            if rank is not None:
                _insert_proof_event(
                    conn,
                    opportunity_id,
                    raw_document_id,
                    "app_store_ranking",
                    app_store_rank_weight(int(rank)),
                    APP_STORE_RANKING_CONFIDENCE,
                    observed_at,
                    {"rank": rank},
                )


def _insert_proof_event(
    conn: psycopg.Connection[Any],
    opportunity_id: int,
    raw_document_id: int,
    proof_type: str,
    weight: float,
    confidence: float,
    observed_at: date,
    extracted_value: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO proof_events
            (opportunity_id, proof_type, raw_document_id, observed_at, weight, confidence, extracted_value)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            opportunity_id,
            proof_type,
            raw_document_id,
            observed_at,
            weight,
            confidence,
            _to_json(extracted_value),
        ),
    )


def _to_json(value: dict[str, Any]) -> str:
    return json.dumps(value, default=str)


def _load_proof_events(conn: psycopg.Connection[Any], opportunity_id: int) -> list[ProofEvent]:
    rows = conn.execute(
        "SELECT proof_type, observed_at, weight, confidence FROM proof_events WHERE opportunity_id = %s",
        (opportunity_id,),
    ).fetchall()
    return [
        ProofEvent(
            proof_type=proof_type,
            observed_at=observed_at,
            weight=float(weight),
            confidence=float(confidence),
        )
        for proof_type, observed_at, weight, confidence in rows
    ]


def _compute_rejection_feedback(
    conn: psycopg.Connection[Any], opportunity_id: int
) -> RejectionPenalty:
    """Phase 5: a persisted rejection feeds future scoring by softly
    penalizing candidates that sit in the semantic neighborhood of past
    rejections -- never a hard veto, since the eliminatory gates already
    decided pass/fail before this runs."""
    row = conn.execute(
        "SELECT centroid_embedding FROM opportunities WHERE id = %s", (opportunity_id,)
    ).fetchone()
    if row is None or row[0] is None:
        return RejectionPenalty(points=0.0)
    centroid = row[0].to_list()
    neighbors = nearest_centroids(
        conn, centroid, k=5, statuses=["rejected"], exclude_opportunity_id=opportunity_id
    )
    return compute_rejection_penalty(neighbors)


def _reject_opportunity(
    conn: psycopg.Connection[Any],
    opportunity_id: int,
    rejection_reason: str,
    rejection_detail: dict[str, Any],
    clock: Clock,
) -> None:
    now = clock()
    conn.execute(
        """
        UPDATE opportunities
        SET status = 'rejected', rejection_reason = %s, rejection_detail = %s,
            last_scored_at = %s, updated_at = %s
        WHERE id = %s
        """,
        (rejection_reason, _to_json(rejection_detail), now, now, opportunity_id),
    )
    append_event(
        conn,
        EventType.OPPORTUNITY_REJECTED,
        opportunity_id=opportunity_id,
        payload={"rejection_reason": rejection_reason, "rejection_detail": rejection_detail},
    )


def _update_opportunity_score(
    conn: psycopg.Connection[Any],
    opportunity_id: int,
    composite_score: float | None,
    momentum: MomentumResult,
    clock: Clock,
) -> None:
    now = clock()
    conn.execute(
        """
        UPDATE opportunities
        SET current_score = %s,
            current_score_breakdown = %s,
            last_scored_at = %s,
            last_seen_at = %s,
            updated_at = %s
        WHERE id = %s
        """,
        (
            composite_score,
            _to_json({"momentum": momentum.score, "momentum_confidence": str(momentum.confidence)}),
            now,
            now,
            now,
            opportunity_id,
        ),
    )


def _write_score_history(
    conn: psycopg.Connection[Any],
    *,
    opportunity_id: int,
    window_end: date,
    momentum: MomentumResult,
    market_proof_score: float,
    buildability: GateResult,
    vendability: GateResult,
    barrier_pass: bool | None,
    barrier_evidence: dict[str, Any],
    composite_score: float | None,
    strategy: DetectionStrategyName,
    evidence: CandidateEvidence,
    rejection_penalty: RejectionPenalty,
    scope: ScopeAssessment,
    demand: DemandAssessment,
) -> None:
    inputs_snapshot = {
        "text_excerpt": evidence.text[:500],
        "sic_code": evidence.sic_code,
        "app_store_genre": evidence.app_store_genre,
        "app_store_chart_countries": sorted(evidence.app_store_chart_countries),
        "distinct_source_count": evidence.distinct_source_count,
        "rejection_penalty_points": rejection_penalty.points,
        "rejection_penalty_neighbors": rejection_penalty.contributing_neighbors,
        "scope_score": scope.score,
        "scope_narrow_matches": scope.narrow_matches,
        "scope_broad_matches": scope.broad_matches,
        "scope_integration_count": scope.integration_count,
        "demand_score": demand.score,
        "demand_matched_types": demand.matched_types,
    }
    conn.execute(
        """
        INSERT INTO score_history (
            opportunity_id, window_end, momentum_score, momentum_confidence,
            market_proof_score, buildability_pass, buildability_reasons,
            vendability_pass, vendability_reasons, barrier_pass, barrier_evidence,
            composite_score, strategy, inputs_snapshot
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            opportunity_id,
            window_end,
            momentum.score,
            str(momentum.confidence),
            market_proof_score,
            buildability.passed,
            _to_json({"reasons": buildability.reasons, "detail": buildability.detail}),
            vendability.passed,
            _to_json({"reasons": vendability.reasons, "detail": vendability.detail}),
            barrier_pass,
            _to_json(barrier_evidence),
            composite_score,
            strategy.value,
            _to_json(inputs_snapshot),
        ),
    )
