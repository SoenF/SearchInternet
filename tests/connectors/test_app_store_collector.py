from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opportunity_engine.clock import fixed_clock
from opportunity_engine.collectors.app_store import AppStoreCollector

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "app_store"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())  # type: ignore[no-any-return]


def _make_fetch(by_country: dict[str, dict[str, Any]]):
    def fake_fetch(url: str) -> dict[str, Any]:
        for country, response in by_country.items():
            if f"itunes.apple.com/{country}/" in url:
                return response
        raise AssertionError(f"unexpected URL in test: {url}")

    return fake_fetch


def test_collect_yields_ranked_documents_for_every_country_and_feed() -> None:
    by_country = {cc: _load(f"rss_top_free_{cc}.json") for cc in ("us", "jp", "kr", "br")}
    collector = AppStoreCollector(
        fetch=_make_fetch(by_country),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
        countries=("us", "jp", "kr", "br"),
        feeds=("topfreeapplications",),  # fixtures only cover the free chart
    )

    docs = list(
        collector.collect(datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 7, tzinfo=UTC))
    )

    expected_total = sum(len(r["feed"]["entry"]) for r in by_country.values())
    assert len(docs) == expected_total
    assert {d.country_code for d in docs} == {"us", "jp", "kr", "br"}
    assert all(d.doc_type == "app_store_ranking" for d in docs)

    us_docs = [d for d in docs if d.country_code == "us"]
    ranks = sorted(d.raw_json["rank"] for d in us_docs)
    assert ranks == list(range(1, len(us_docs) + 1))

    # published_at is stamped to the window's end date (snapshot semantics)
    assert all(d.published_at == datetime(2026, 8, 7, tzinfo=UTC) for d in docs)


def test_collect_skips_a_single_malformed_entry_without_raising() -> None:
    us_response = copy.deepcopy(_load("rss_top_free_us.json"))
    us_response["feed"]["entry"].append({"title": {"label": "missing required fields"}})
    collector = AppStoreCollector(
        fetch=_make_fetch({"us": us_response}),
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
        countries=("us",),
        feeds=("topfreeapplications",),
    )

    docs = list(
        collector.collect(datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 7, tzinfo=UTC))
    )

    assert len(docs) == len(us_response["feed"]["entry"]) - 1


def test_collect_continues_when_one_country_fails() -> None:
    us_response = _load("rss_top_free_us.json")

    def flaky_fetch(url: str) -> dict[str, Any]:
        if "/jp/" in url:
            raise RuntimeError("connection reset")
        return us_response

    collector = AppStoreCollector(
        fetch=flaky_fetch,
        clock=fixed_clock(datetime(2026, 8, 7, tzinfo=UTC)),
        countries=("us", "jp"),
        feeds=("topfreeapplications",),
    )

    docs = list(
        collector.collect(datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 7, tzinfo=UTC))
    )

    assert len(docs) == len(us_response["feed"]["entry"])
    assert all(d.country_code == "us" for d in docs)
