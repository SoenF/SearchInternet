from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opportunity_engine.clock import fixed_clock
from opportunity_engine.collectors.edgar import EdgarFormDCollector

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "edgar"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())  # type: ignore[no-any-return]


def _make_fetch(response: dict[str, Any]):
    def fake_fetch(url: str, params: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        assert headers["User-Agent"]  # SEC fair-access policy requires this
        if params["from"] > 0:
            return {"hits": {"total": {"value": 0}, "hits": []}}
        return response

    return fake_fetch


def test_collect_yields_formd_documents() -> None:
    response = _load("formd_search_response.json")
    collector = EdgarFormDCollector(
        user_agent="OpportunityEngine/0.1 (contact: davide@vamur.com)",
        fetch=_make_fetch(response),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 31, tzinfo=UTC))
    )

    assert len(docs) == len(response["hits"]["hits"])
    assert all(d.doc_type == "edgar_formd" for d in docs)
    assert all(d.connector_name == "sec_edgar_formd" for d in docs)

    bank_docs = [d for d in docs if d.category in {"6021", "6022"}]
    assert bank_docs, "expected at least one SIC-classified bank filing in the fixture"

    unclassified_docs = [d for d in docs if d.category is None]
    assert unclassified_docs, "expected at least one filer with no SIC on file (the common case)"


def test_collect_skips_a_single_malformed_hit_without_raising() -> None:
    response = copy.deepcopy(_load("formd_search_response.json"))
    response["hits"]["hits"].append({"_source": {"file_date": "2026-07-01"}})  # missing "adsh"
    collector = EdgarFormDCollector(
        user_agent="OpportunityEngine/0.1 (contact: davide@vamur.com)",
        fetch=_make_fetch(response),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
    )

    docs = list(
        collector.collect(datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 31, tzinfo=UTC))
    )

    assert len(docs) == len(response["hits"]["hits"]) - 1
