"""Pure, rule-based heuristic: does an opportunity's evidence text read like
a narrow, single-feature tool, or a broad, full-platform build? Keyword-based,
not language understanding -- the same class of approximation as the
buildability/vendability gates in scoring_tools.py, and just as honestly
incomplete (see CLAUDE.md's "Known, deliberate limitations").

Why this exists: this pipeline's momentum/market-proof scoring rewards
well-evidenced ideas regardless of how big the underlying build is, which
structurally under-ranks a small, single-person-buildable idea relative to
a full platform with equally strong evidence. `evaluate_buildability`
already hard-rejects the clearly-impossible (regulated domains, heavy
integrations, capital-intensive enterprise); this adds a *soft* nudge for
everything that passes that gate but still reads as bigger-than-a-week-alone
in scope -- a warning-shaped signal, not a gate, same pattern as the
personal-brand-risk and competitor-saturation warnings.

Multi-integration detection is deliberately concrete, not a keyword guess:
verified against this project's own real ingested data (CloudQuell, Product
Hunt, 2026-08-07) pitching "AWS, OpenAI, Anthropic, Snowflake (Azure & GCP
in beta)" in one sentence -- six named providers is a real, checkable proxy
for "six integrations to build and maintain," independent of whatever
adjectives the pitch itself uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NARROW_SCOPE_KEYWORDS = (
    "extension",
    "plugin",
    "widget",
    "cli",
    "command-line",
    "bookmarklet",
    "add-on",
    "addon",
    "wrapper",
    "checker",
    "tracker",
    "converter",
    "calculator",
    "companion",
    "skill file",
    "single-purpose",
)
BROAD_SCOPE_KEYWORDS = (
    "platform",
    "marketplace",
    "end-to-end",
    "all-in-one",
    "ecosystem",
    "enterprise-grade",
    "infrastructure",
    "operating system",
    "workspace",
)
# Not exhaustive -- widely-integrated SaaS/cloud providers common enough in
# pitches on this pipeline's sources to be worth naming explicitly.
KNOWN_PROVIDER_NAMES = (
    "aws",
    "azure",
    "gcp",
    "google cloud",
    "snowflake",
    "salesforce",
    "hubspot",
    "stripe",
    "twilio",
    "sendgrid",
    "openai",
    "anthropic",
    "slack",
    "shopify",
    "quickbooks",
    "netsuite",
    "zendesk",
    "workday",
)
MULTI_INTEGRATION_THRESHOLD = 3

# Points added to (positive) or subtracted from (negative) the composite
# score -- a nudge, not a dominant factor. Starting point, not a tuned
# value, same caveat as every other threshold in scoring_tools.py.
COMPOSITE_SCOPE_WEIGHT = 15.0


@dataclass(frozen=True)
class ScopeAssessment:
    score: float  # -1.0 (reads broad) .. +1.0 (reads narrow); 0.0 = no signal
    narrow_matches: list[str] = field(default_factory=list)
    broad_matches: list[str] = field(default_factory=list)
    integration_count: int = 0


def classify_scope(text: str | None) -> ScopeAssessment:
    lowered = (text or "").lower()
    narrow_matches = [k for k in NARROW_SCOPE_KEYWORDS if k in lowered]
    broad_matches = [k for k in BROAD_SCOPE_KEYWORDS if k in lowered]
    integration_count = sum(1 for provider in KNOWN_PROVIDER_NAMES if provider in lowered)

    score = 0.0
    if narrow_matches:
        score += 0.5
    if broad_matches:
        score -= 0.5
    if integration_count >= MULTI_INTEGRATION_THRESHOLD:
        score -= 0.5
    score = max(-1.0, min(1.0, score))

    return ScopeAssessment(
        score=score,
        narrow_matches=narrow_matches,
        broad_matches=broad_matches,
        integration_count=integration_count,
    )
