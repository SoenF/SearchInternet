from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import leadbridge.main as main_module
from leadbridge.dedup import in_memory_store as dedup_in_memory_store
from leadbridge.signing import sign_payload
from leadbridge.tenants import in_memory_store as tenants_in_memory_store

LINK_SECRET = "test_link_secret"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("FB_APP_SECRET", "test_app_secret")
    monkeypatch.setenv("FB_WEBHOOK_VERIFY_TOKEN", "test_verify_token")
    monkeypatch.setenv("LINK_SIGNING_SECRET", LINK_SECRET)

    zip_path = tmp_path / "leadbridge-src.zip"
    zip_path.write_bytes(b"fake zip contents")
    monkeypatch.setenv("DOWNLOAD_ZIP_PATH", str(zip_path))

    main_module._settings = None
    main_module._dedup = dedup_in_memory_store()
    main_module._tenants = tenants_in_memory_store()
    return TestClient(main_module.app)


def _future_token(kind: str, extra: dict | None = None) -> str:
    payload = {"kind": kind, **(extra or {})}
    return sign_payload(LINK_SECRET, payload, expires_at=9_999_999_999.0)


def test_download_with_a_valid_token_returns_the_zip(client: TestClient) -> None:
    token = _future_token("download")
    response = client.get("/download", params={"token": token})
    assert response.status_code == 200
    assert response.content == b"fake zip contents"


def test_download_with_an_expired_token_is_rejected(client: TestClient) -> None:
    token = sign_payload(LINK_SECRET, {"kind": "download"}, expires_at=1.0)
    response = client.get("/download", params={"token": token})
    assert response.status_code == 403


def test_download_with_a_setup_token_is_rejected(client: TestClient) -> None:
    """A setup link must not double as a download link -- each token's
    `kind` scopes it to exactly one route."""
    token = _future_token("setup", {"stripe_customer_id": "cus_1"})
    response = client.get("/download", params={"token": token})
    assert response.status_code == 403


def test_setup_form_with_valid_token_is_served(client: TestClient) -> None:
    token = _future_token("setup", {"stripe_customer_id": "cus_1"})
    response = client.get("/setup", params={"token": token})
    assert response.status_code == 200
    assert "Connect your Facebook Page" in response.text


def test_setup_form_with_a_download_token_is_rejected(client: TestClient) -> None:
    token = _future_token("download")
    response = client.get("/setup", params={"token": token})
    assert response.status_code == 403


def test_setup_submit_creates_an_active_tenant_with_the_tokens_customer_id(
    client: TestClient,
) -> None:
    token = _future_token("setup", {"stripe_customer_id": "cus_42"})
    response = client.post(
        "/setup",
        data={
            "token": token,
            "page_id": "page42",
            "fb_page_access_token": "fb-token-42",
            "make_webhook_url": "https://hook.example/42",
        },
    )
    assert response.status_code == 200

    tenant = main_module._tenants.get_tenant("page42")
    assert tenant is not None
    assert tenant.fb_page_access_token == "fb-token-42"
    assert tenant.stripe_customer_id == "cus_42"
    assert tenant.status == "active"


def test_setup_submit_with_expired_token_does_not_create_a_tenant(client: TestClient) -> None:
    token = sign_payload(
        LINK_SECRET, {"kind": "setup", "stripe_customer_id": "cus_1"}, expires_at=1.0
    )
    response = client.post(
        "/setup",
        data={
            "token": token,
            "page_id": "page1",
            "fb_page_access_token": "fb-token",
            "make_webhook_url": "https://hook.example/1",
        },
    )
    assert response.status_code == 403
    assert main_module._tenants.get_tenant("page1") is None
