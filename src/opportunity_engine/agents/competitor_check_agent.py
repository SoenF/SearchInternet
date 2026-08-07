"""Single-responsibility service: for opportunities never checked before,
search GitHub repos + npm packages by title keywords and persist a
competitor-saturation signal (total match count + a handful of top matches).
Zero LLM, two free API calls per opportunity. Talks to other agents only
through the database and the events log, never directly.

Checked once per opportunity (`competitor_checked_at IS NULL` is the
worklist), not re-checked daily -- "does a competitor already exist"
doesn't change fast enough to justify repeated calls against a growing
backlog. Batched per run (`batch_size`) since GitHub's search endpoint is
rate-limited (30/min authenticated, 10/min not) and a large backlog's first
run would otherwise need far more calls than that limit allows in one go;
unchecked opportunities simply get picked up on a later run.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import psycopg

from opportunity_engine.clock import Clock, utc_now
from opportunity_engine.domain.enums import EventType
from opportunity_engine.events import append_event
from opportunity_engine.tools.competitor_search import (
    CompetitorMatch,
    build_search_query,
    parse_github_repo_search,
    parse_npm_search,
)
from opportunity_engine.tools.http import fetch_json
from opportunity_engine.tools.scoring_tools import COMPETITOR_SATURATION_WARNING_THRESHOLD

logger = logging.getLogger(__name__)

_GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
_NPM_SEARCH_URL = "https://registry.npmjs.org/-/v1/search"
_MATCHES_PER_SOURCE = 5

FetchFn = Callable[[str], dict[str, Any]]


def _default_github_fetch(client: httpx.Client, headers: dict[str, str]) -> FetchFn:
    return lambda query: fetch_json(
        client,
        _GITHUB_SEARCH_URL,
        params={"q": query, "per_page": _MATCHES_PER_SOURCE},
        headers=headers,
    )


def _default_npm_fetch(client: httpx.Client) -> FetchFn:
    return lambda query: fetch_json(
        client, _NPM_SEARCH_URL, params={"text": query, "size": _MATCHES_PER_SOURCE}
    )


@dataclass
class CompetitorCheckStats:
    checked: int = 0
    saturated: int = 0  # match_count exceeded the threshold used by the caller, for visibility only


def run_competitor_check(
    conn: psycopg.Connection[Any],
    *,
    github_token: str = "",
    batch_size: int = 50,
    saturation_threshold: int = COMPETITOR_SATURATION_WARNING_THRESHOLD,
    github_fetch: FetchFn | None = None,
    npm_fetch: FetchFn | None = None,
    clock: Clock = utc_now,
    client: httpx.Client | None = None,
) -> CompetitorCheckStats:
    stats = CompetitorCheckStats()
    if github_fetch is None or npm_fetch is None:
        owned_client = client or httpx.Client(timeout=10.0)
        if github_fetch is None:
            headers = {"Accept": "application/vnd.github+json"}
            if github_token:
                headers["Authorization"] = f"Bearer {github_token}"
            github_fetch = _default_github_fetch(owned_client, headers)
        if npm_fetch is None:
            npm_fetch = _default_npm_fetch(owned_client)

    rows = conn.execute(
        """
        SELECT id, title FROM opportunities
        WHERE competitor_checked_at IS NULL AND status IN ('candidate', 'qualified')
        ORDER BY current_score DESC NULLS LAST
        LIMIT %s
        """,
        (batch_size,),
    ).fetchall()

    for opportunity_id, title in rows:
        query = build_search_query(title)
        github_matches: list[CompetitorMatch] = []
        npm_matches: list[CompetitorMatch] = []
        github_total = 0
        npm_total = 0
        try:
            github_data = github_fetch(query)
            github_matches = parse_github_repo_search(github_data)
            github_total = int(github_data.get("total_count", 0))
        except Exception:
            logger.warning(
                "GitHub competitor search failed for opportunity %s", opportunity_id, exc_info=True
            )
        try:
            npm_data = npm_fetch(query)
            npm_matches = parse_npm_search(npm_data)
            npm_total = int(npm_data.get("total", 0))
        except Exception:
            logger.warning(
                "npm competitor search failed for opportunity %s", opportunity_id, exc_info=True
            )

        match_count = github_total + npm_total
        top_matches = [
            {"source": m.source, "name": m.name, "url": m.url, "popularity": m.popularity}
            for m in (*github_matches, *npm_matches)
        ]
        conn.execute(
            """
            UPDATE opportunities
            SET competitor_match_count = %s, competitor_matches = %s,
                competitor_checked_at = %s, updated_at = %s
            WHERE id = %s
            """,
            (match_count, json.dumps(top_matches), clock(), clock(), opportunity_id),
        )
        append_event(
            conn,
            EventType.COMPETITOR_CHECKED,
            opportunity_id=opportunity_id,
            payload={"match_count": match_count, "query": query},
        )
        conn.commit()
        stats.checked += 1
        if match_count > saturation_threshold:
            stats.saturated += 1

    return stats
