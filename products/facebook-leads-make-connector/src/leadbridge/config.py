"""Settings from os.environ, built once and passed explicitly -- same pattern
as opportunity_engine/config.py in this repo, no hidden globals."""

from __future__ import annotations

import os
from dataclasses import dataclass

# Pinned, not left to Facebook's default -- a floating "latest" version is
# exactly how the multi-form mapping and token-scope behavior silently drifts
# out from under a working integration. Bump deliberately, re-test against
# tests/fixtures/ before shipping the bump.
GRAPH_API_VERSION = "v21.0"


@dataclass(frozen=True)
class Settings:
    fb_app_secret: str
    fb_page_access_token: str
    fb_webhook_verify_token: str
    make_webhook_url: str
    dedup_db_path: str = "leadbridge_dedup.sqlite3"
    graph_api_version: str = GRAPH_API_VERSION

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            fb_app_secret=_require("FB_APP_SECRET"),
            fb_page_access_token=_require("FB_PAGE_ACCESS_TOKEN"),
            fb_webhook_verify_token=_require("FB_WEBHOOK_VERIFY_TOKEN"),
            make_webhook_url=_require("MAKE_WEBHOOK_URL"),
            dedup_db_path=os.environ.get("DEDUP_DB_PATH", cls.dedup_db_path),
            graph_api_version=os.environ.get("GRAPH_API_VERSION", GRAPH_API_VERSION),
        )


def _require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"missing required environment variable: {key}")
    return value
