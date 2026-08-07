from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

import leadbridge.main as main_module
from leadbridge.dedup import in_memory_store

FIXTURES = Path(__file__).parent / "fixtures"
APP_SECRET = "test_app_secret"
VERIFY_TOKEN = "test_verify_token"
MAKE_URL = "https://hook.us1.make.com/fake-webhook-id"
API_VERSION = "v21.0"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("FB_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("FB_PAGE_ACCESS_TOKEN", "fake-page-token")
    monkeypatch.setenv("FB_WEBHOOK_VERIFY_TOKEN", VERIFY_TOKEN)
    monkeypatch.setenv("MAKE_WEBHOOK_URL", MAKE_URL)
    monkeypatch.setenv("GRAPH_API_VERSION", API_VERSION)
    # Reset module-level caches so each test gets fresh Settings/DedupStore
    # built from this test's env vars, not a previous test's.
    main_module._settings = None
    main_module._dedup = in_memory_store()
    return TestClient(main_module.app)


def test_webhook_verification_handshake_echoes_challenge(client: TestClient) -> None:
    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "12345",
        },
    )
    assert response.status_code == 200
    assert response.text == "12345"


def test_webhook_verification_rejects_wrong_token(client: TestClient) -> None:
    response = client.get(
        "/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "12345"},
    )
    assert response.status_code == 403


def test_post_without_valid_signature_is_rejected(client: TestClient) -> None:
    body = _load("webhook_leadgen_notification.json")
    response = client.post(
        "/webhook", json=body, headers={"x-hub-signature-256": "sha256=deadbeef"}
    )
    assert response.status_code == 403


@respx.mock
def test_valid_lead_notification_is_retrieved_normalized_and_forwarded(client: TestClient) -> None:
    respx.get(f"https://graph.facebook.com/{API_VERSION}/1930628924301148").mock(
        return_value=httpx.Response(200, json=_load("graph_lead_response_simple_form.json"))
    )
    make_route = respx.post(MAKE_URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    body_bytes = json.dumps(_load("webhook_leadgen_notification.json")).encode()
    response = client.post(
        "/webhook",
        content=body_bytes,
        headers={"content-type": "application/json", "x-hub-signature-256": _sign(body_bytes)},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "processed": "1"}
    assert make_route.called
    forwarded_payload = json.loads(make_route.calls[0].request.content)
    assert forwarded_payload["fields"]["email"] == "lee@example.com"


@respx.mock
def test_redelivered_notification_is_not_forwarded_twice(client: TestClient) -> None:
    respx.get(f"https://graph.facebook.com/{API_VERSION}/1930628924301148").mock(
        return_value=httpx.Response(200, json=_load("graph_lead_response_simple_form.json"))
    )
    make_route = respx.post(MAKE_URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    body_bytes = json.dumps(_load("webhook_leadgen_notification.json")).encode()
    headers = {"content-type": "application/json", "x-hub-signature-256": _sign(body_bytes)}

    first = client.post("/webhook", content=body_bytes, headers=headers)
    second = client.post("/webhook", content=body_bytes, headers=headers)

    assert first.json() == {"status": "ok", "processed": "1"}
    assert second.json() == {"status": "ok", "processed": "0"}
    assert make_route.call_count == 1


@respx.mock
def test_lead_retrieval_failure_is_logged_and_skipped_not_a_500(client: TestClient) -> None:
    """A GraphMethodException on one lead in a batch must not take down the
    whole webhook delivery -- Facebook interprets a 5xx as "retry me," which
    would just repeat the same failure forever."""
    respx.get(f"https://graph.facebook.com/{API_VERSION}/1930628924301148").mock(
        return_value=httpx.Response(400, json=_load("graph_error_graphmethodexception.json"))
    )
    respx.get(f"https://graph.facebook.com/{API_VERSION}/me/permissions").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    body_bytes = json.dumps(_load("webhook_leadgen_notification.json")).encode()
    response = client.post(
        "/webhook",
        content=body_bytes,
        headers={"content-type": "application/json", "x-hub-signature-256": _sign(body_bytes)},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "processed": "0"}
