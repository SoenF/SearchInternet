"""Forwards one normalized lead payload to a single Make.com Custom Webhook
trigger. This is deliberately the only integration point with Make -- once
the payload here is a flat, predictable JSON object, the downstream Make
scenario needs only static field mapping (see docs/make_blueprint_spec.md),
which is the whole point: push the variability into this service, where it's
tested, instead of into N fragile per-form Make scenarios."""

from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from leadbridge.normalizer import NormalizedLead


@retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def forward_to_make(make_webhook_url: str, lead: NormalizedLead) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(make_webhook_url, json=lead.to_payload())
    response.raise_for_status()
