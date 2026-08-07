from __future__ import annotations

import hashlib
import hmac

from leadbridge.stripe_webhook import verify_stripe_signature

SECRET = "whsec_test_secret"
BODY = b'{"id":"evt_123","type":"checkout.session.completed"}'


def _header(secret: str, timestamp: int, body: bytes, extra_v0: bool = False) -> str:
    signed_payload = f"{timestamp}.".encode() + body
    v1 = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    header = f"t={timestamp},v1={v1}"
    if extra_v0:
        header += ",v0=deliberately_fake_for_testing"
    return header


def test_valid_signature_within_tolerance_is_accepted() -> None:
    header = _header(SECRET, 1000, BODY)
    assert verify_stripe_signature(SECRET, BODY, header, now=1000.0) is True


def test_valid_signature_with_a_v0_scheme_present_is_still_accepted() -> None:
    """Stripe always includes a fake v0 signature for test events -- must be
    ignored, not treated as a valid scheme (downgrade-attack protection)."""
    header = _header(SECRET, 1000, BODY, extra_v0=True)
    assert verify_stripe_signature(SECRET, BODY, header, now=1000.0) is True


def test_wrong_secret_is_rejected() -> None:
    header = _header("wrong_secret", 1000, BODY)
    assert verify_stripe_signature(SECRET, BODY, header, now=1000.0) is False


def test_tampered_body_is_rejected() -> None:
    header = _header(SECRET, 1000, BODY)
    assert verify_stripe_signature(SECRET, b'{"tampered":true}', header, now=1000.0) is False


def test_timestamp_outside_tolerance_is_rejected_as_a_replay() -> None:
    header = _header(SECRET, 1000, BODY)
    assert (
        verify_stripe_signature(SECRET, BODY, header, now=1000.0 + 400, tolerance_seconds=300)
        is False
    )


def test_missing_header_is_rejected() -> None:
    assert verify_stripe_signature(SECRET, BODY, None, now=1000.0) is False


def test_header_missing_v1_field_is_rejected() -> None:
    assert verify_stripe_signature(SECRET, BODY, "t=1000", now=1000.0) is False
