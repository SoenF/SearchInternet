"""Verifies Stripe's `Stripe-Signature` header manually (no `stripe` SDK
dependency, consistent with the rest of this project's minimal-dependency
approach). Format: `t=<unix_ts>,v1=<hex_hmac>[,v0=<fake, ignore>]`; the
signed string is `f"{timestamp}.{raw_body}"`, HMAC-SHA256 keyed by the
webhook endpoint secret. A timestamp tolerance guards against replaying an
intercepted, still-validly-signed payload later."""

from __future__ import annotations

import hashlib
import hmac

_DEFAULT_TOLERANCE_SECONDS = 300


def verify_stripe_signature(
    secret: str,
    raw_body: bytes,
    header_value: str | None,
    *,
    now: float,
    tolerance_seconds: int = _DEFAULT_TOLERANCE_SECONDS,
) -> bool:
    if not header_value:
        return False

    timestamp: str | None = None
    v1_signatures: list[str] = []
    for item in header_value.split(","):
        if "=" not in item:
            continue
        key, _, value = item.partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            v1_signatures.append(value)

    if timestamp is None or not v1_signatures:
        return False

    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(now - ts) > tolerance_seconds:
        return False

    signed_payload = f"{timestamp}.".encode() + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, sig) for sig in v1_signatures)
