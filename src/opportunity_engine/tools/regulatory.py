"""Pure regulatory-risk classification, shared by both the buildability and
vendability gates (tools.scoring_tools) so the two don't maintain duplicate
keyword/SIC lists -- this is the ordinary DRY case that doesn't need a new
abstraction, just one shared function.

Known limitation: EDGAR's SIC classification is empty for most Form D filers
in practice (confirmed against live data -- brand-new single-purpose
investment vehicles typically have none on file; established filers like
bank holding companies do). SIC-based detection is a bonus signal when
present, not something to rely on as the primary regulatory-risk check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Well-known SIC ranges with real licensing/compliance overhead for a
# one-person-plus-agents team to enter. Not exhaustive -- a documented,
# extend-as-needed heuristic, not a legal classification.
_REGULATED_SIC_RANGES: list[tuple[int, int, str]] = [
    (6000, 6099, "depository_institutions"),  # banks
    (6100, 6199, "non_depository_credit"),  # lending
    (6300, 6399, "insurance"),
    (8000, 8099, "health_services"),
]

_REGULATED_APP_STORE_GENRES = frozenset({"Medical", "Finance"})

_REGULATED_KEYWORDS = (
    "hipaa",
    "fda approval",
    "broker-dealer",
    "money transmitter",
    "insurance license",
    "medical device",
    "controlled substance",
)


@dataclass(frozen=True)
class RegulatoryRisk:
    regulated: bool
    reasons: list[str] = field(default_factory=list)


def _sic_category(sic_code: str | None) -> str | None:
    if not sic_code or not sic_code.isdigit():
        return None
    code = int(sic_code)
    for low, high, label in _REGULATED_SIC_RANGES:
        if low <= code <= high:
            return label
    return None


def classify_regulatory_risk(
    text: str | None, sic_code: str | None, app_store_genre: str | None
) -> RegulatoryRisk:
    reasons = []

    sic_category = _sic_category(sic_code)
    if sic_category:
        reasons.append(f"sic:{sic_category}")

    if app_store_genre in _REGULATED_APP_STORE_GENRES:
        reasons.append(f"app_store_genre:{app_store_genre}")

    lowered = (text or "").lower()
    for keyword in _REGULATED_KEYWORDS:
        if keyword in lowered:
            reasons.append(f"keyword:{keyword}")

    return RegulatoryRisk(regulated=bool(reasons), reasons=reasons)
