"""Pure parsing: an EDGAR full-text-search hit (Form D filings) -> a RawDocument.

Note: `category` is repurposed to carry the filer's SIC code for this doc_type
(the same field carries an App Store genre for app_store_ranking documents) --
both feed `tools.regulatory.classify_regulatory_risk`, so keeping SIC/genre in
one place avoids the regulatory classifier needing to know each source's
particular JSON shape.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from opportunity_engine.domain.models import RawDocument


def parse_formd_hit(hit: dict[str, Any], fetched_at: datetime) -> RawDocument:
    source = hit["_source"]
    accession_no: str = source["adsh"]
    file_date: str = source["file_date"]  # 'YYYY-MM-DD'
    display_names = source.get("display_names") or []
    title = display_names[0] if display_names else accession_no
    sic_codes: list[str] = source.get("sics") or []
    ciks: list[str] = source.get("ciks") or []
    cik = ciks[0] if ciks else None

    content_hash = hashlib.sha256(
        f"{accession_no}\n{file_date}\n{','.join(sic_codes)}".encode()
    ).hexdigest()

    return RawDocument(
        connector_name="sec_edgar_formd",
        external_id=accession_no,
        doc_type="edgar_formd",
        fetched_at=fetched_at,
        published_at=datetime.strptime(file_date, "%Y-%m-%d").replace(tzinfo=UTC),
        source_url=(
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
            if cik
            else "https://www.sec.gov/edgar/search/"
        ),
        title=title,
        category=sic_codes[0] if sic_codes else None,
        content_hash=content_hash,
        raw_json=hit,
    )
