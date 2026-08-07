from __future__ import annotations

from leadbridge.signing import sign_payload, verify_token

SECRET = "test_link_secret"


def test_valid_unexpired_token_returns_its_payload() -> None:
    token = sign_payload(SECRET, {"kind": "download"}, expires_at=1000.0)
    assert verify_token(SECRET, token, now=500.0) == {"kind": "download"}


def test_expired_token_is_rejected() -> None:
    token = sign_payload(SECRET, {"kind": "download"}, expires_at=1000.0)
    assert verify_token(SECRET, token, now=1000.1) is None


def test_token_signed_with_a_different_secret_is_rejected() -> None:
    token = sign_payload(SECRET, {"kind": "download"}, expires_at=1000.0)
    assert verify_token("wrong_secret", token, now=500.0) is None


def test_tampered_token_is_rejected() -> None:
    token = sign_payload(SECRET, {"kind": "download"}, expires_at=1000.0)
    encoded, signature = token.rsplit(".", 1)
    tampered = encoded + "x." + signature
    assert verify_token(SECRET, tampered, now=500.0) is None


def test_malformed_token_without_a_separator_is_rejected() -> None:
    assert verify_token(SECRET, "not-a-real-token", now=500.0) is None


def test_setup_token_carries_the_stripe_customer_id() -> None:
    token = sign_payload(
        SECRET, {"kind": "setup", "stripe_customer_id": "cus_123"}, expires_at=1000.0
    )
    payload = verify_token(SECRET, token, now=500.0)
    assert payload is not None
    assert payload["stripe_customer_id"] == "cus_123"
