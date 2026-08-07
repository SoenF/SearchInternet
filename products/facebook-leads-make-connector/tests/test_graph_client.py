from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from leadbridge.graph_client import LeadRetrievalError, fetch_lead, validate_token_scopes

FIXTURES = Path(__file__).parent / "fixtures"
API_VERSION = "v21.0"
LEADGEN_ID = "1930628924301148"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@respx.mock
async def test_fetch_lead_returns_parsed_response_on_success() -> None:
    respx.get(f"https://graph.facebook.com/{API_VERSION}/{LEADGEN_ID}").mock(
        return_value=httpx.Response(200, json=_load("graph_lead_response_simple_form.json"))
    )
    lead = await fetch_lead(LEADGEN_ID, "fake-token", API_VERSION)
    assert lead.raw["id"] == LEADGEN_ID


@respx.mock
async def test_graphmethodexception_100_with_all_scopes_granted_gets_advertiser_role_hint() -> None:
    """Reproduces the exact real-world failure from the community thread this
    product is built from: every scope granted, retrieval still fails."""
    respx.get(f"https://graph.facebook.com/{API_VERSION}/{LEADGEN_ID}").mock(
        return_value=httpx.Response(400, json=_load("graph_error_graphmethodexception.json"))
    )
    respx.get(f"https://graph.facebook.com/{API_VERSION}/me/permissions").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"permission": "ads_management", "status": "granted"},
                    {"permission": "leads_retrieval", "status": "granted"},
                    {"permission": "pages_show_list", "status": "granted"},
                    {"permission": "pages_read_engagement", "status": "granted"},
                ]
            },
        )
    )
    with pytest.raises(LeadRetrievalError) as exc_info:
        await fetch_lead(LEADGEN_ID, "fake-token", API_VERSION)
    assert "advertiser role" in str(exc_info.value)


@respx.mock
async def test_graphmethodexception_100_with_missing_scope_names_it() -> None:
    respx.get(f"https://graph.facebook.com/{API_VERSION}/{LEADGEN_ID}").mock(
        return_value=httpx.Response(400, json=_load("graph_error_graphmethodexception.json"))
    )
    respx.get(f"https://graph.facebook.com/{API_VERSION}/me/permissions").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"permission": "ads_management", "status": "granted"},
                    {"permission": "pages_show_list", "status": "granted"},
                    {"permission": "pages_read_engagement", "status": "granted"},
                ]
            },
        )
    )
    with pytest.raises(LeadRetrievalError) as exc_info:
        await fetch_lead(LEADGEN_ID, "fake-token", API_VERSION)
    assert "leads_retrieval" in str(exc_info.value)


@respx.mock
async def test_validate_token_scopes_returns_empty_list_when_all_granted() -> None:
    respx.get(f"https://graph.facebook.com/{API_VERSION}/me/permissions").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"permission": s, "status": "granted"}
                    for s in (
                        "ads_management",
                        "leads_retrieval",
                        "pages_show_list",
                        "pages_read_engagement",
                    )
                ]
            },
        )
    )
    missing = await validate_token_scopes("fake-token", API_VERSION)
    assert missing == []


@respx.mock
async def test_non_100_graph_error_raises_with_the_original_message() -> None:
    respx.get(f"https://graph.facebook.com/{API_VERSION}/{LEADGEN_ID}").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "message": "Invalid OAuth access token.",
                    "type": "OAuthException",
                    "code": 190,
                }
            },
        )
    )
    with pytest.raises(LeadRetrievalError) as exc_info:
        await fetch_lead(LEADGEN_ID, "expired-token", API_VERSION)
    assert "Invalid OAuth access token" in str(exc_info.value)
