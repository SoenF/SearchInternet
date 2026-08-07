"""Pure regex extraction of explicit-demand phrases from free text -- "I
wish there was a tool for X", "is there an app that does X", "someone
should build X", "alternative to X", "X doesn't support Y", "I'd pay $50/mo
for this". Mirrors tools/revenue_extraction.py's approach exactly: no LLM,
no ML, SQL/Python first -- an LLM would be overkill for phrase matching.

The core idea this implements: an opportunity someone is *explicitly asking
to exist* is stronger evidence than an opportunity merely *mentioned* (an
HN thread getting attention, a Wikipedia article trending) -- the existing
momentum dimension already captures "attention is growing," this captures
"someone articulated a specific unmet need," which is a different claim.

`WILLINGNESS_TO_PAY` is deliberately excluded from `classify_demand`'s own
score: it's a monetary claim (just prospective rather than realized), so it
feeds `proof_events`/market proof instead (see agents/scoring_agent.py's
`_sync_proof_events`) -- the same bucket as disclosed revenue -- rather than
being counted twice across two different scoring channels for one piece of
evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

DEMAND_EXPLICIT_REQUEST = "explicit_demand_request"
DEMAND_ALTERNATIVE_REQUEST = "alternative_request"
DEMAND_EXISTING_SOLUTION_COMPLAINT = "existing_solution_complaint"
DEMAND_WILLINGNESS_TO_PAY = "willingness_to_pay"

_EXPLICIT_REQUEST_PATTERNS = (
    re.compile(r"\bi wish (there was|there were|someone (made|built))\b", re.IGNORECASE),
    re.compile(r"\bis there (?:a|an|any) (?:tool|app|software|service|website)\b", re.IGNORECASE),
    re.compile(
        r"\bdoes anyone know (?:a|an|of a|of an)? ?(?:tool|app|software|service)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\blooking for (?:a|an) (?:tool|app|software|service) (?:to|that|for)\b", re.IGNORECASE
    ),
    re.compile(r"\bsomeone should (?:build|make|create)\b", re.IGNORECASE),
    re.compile(r"\bcan (?:someone|anyone) (?:make|build|create)\b", re.IGNORECASE),
    re.compile(r"\bwhy (?:doesn'?t|does not) .{0,40}exist\b", re.IGNORECASE),
    re.compile(r"\bhow (?:can|do) i automate\b", re.IGNORECASE),
    re.compile(r"\bneed a way to\b", re.IGNORECASE),
)
_ALTERNATIVE_REQUEST_PATTERNS = (
    re.compile(r"\balternative (?:to|for)\s+\w+", re.IGNORECASE),
    re.compile(r"\bneed an alternative\b", re.IGNORECASE),
)
_EXISTING_SOLUTION_COMPLAINT_PATTERNS = (
    re.compile(r"\b(?:is|are|'s) too expensive\b", re.IGNORECASE),
    re.compile(r"\bdoesn'?t (?:support|integrate with|have)\b", re.IGNORECASE),
    re.compile(r"\boverkill for\b", re.IGNORECASE),
    re.compile(r"\bi wish \w+ (?:had|supported)\b", re.IGNORECASE),
)
_WILLINGNESS_TO_PAY_PATTERN = re.compile(
    r"\b(?:i'?d|i would|would (?:happily )?)\s*pay\b"
    r"(?:[^.!?]{0,30}?\$\s?(?P<amount>\d+(?:[.,]\d+)?)\s?(?P<multiplier>[kK])?)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DemandMention:
    demand_type: str
    raw_match: str
    monthly_amount_usd: float | None = None


@dataclass(frozen=True)
class DemandAssessment:
    score: float  # 0.0 (no signal) .. 1.0 (multiple explicit-demand phrase types found)
    matched_types: list[str] = field(default_factory=list)


def extract_demand_mentions(text: str | None) -> list[DemandMention]:
    if not text:
        return []
    mentions: list[DemandMention] = []
    for pattern in _EXPLICIT_REQUEST_PATTERNS:
        mentions.extend(
            DemandMention(DEMAND_EXPLICIT_REQUEST, m.group(0)) for m in pattern.finditer(text)
        )
    for pattern in _ALTERNATIVE_REQUEST_PATTERNS:
        mentions.extend(
            DemandMention(DEMAND_ALTERNATIVE_REQUEST, m.group(0)) for m in pattern.finditer(text)
        )
    for pattern in _EXISTING_SOLUTION_COMPLAINT_PATTERNS:
        mentions.extend(
            DemandMention(DEMAND_EXISTING_SOLUTION_COMPLAINT, m.group(0))
            for m in pattern.finditer(text)
        )
    for match in _WILLINGNESS_TO_PAY_PATTERN.finditer(text):
        amount_str = match.group("amount")
        amount = None
        if amount_str:
            amount = float(amount_str.replace(",", ""))
            if (match.group("multiplier") or "").lower() == "k":
                amount *= 1000.0
        mentions.append(DemandMention(DEMAND_WILLINGNESS_TO_PAY, match.group(0), amount))
    return mentions


def classify_demand(text: str | None) -> DemandAssessment:
    """A modest composite-score nudge, not a dimension of its own -- same
    pattern as tools/scope_classifier.py. Presence-based, not count-based
    (repeating the same phrase three times in one post isn't three times
    the signal): each demand type contributes at most once, regardless of
    how many times it's matched."""
    types = {m.demand_type for m in extract_demand_mentions(text)}
    score = 0.0
    if DEMAND_EXPLICIT_REQUEST in types:
        score += 0.6
    if DEMAND_ALTERNATIVE_REQUEST in types:
        score += 0.3
    if DEMAND_EXISTING_SOLUTION_COMPLAINT in types:
        score += 0.3
    score = round(
        min(1.0, score), 2
    )  # avoid noisy floats like 0.8999999999999999 in stored snapshots
    matched = sorted(types - {DEMAND_WILLINGNESS_TO_PAY})
    return DemandAssessment(score=score, matched_types=matched)
