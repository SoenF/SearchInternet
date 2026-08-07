"""Shared HTTP-fetch tool used by all four collectors.

One retry/backoff policy in one place beats four hand-rolled loops -- the
external APIs are free public services that will occasionally rate-limit or
blip, not services this project controls.
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=8),
    retry=retry_if_exception(_is_retryable),
)
def fetch_json(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = client.get(url, params=params, headers=headers)
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=8),
    retry=retry_if_exception(_is_retryable),
)
def post_json(
    client: httpx.Client,
    url: str,
    *,
    json_body: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Shared with fetch_json's retry policy -- used by GraphQL sources
    (Product Hunt v2), which take their query/variables as a POST body."""
    response = client.post(url, json=json_body, headers=headers)
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result
