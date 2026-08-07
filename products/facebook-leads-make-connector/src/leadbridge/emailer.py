"""Sends transactional email via Resend's HTTP API
(https://resend.com/docs/api-reference/emails/send-email) -- one POST, no
SDK needed for a single call, consistent with the rest of this project."""

from __future__ import annotations

import httpx

_RESEND_URL = "https://api.resend.com/emails"


async def send_email(
    api_key: str, *, from_address: str, to_address: str, subject: str, html: str
) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            _RESEND_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"from": from_address, "to": [to_address], "subject": subject, "html": html},
        )
    response.raise_for_status()
