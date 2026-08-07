from __future__ import annotations

import json
from pathlib import Path

from leadbridge.normalizer import normalize_lead

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_simple_form_maps_standard_fields_exactly() -> None:
    lead = normalize_lead(_load("graph_lead_response_simple_form.json"))
    assert lead.fields == {
        "full_name": "Lee Wilson",
        "email": "lee@example.com",
        "phone_number": "+447700900123",
    }
    assert lead.custom_fields == {}
    assert lead.leadgen_id == "1930628924301148"
    assert lead.form_id == "998877665544"


def test_different_form_on_same_page_still_normalizes_to_the_same_schema() -> None:
    """The core bug this product fixes: two different Instant Forms on one
    Page produce structurally different field_data, but both must resolve to
    the same canonical `fields` keys so one downstream Make scenario works
    for both without per-form scenario duplication."""
    lead = normalize_lead(_load("graph_lead_response_alt_field_names.json"))
    assert lead.fields["first_name"] == "Monica"
    assert lead.fields["last_name"] == "Cacciani"
    assert lead.fields["email"] == "monica@arealifting.example"
    assert lead.fields["company_name"] == "AreaLifting Gym"


def test_unrecognized_custom_question_is_kept_not_dropped() -> None:
    """The failure mode this must avoid: Make's static mapping silently drops
    fields it wasn't configured for. A budget question with no canonical
    bucket must still survive, just in custom_fields."""
    lead = normalize_lead(_load("graph_lead_response_alt_field_names.json"))
    assert lead.custom_fields == {"what_s_your_monthly_training_budget_": "500-1000"}


def test_first_canonical_match_wins_when_two_fields_could_map_to_the_same_bucket() -> None:
    graph_response = {
        "id": "1",
        "form_id": "1",
        "ad_id": None,
        "created_time": None,
        "field_data": [
            {"name": "email", "values": ["primary@example.com"]},
            {"name": "backup_email_address", "values": ["backup@example.com"]},
        ],
    }
    lead = normalize_lead(graph_response)
    assert lead.fields["email"] == "primary@example.com"
    assert lead.custom_fields == {}  # backup_email_address also buckets to email, doesn't leak


def test_empty_values_list_normalizes_to_empty_string_not_a_crash() -> None:
    graph_response = {
        "id": "1",
        "form_id": "1",
        "ad_id": None,
        "created_time": None,
        "field_data": [{"name": "email", "values": []}],
    }
    lead = normalize_lead(graph_response)
    assert lead.fields["email"] == ""


def test_to_payload_produces_a_flat_json_serializable_dict() -> None:
    lead = normalize_lead(_load("graph_lead_response_simple_form.json"))
    payload = lead.to_payload()
    assert json.dumps(payload)  # must not raise
    assert payload["leadgen_id"] == "1930628924301148"
