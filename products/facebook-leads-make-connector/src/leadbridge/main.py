"""FastAPI app serving BOTH monetization paths off one deployment:

- Single-tenant (self-hosted buyer): Meta webhook -> Graph API retrieval ->
  normalize -> dedup -> forward to Make, using the global FB_PAGE_ACCESS_TOKEN
  / MAKE_WEBHOOK_URL env vars. Unchanged from the original single-buyer
  design.
- Multi-tenant (hosted subscription, run by whoever sells this): the same
  Meta webhook additionally checks tenants.py by page_id first, so several
  subscribers' leads can flow through one deployment without touching each
  other's config. Stripe webhooks provision/deprovision tenants and email
  either a source-code download link (one-time purchase) or a setup-form
  link (new subscription) via Resend.

See README.md for the problem this solves, docs/SETUP.md for how to
configure and deploy it, and docs/SETUP.md's Meta App Review note before
onboarding any subscriber whose Page you don't personally administer --
that's a real, non-optional gate on the multi-tenant path, not a code
problem.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Form, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse

from leadbridge.config import Settings
from leadbridge.dedup import DedupStore, file_store
from leadbridge.emailer import send_email
from leadbridge.forwarder import forward_to_make
from leadbridge.graph_client import LeadRetrievalError, fetch_lead
from leadbridge.normalizer import normalize_lead
from leadbridge.signature import verify_signature
from leadbridge.signing import sign_payload, verify_token
from leadbridge.stripe_webhook import verify_stripe_signature
from leadbridge.tenants import TenantStore
from leadbridge.tenants import file_store as tenants_file_store

logger = logging.getLogger("leadbridge")

app = FastAPI(title="LeadBridge for Make")
_settings: Settings | None = None
_dedup: DedupStore | None = None
_tenants: TenantStore | None = None


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


def _get_tenants() -> TenantStore:
    global _tenants
    if _tenants is None:
        _tenants = tenants_file_store(_get_settings().tenants_db_path)
    return _tenants


def _require_configured(value: str, env_var: str) -> str:
    if not value:
        raise HTTPException(status_code=503, detail=f"{env_var} is not configured")
    return value


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
    tenants = _get_tenants()
    processed = 0

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue
            value = change.get("value", {})
            leadgen_id = str(value.get("leadgen_id", ""))
            page_id = str(value.get("page_id", ""))
            if not leadgen_id or dedup.already_processed(leadgen_id):
                continue

            tenant = tenants.get_tenant(page_id) if page_id else None
            if tenant is not None:
                if tenant.status != "active":
                    logger.info("skipping lead for inactive tenant page_id=%s", page_id)
                    continue
                access_token = tenant.fb_page_access_token
                make_url = tenant.make_webhook_url
            else:
                access_token = settings.fb_page_access_token
                make_url = settings.make_webhook_url

            if not access_token or not make_url:
                logger.warning("no tenant or global config for page_id=%s, skipping", page_id)
                continue

            try:
                graph_lead = await fetch_lead(leadgen_id, access_token, settings.graph_api_version)
            except LeadRetrievalError:
                logger.exception("lead retrieval failed for leadgen_id=%s", leadgen_id)
                continue

            normalized = normalize_lead(graph_lead.raw)
            await forward_to_make(make_url, normalized)
            dedup.mark_processed(leadgen_id, datetime.now(UTC).isoformat())
            processed += 1

    return {"status": "ok", "processed": str(processed)}


@app.post("/stripe/webhook")
async def receive_stripe_webhook(
    request: Request, stripe_signature: str | None = Header(default=None, alias="Stripe-Signature")
) -> dict[str, str]:
    raw_body = await request.body()
    settings = _get_settings()
    _require_configured(settings.stripe_webhook_secret, "STRIPE_WEBHOOK_SECRET")
    now = datetime.now(UTC).timestamp()

    if not verify_stripe_signature(
        settings.stripe_webhook_secret, raw_body, stripe_signature, now=now
    ):
        raise HTTPException(status_code=400, detail="invalid signature")

    event: dict[str, Any] = await request.json()
    event_type = event.get("type", "")
    data_object: dict[str, Any] = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(settings, data_object)
    elif event_type == "customer.subscription.deleted":
        customer_id = str(data_object.get("customer", ""))
        if customer_id:
            _get_tenants().deactivate_by_customer_id(customer_id)
    else:
        logger.info("ignoring unhandled stripe event type=%s", event_type)

    return {"status": "ok"}


async def _handle_checkout_completed(settings: Settings, session: dict[str, Any]) -> None:
    _require_configured(settings.link_signing_secret, "LINK_SIGNING_SECRET")
    _require_configured(settings.resend_api_key, "RESEND_API_KEY")
    _require_configured(settings.email_from_address, "EMAIL_FROM_ADDRESS")
    _require_configured(settings.base_url, "BASE_URL")

    email = str(session.get("customer_details", {}).get("email", ""))
    if not email:
        logger.warning("checkout.session.completed with no customer email, skipping")
        return

    now = datetime.now(UTC).timestamp()
    expires_at = now + settings.link_expiry_hours * 3600
    base_url = settings.base_url.rstrip("/")

    if session.get("mode") == "payment":
        token = sign_payload(settings.link_signing_secret, {"kind": "download"}, expires_at)
        link = f"{base_url}/download?token={token}"
        html = (
            f"<p>Thanks for buying LeadBridge for Make.</p>"
            f"<p><a href='{link}'>Download the source code</a> "
            f"(link expires in {settings.link_expiry_hours}h).</p>"
            f"<p>Next step: follow docs/SETUP.md in the download.</p>"
        )
        subject = "Your LeadBridge download"
    elif session.get("mode") == "subscription":
        customer_id = str(session.get("customer", ""))
        token = sign_payload(
            settings.link_signing_secret,
            {"kind": "setup", "stripe_customer_id": customer_id},
            expires_at,
        )
        link = f"{base_url}/setup?token={token}"
        html = (
            f"<p>Thanks for subscribing to LeadBridge for Make.</p>"
            f"<p><a href='{link}'>Connect your Facebook Page</a> "
            f"(link expires in {settings.link_expiry_hours}h) and we'll start "
            f"forwarding your leads to Make.</p>"
        )
        subject = "Connect your Facebook Page to LeadBridge"
    else:
        return

    await send_email(
        settings.resend_api_key,
        from_address=settings.email_from_address,
        to_address=email,
        subject=subject,
        html=html,
    )


@app.get("/download")
async def download(token: str) -> FileResponse:
    settings = _get_settings()
    _require_configured(settings.link_signing_secret, "LINK_SIGNING_SECRET")
    now = datetime.now(UTC).timestamp()
    payload = verify_token(settings.link_signing_secret, token, now=now)
    if payload is None or payload.get("kind") != "download":
        raise HTTPException(status_code=403, detail="invalid or expired link")
    return FileResponse(settings.download_zip_path, filename="leadbridge-src.zip")


@app.get("/setup", response_class=HTMLResponse)
async def setup_form(token: str) -> str:
    settings = _get_settings()
    _require_configured(settings.link_signing_secret, "LINK_SIGNING_SECRET")
    now = datetime.now(UTC).timestamp()
    payload = verify_token(settings.link_signing_secret, token, now=now)
    if payload is None or payload.get("kind") != "setup":
        raise HTTPException(status_code=403, detail="invalid or expired link")

    return f"""
    <h1>Connect your Facebook Page</h1>
    <form method="post" action="/setup">
      <input type="hidden" name="token" value="{token}">
      <label>Facebook Page ID <input name="page_id" required></label><br>
      <label>Page Access Token <input name="fb_page_access_token" required></label><br>
      <label>Make Custom Webhook URL <input name="make_webhook_url" required></label><br>
      <button type="submit">Connect</button>
    </form>
    """


@app.post("/setup", response_class=HTMLResponse)
async def setup_submit(
    token: str = Form(...),
    page_id: str = Form(...),
    fb_page_access_token: str = Form(...),
    make_webhook_url: str = Form(...),
) -> str:
    settings = _get_settings()
    _require_configured(settings.link_signing_secret, "LINK_SIGNING_SECRET")
    now = datetime.now(UTC).timestamp()
    payload = verify_token(settings.link_signing_secret, token, now=now)
    if payload is None or payload.get("kind") != "setup":
        raise HTTPException(status_code=403, detail="invalid or expired link")

    _get_tenants().upsert_tenant(
        page_id=page_id,
        fb_page_access_token=fb_page_access_token,
        make_webhook_url=make_webhook_url,
        stripe_customer_id=str(payload.get("stripe_customer_id", "")),
        created_at=datetime.now(UTC).isoformat(),
    )
    return "<h1>Connected.</h1><p>Your leads will start forwarding to Make.</p>"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
