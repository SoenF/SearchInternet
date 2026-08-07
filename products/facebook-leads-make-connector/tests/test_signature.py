from __future__ import annotations

import hashlib
import hmac

from leadbridge.signature import verify_signature

SECRET = "test_app_secret"
BODY = b'{"object":"page","entry":[]}'


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_is_accepted() -> None:
    assert verify_signature(SECRET, BODY, _sign(SECRET, BODY)) is True


def test_wrong_secret_is_rejected() -> None:
    assert verify_signature(SECRET, BODY, _sign("wrong_secret", BODY)) is False


def test_tampered_body_is_rejected() -> None:
    signature = _sign(SECRET, BODY)
    assert (
        verify_signature(SECRET, b'{"object":"page","entry":[{"tampered":true}]}', signature)
        is False
    )


def test_missing_header_is_rejected() -> None:
    assert verify_signature(SECRET, BODY, None) is False


def test_header_without_sha256_prefix_is_rejected() -> None:
    assert verify_signature(SECRET, BODY, "md5=deadbeef") is False
