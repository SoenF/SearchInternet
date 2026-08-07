"""Verifies Meta's `X-Hub-Signature-256` header (HMAC-SHA256 over the raw
request body, keyed by the Facebook App Secret) -- the standard Meta webhook
signing scheme, unchanged since Graph API webhooks were introduced. Without
this, anyone who finds the webhook URL could POST fabricated leads."""

from __future__ import annotations

import hashlib
import hmac

_PREFIX = "sha256="


def verify_signature(app_secret: str, raw_body: bytes, header_value: str | None) -> bool:
    if not header_value or not header_value.startswith(_PREFIX):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = header_value[len(_PREFIX) :]
    return hmac.compare_digest(expected, provided)
