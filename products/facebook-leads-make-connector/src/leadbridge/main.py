"""FastAPI app: Meta webhook verification handshake (GET) + leadgen
notification receiver (POST) -> Graph API retrieval -> normalize -> dedup ->
forward to Make. See README.md for the problem this solves and
docs/SETUP.md for how to configure and deploy it."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response

from leadbridge.config import Settings
from leadbridge.dedup import DedupStore, file_store
from leadbridge.forwarder import forward_to_make
from leadbridge.graph_client import LeadRetrievalError, fetch_lead
from leadbridge.normalizer import normalize_lead
from leadbridge.signature import verify_signature

logger = logging.getLogger("leadbridge")

app = FastAPI(title="LeadBridge for Make")
_settings: Settings | None = None
_dedup: DedupStore | None = None


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def _get_dedup() -> DedupStore:
    global _dedup
    if _dedup is None:
        _dedup = file_store(_get_settings().dedup_db_path)
    return _dedup


@app.get("/webhook")
async def verify_webhook(request: Request) -> Response:
    """Meta's subscription handshake: GET with hub.mode/hub.verify_token/
    hub.challenge as query params (not headers) -- respond with the raw
    challenge string if the verify token matches."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")
    if mode == "subscribe" and token == _get_settings().fb_webhook_verify_token:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="verify token mismatch")


@app.post("/webhook")
async def receive_webhook(
    request: Request, x_hub_signature_256: str | None = Header(default=None)
) -> dict[str, str]:
    raw_body = await request.body()
    settings = _get_settings()

    if not verify_signature(settings.fb_app_secret, raw_body, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="invalid signature")

    payload: dict[str, Any] = await request.json()
    dedup = _get_dedup()
    processed = 0

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue
            leadgen_id = str(change.get("value", {}).get("leadgen_id", ""))
            if not leadgen_id or dedup.already_processed(leadgen_id):
                continue

            try:
                graph_lead = await fetch_lead(
                    leadgen_id, settings.fb_page_access_token, settings.graph_api_version
                )
            except LeadRetrievalError:
                logger.exception("lead retrieval failed for leadgen_id=%s", leadgen_id)
                continue

            normalized = normalize_lead(graph_lead.raw)
            await forward_to_make(settings.make_webhook_url, normalized)
            dedup.mark_processed(leadgen_id, datetime.now(UTC).isoformat())
            processed += 1

    return {"status": "ok", "processed": str(processed)}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
