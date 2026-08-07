"""Short-lived, HMAC-signed tokens for the two links this service emails out
(the one-time buyer's download link, the subscriber's setup-form link).
Distinct from signature.py (which verifies an INBOUND webhook against a
header Meta/Stripe computed) -- this generates and verifies OUR OWN outbound
tokens, so it carries an expiry and an arbitrary payload dict instead."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any


def sign_payload(secret: str, payload: dict[str, Any], expires_at: float) -> str:
    body = {"payload": payload, "expires_at": expires_at}
    encoded = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), encoded, hashlib.sha256).hexdigest()
    return f"{encoded.decode('ascii')}.{signature}"


def verify_token(secret: str, token: str, *, now: float) -> dict[str, Any] | None:
    try:
        encoded_str, signature = token.rsplit(".", 1)
    except ValueError:
        return None

    encoded = encoded_str.encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), encoded, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None

    try:
        body = json.loads(base64.urlsafe_b64decode(encoded))
    except (ValueError, json.JSONDecodeError):
        return None

    if now > body.get("expires_at", 0):
        return None

    payload = body.get("payload")
    return payload if isinstance(payload, dict) else None
