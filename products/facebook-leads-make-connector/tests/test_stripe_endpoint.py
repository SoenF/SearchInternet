from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

import leadbridge.main as main_module
from leadbridge.dedup import in_memory_store as dedup_in_memory_store
from leadbridge.tenants import in_memory_store as tenants_in_memory_store

FIXTURES = Path(__file__).parent / "fixtures"
STRIPE_SECRET = "whsec_test_secret"
LINK_SECRET = "test_link_secret"
BASE_URL = "https://leadbridge.example.com"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _stripe_header(body: bytes, timestamp: int | None = None) -> str:
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.".encode() + body
    v1 = hmac.new(STRIPE_SECRET.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("FB_APP_SECRET", "test_app_secret")
    monkeypatch.setenv("FB_WEBHOOK_VERIFY_TOKEN", "test_verify_token")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", STRIPE_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "test_resend_key")
    monkeypatch.setenv("EMAIL_FROM_ADDRESS", "LeadBridge <noreply@example.com>")
    monkeypatch.setenv("LINK_SIGNING_SECRET", LINK_SECRET)
    monkeypatch.setenv("BASE_URL", BASE_URL)
    main_module._settings = None
    main_module._dedup = dedup_in_memory_store()
    main_module._tenants = tenants_in_memory_store()
    return TestClient(main_module.app)


def test_webhook_rejects_missing_signature(client: TestClient) -> None:
    body_bytes = json.dumps(_load("stripe_checkout_completed_payment.json")).encode()
    response = client.post("/stripe/webhook", content=body_bytes)
    assert response.status_code == 400


def test_webhook_rejects_wrong_signature(client: TestClient) -> None:
    body_bytes = json.dumps(_load("stripe_checkout_completed_payment.json")).encode()
    response = client.post(
        "/stripe/webhook", content=body_bytes, headers={"Stripe-Signature": "t=1,v1=deadbeef"}
    )
    assert response.status_code == 400


@respx.mock
def test_one_time_payment_emails_a_download_link(client: TestClient) -> None:
    email_route = respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(200, json={"id": "email_1"})
    )
    body_bytes = json.dumps(_load("stripe_checkout_completed_payment.json")).encode()

    response = client.post(
        "/stripe/webhook",
        content=body_bytes,
        headers={"Stripe-Signature": _stripe_header(body_bytes)},
    )

    assert response.status_code == 200
    assert email_route.called
    sent = json.loads(email_route.calls[0].request.content)
    assert sent["to"] == ["buyer@example.com"]
    assert f"{BASE_URL}/download?token=" in sent["html"]


@respx.mock
def test_subscription_checkout_emails_a_setup_link(client: TestClient) -> None:
    email_route = respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(200, json={"id": "email_2"})
    )
    body_bytes = json.dumps(_load("stripe_checkout_completed_subscription.json")).encode()

    response = client.post(
        "/stripe/webhook",
        content=body_bytes,
        headers={"Stripe-Signature": _stripe_header(body_bytes)},
    )

    assert response.status_code == 200
    assert email_route.called
    sent = json.loads(email_route.calls[0].request.content)
    assert sent["to"] == ["subscriber@example.com"]
    assert f"{BASE_URL}/setup?token=" in sent["html"]


def test_subscription_deleted_deactivates_the_matching_tenant(client: TestClient) -> None:
    main_module._tenants.upsert_tenant(
        page_id="page1",
        fb_page_access_token="token1",
        make_webhook_url="https://hook.example/1",
        stripe_customer_id="cus_subscriber123",
        created_at="2026-08-07T00:00:00Z",
    )
    body_bytes = json.dumps(_load("stripe_subscription_deleted.json")).encode()

    response = client.post(
        "/stripe/webhook",
        content=body_bytes,
        headers={"Stripe-Signature": _stripe_header(body_bytes)},
    )

    assert response.status_code == 200
    tenant = main_module._tenants.get_tenant("page1")
    assert tenant is not None
    assert tenant.status == "inactive"


def test_unhandled_event_type_is_acknowledged_without_error(client: TestClient) -> None:
    body = {"id": "evt_x", "object": "event", "type": "invoice.paid", "data": {"object": {}}}
    body_bytes = json.dumps(body).encode()
    response = client.post(
        "/stripe/webhook",
        content=body_bytes,
        headers={"Stripe-Signature": _stripe_header(body_bytes)},
    )
    assert response.status_code == 200
