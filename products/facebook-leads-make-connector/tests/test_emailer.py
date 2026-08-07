from __future__ import annotations

import httpx
import pytest
import respx

from leadbridge.emailer import send_email


@respx.mock
async def test_send_email_posts_expected_payload_and_auth_header() -> None:
    route = respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(200, json={"id": "email_123"})
    )

    await send_email(
        "test_api_key",
        from_address="LeadBridge <noreply@example.com>",
        to_address="buyer@example.com",
        subject="Your download",
        html="<p>hi</p>",
    )

    assert route.called
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer test_api_key"
    import json

    body = json.loads(request.content)
    assert body["to"] == ["buyer@example.com"]
    assert body["subject"] == "Your download"


@respx.mock
async def test_send_email_raises_on_non_2xx_response() -> None:
    respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(401, json={"message": "invalid api key"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await send_email(
            "bad_key",
            from_address="a@example.com",
            to_address="b@example.com",
            subject="s",
            html="<p>h</p>",
        )
