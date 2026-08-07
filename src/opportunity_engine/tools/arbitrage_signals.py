"""Concrete barrier evidence for ArbitrageStrategy, given only Phase-1 data
sources (App Store charts/lookup, EDGAR, Wikipedia Pageviews).

Simplifying assumption stated explicitly: the target market is fixed to
"us" and the origin markets of interest are JP/KR/BR -- matching the spec's
own example countries and this project's App Store country coverage. A
future phase could generalize this to arbitrary market pairs; Phase 1-2 does
not need to.
"""

from __future__ import annotations

from opportunity_engine.domain.models import Barrier, CandidateEvidence
from opportunity_engine.tools.regulatory import classify_regulatory_risk

TARGET_MARKET = "us"
ORIGIN_MARKETS_OF_INTEREST = frozenset({"jp", "kr", "br"})
_WIKIPEDIA_ASYMMETRY_RATIO = 3.0  # foreign pageviews must be >= 3x English to count


def has_cjk_script(text: str) -> bool:
    """Unicode-range check for Japanese/Korean/Chinese script -- no
    `langdetect` dependency needed for this narrow purpose. Used to
    corroborate whether a target-market App Store listing is genuinely
    localized: iTunes' own `languageCodesISO2A` metadata is not fully
    reliable on its own (live data shows apps with real Korean-language
    content still declaring only `['EN']` there)."""
    for char in text:
        code = ord(char)
        if (
            0x3040 <= code <= 0x30FF  # Hiragana / Katakana
            or 0x4E00 <= code <= 0x9FFF  # CJK Unified Ideographs
            or 0xAC00 <= code <= 0xD7A3  # Hangul syllables
        ):
            return True
    return False


def language_localization_barrier(evidence: CandidateEvidence) -> Barrier | None:
    """Primary, strongest barrier: charting in an origin market with no
    equivalent, localized listing in the target market."""
    origin_charts = evidence.app_store_chart_countries & ORIGIN_MARKETS_OF_INTEREST
    if not origin_charts:
        return None
    if TARGET_MARKET in evidence.app_store_chart_countries:
        return None  # already charting in the target market too -- no barrier
    if evidence.has_localized_target_listing:
        return None  # listed and genuinely localized in the target market -- no barrier
    return Barrier(
        kind="language_localization_barrier",
        detail={
            "origin_markets": sorted(origin_charts),
            "target_market": TARGET_MARKET,
            "has_target_listing": TARGET_MARKET in evidence.app_store_listing_countries,
            "has_localized_target_listing": evidence.has_localized_target_listing,
        },
    )


def payment_distribution_barrier(
    evidence: CandidateEvidence, *, has_primary_barrier: bool
) -> Barrier | None:
    """Secondary, weak alone -- explicitly never sufficient on its own:
    "no competitor in the target market" by itself is as likely to mean
    "no demand" as "a barrier exists". Only counted when the primary
    (language/localization) barrier is already present."""
    if not has_primary_barrier:
        return None
    if not evidence.pricing_varies_by_country:
        return None
    if evidence.competitor_in_target_country:
        return None
    return Barrier(
        kind="payment_distribution_barrier",
        detail={"pricing_varies_by_country": True, "competitor_in_target_country": False},
    )


def regulatory_barrier(evidence: CandidateEvidence) -> Barrier | None:
    """Rare, EDGAR-sourced: origin-market SIC code/App Store genre flagged as
    regulated in a way that plausibly slows down direct market entry
    elsewhere. Unlike payment_distribution_barrier, this can stand on its own
    -- a genuine licensing/compliance barrier is a real moat by itself."""
    risk = classify_regulatory_risk(evidence.text, evidence.sic_code, evidence.app_store_genre)
    if not risk.regulated:
        return None
    return Barrier(kind="regulatory_barrier", detail={"regulatory_reasons": risk.reasons})


def wikipedia_cross_language_asymmetry(evidence: CandidateEvidence) -> Barrier | None:
    """Corroborating only -- deliberately never sufficient by itself to
    justify accepting the strategy (ArbitrageStrategy only counts this when
    at least one standalone barrier, language or regulatory, already fired).
    Requires the topic to already be tracked in multiple Wikipedia
    projects."""
    en_series = evidence.wikipedia_pageviews_by_project.get("en.wikipedia")
    foreign_projects = {"ja.wikipedia", "ko.wikipedia", "pt.wikipedia"} & set(
        evidence.wikipedia_pageviews_by_project.keys()
    )
    if not en_series or not foreign_projects:
        return None

    en_total = sum(v.value for v in en_series)
    for project in sorted(foreign_projects):
        foreign_total = sum(v.value for v in evidence.wikipedia_pageviews_by_project[project])
        if foreign_total <= 0:
            continue
        if en_total == 0 or foreign_total / en_total >= _WIKIPEDIA_ASYMMETRY_RATIO:
            return Barrier(
                kind="wikipedia_cross_language_asymmetry",
                detail={"project": project, "foreign_total": foreign_total, "en_total": en_total},
            )
    return None
