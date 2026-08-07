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

DEFAULT_LINK_EXPIRY_HOURS = 72


@dataclass(frozen=True)
class Settings:
    fb_app_secret: str
    fb_webhook_verify_token: str
    dedup_db_path: str = "leadbridge_dedup.sqlite3"
    graph_api_version: str = GRAPH_API_VERSION

    # Single-tenant fallback: set by a buyer who bought the source and
    # self-hosts for their own one Facebook Page. Optional (not required)
    # because a deployment running ONLY the hosted-subscription side has no
    # single Page of its own -- every lead it receives resolves through
    # tenants.py instead. See main.py's webhook handler for the fallback
    # order: tenant record by page_id first, these two second.
    fb_page_access_token: str = ""
    make_webhook_url: str = ""

    # Multi-tenant hosted subscription side -- all optional because a
    # deployment running ONLY the single-tenant self-hosted side (the
    # one-time buyer's own copy) never touches Stripe or email at all.
    stripe_webhook_secret: str = ""
    resend_api_key: str = ""
    email_from_address: str = ""
    link_signing_secret: str = ""
    base_url: str = ""
    tenants_db_path: str = "leadbridge_tenants.sqlite3"
    download_zip_path: str = "dist/leadbridge-src.zip"
    link_expiry_hours: int = DEFAULT_LINK_EXPIRY_HOURS

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            fb_app_secret=_require("FB_APP_SECRET"),
            fb_webhook_verify_token=_require("FB_WEBHOOK_VERIFY_TOKEN"),
            dedup_db_path=os.environ.get("DEDUP_DB_PATH", cls.dedup_db_path),
            graph_api_version=os.environ.get("GRAPH_API_VERSION", GRAPH_API_VERSION),
            fb_page_access_token=os.environ.get("FB_PAGE_ACCESS_TOKEN", ""),
            make_webhook_url=os.environ.get("MAKE_WEBHOOK_URL", ""),
            stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
            resend_api_key=os.environ.get("RESEND_API_KEY", ""),
            email_from_address=os.environ.get("EMAIL_FROM_ADDRESS", ""),
            link_signing_secret=os.environ.get("LINK_SIGNING_SECRET", ""),
            base_url=os.environ.get("BASE_URL", ""),
            tenants_db_path=os.environ.get("TENANTS_DB_PATH", cls.tenants_db_path),
            download_zip_path=os.environ.get("DOWNLOAD_ZIP_PATH", cls.download_zip_path),
            link_expiry_hours=int(os.environ.get("LINK_EXPIRY_HOURS", DEFAULT_LINK_EXPIRY_HOURS)),
        )


def _require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"missing required environment variable: {key}")
    return value
