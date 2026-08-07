"""Pure regex extraction of self-reported revenue mentions from free text
(HN posts). This is Phase 1-2's only non-official revenue-proof channel --
self-reported and unverified, which is exactly why its confidence weight
(see tools.scoring_tools.DISCLOSED_REVENUE_CONFIDENCE) is much lower than an
EDGAR filing's. No LLM, no ML: SQL/Python first, per the project's processing-
order rule -- an LLM would be overkill for "does this text contain a dollar
figure next to MRR/ARR."
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_AMOUNT_PATTERN = re.compile(
    r"\$\s?(?P<amount>\d+(?:[.,]\d+)?)\s?(?P<multiplier>[kKmM])?\s*"
    r"(?P<period>MRR|ARR|/\s?mo(?:nth)?\b|per\s+month|/\s?yr\b|per\s+year|/\s?year)",
    re.IGNORECASE,
)
_MULTIPLIERS = {"k": 1_000.0, "m": 1_000_000.0}
_ANNUAL_MARKERS = ("arr", "yr", "year")


@dataclass(frozen=True)
class ExtractedRevenue:
    monthly_amount_usd: float
    raw_match: str


def extract_revenue_mentions(text: str) -> list[ExtractedRevenue]:
    results = []
    for match in _AMOUNT_PATTERN.finditer(text):
        amount = float(match.group("amount").replace(",", ""))
        multiplier = _MULTIPLIERS.get((match.group("multiplier") or "").lower(), 1.0)
        amount *= multiplier
        period = match.group("period").lower()
        is_annual = any(marker in period for marker in _ANNUAL_MARKERS)
        monthly_amount = amount / 12 if is_annual else amount
        results.append(
            ExtractedRevenue(monthly_amount_usd=monthly_amount, raw_match=match.group(0))
        )
    return results
