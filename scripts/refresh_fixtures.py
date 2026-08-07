#!/usr/bin/env python3
"""Manual, non-CI tool: pulls a fresh sample from each live data source and
diffs its top-level shape against the committed fixture.

Connector fixture tests (tests/connectors/) only catch *our own parser*
regressing against a known-good recorded shape -- they cannot detect the
live API changing shape out from under us. This script is the (manual,
human-in-the-loop) other half of that: it never modifies a fixture itself,
it just prints what changed so a human can decide whether to update the
fixture and the parser together.

Run occasionally, by hand:

    python scripts/refresh_fixtures.py

Never imported by the application, never run in CI, never run by pytest.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
USER_AGENT = "OpportunityEngine/0.1 (contact: davide@vamur.com) [fixture-refresh-script]"


def _fetch(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = httpx.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=15.0)
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def _diff_top_level_keys(fixture: dict[str, Any], live: dict[str, Any]) -> list[str]:
    differences = []
    fixture_keys, live_keys = set(fixture.keys()), set(live.keys())
    for key in sorted(fixture_keys - live_keys):
        differences.append(f"'{key}': present in committed fixture, missing in live response")
    for key in sorted(live_keys - fixture_keys):
        differences.append(f"'{key}': present in live response, missing in committed fixture")
    return differences


def _check(name: str, fixture_path: Path, fetch_live: Callable[[], dict[str, Any]]) -> None:
    print(f"--- {name} ---")
    if not fixture_path.exists():
        print(f"  no committed fixture at {fixture_path}, skipping")
        return
    fixture = json.loads(fixture_path.read_text())
    try:
        live = fetch_live()
    except Exception as exc:  # noqa: BLE001 -- one source failing must not stop the others
        print(f"  FAILED to fetch a live sample: {exc}")
        return
    differences = _diff_top_level_keys(fixture, live)
    if differences:
        print(f"  POSSIBLE DRIFT vs {fixture_path.relative_to(FIXTURES_DIR.parent.parent)}:")
        for difference in differences:
            print(f"    - {difference}")
    else:
        print("  top-level shape matches the committed fixture")


def main() -> int:
    _check(
        "Hacker News (Algolia)",
        FIXTURES_DIR / "hackernews" / "search_by_date_ask_hn.json",
        lambda: _fetch(
            "https://hn.algolia.com/api/v1/search_by_date",
            {"tags": "ask_hn", "hitsPerPage": 3},
        ),
    )
    _check(
        "SEC EDGAR Form D full-text search",
        FIXTURES_DIR / "edgar" / "formd_search_response.json",
        lambda: _fetch(
            "https://efts.sec.gov/LATEST/search-index",
            {"forms": "D", "startdt": "2026-01-01", "enddt": "2026-01-31"},
        ),
    )
    _check(
        "Wikipedia Pageviews",
        FIXTURES_DIR / "wikipedia" / "pageviews_response.json",
        lambda: _fetch(
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
            "en.wikipedia/all-access/user/ChatGPT/daily/20250101/20250103"
        ),
    )
    _check(
        "iTunes App Store RSS (US top-free)",
        FIXTURES_DIR / "app_store" / "rss_top_free_us.json",
        lambda: _fetch("https://itunes.apple.com/us/rss/topfreeapplications/limit=3/json"),
    )
    _check(
        "iTunes lookup",
        FIXTURES_DIR / "app_store" / "lookup_by_id.json",
        lambda: _fetch("https://itunes.apple.com/lookup", {"id": "6741796873", "country": "us"}),
    )

    print("\nReview any drift above by hand -- this script never edits fixtures itself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
