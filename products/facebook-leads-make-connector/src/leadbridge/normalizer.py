"""Normalizes a lead's `field_data` (Graph API shape: a list of {name, values}
pairs) into one predictable schema, regardless of which Instant Form on the
Page it came from.

Why this is needed at all: Facebook's *standard* lead-form fields (full_name,
email, phone_number, ...) use a stable internal `name` no matter what label
text the form shows the lead -- but *custom* questions get a slugified version
of the actual question text as their `name` (e.g. "what_s_your_monthly_budget"),
which is different on every form. A Page with several Instant Forms therefore
produces structurally different payloads per form. Make's native module maps
fields statically per scenario, so it either needs one scenario per form or
silently drops whatever it wasn't mapped for -- this is the exact failure in
the "Facebook instant form integration to Outlook" community thread this
product is built from (see docs/root_cause_notes.md).

Approach: exact-match Facebook's known standard field names first (these are
certain, not guesses), then keyword-substring match anything else against a
small canonical bucket list. Anything still unmatched goes into
`custom_fields` rather than being dropped -- the whole point is "stop losing
data silently."
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Facebook's documented standard lead-form field names -- these are exact,
# stable internal keys (https://developers.facebook.com/docs/marketing-api/guides/lead-ads/standard-fields),
# not something inferred from question text.
_STANDARD_FIELD_MAP: dict[str, str] = {
    "full_name": "full_name",
    "first_name": "first_name",
    "last_name": "last_name",
    "email": "email",
    "work_email": "email",
    "phone_number": "phone_number",
    "work_phone_number": "phone_number",
    "company_name": "company_name",
    "job_title": "job_title",
    "city": "city",
    "state": "state",
    "country": "country",
    "zip_code": "zip_code",
    "street_address": "street_address",
}

# Fallback keyword buckets for custom questions, whose `name` is a slugified
# version of the on-form question text and therefore varies per form. Ordered
# most-specific first since matching stops at the first hit.
_KEYWORD_BUCKETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("email", ("email", "e_mail")),
    ("phone_number", ("phone", "mobile", "whatsapp", "tel_")),
    ("full_name", ("full_name", "your_name", "contact_name")),
    ("first_name", ("first_name",)),
    ("last_name", ("last_name", "surname")),
    ("company_name", ("company", "business_name", "organi")),
    ("job_title", ("job_title", "role", "position")),
    ("city", ("city", "town")),
    ("zip_code", ("zip", "postal")),
)


@dataclass(frozen=True)
class NormalizedLead:
    leadgen_id: str
    form_id: str
    ad_id: str | None
    created_time: str | None
    fields: dict[str, str] = field(default_factory=dict)
    custom_fields: dict[str, str] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "leadgen_id": self.leadgen_id,
            "form_id": self.form_id,
            "ad_id": self.ad_id,
            "created_time": self.created_time,
            "fields": self.fields,
            "custom_fields": self.custom_fields,
        }


def _slug_key(raw_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", raw_name.strip().lower()).strip("_")


def _first_value(values: list[str]) -> str:
    return values[0] if values else ""


def normalize_lead(graph_lead_response: dict[str, Any]) -> NormalizedLead:
    fields: dict[str, str] = {}
    custom_fields: dict[str, str] = {}

    for entry in graph_lead_response.get("field_data", []):
        raw_name = entry.get("name", "")
        value = _first_value(entry.get("values", []))
        slug = _slug_key(raw_name)

        canonical = _STANDARD_FIELD_MAP.get(slug)
        if canonical is None:
            for bucket_name, keywords in _KEYWORD_BUCKETS:
                if any(kw in slug for kw in keywords):
                    canonical = bucket_name
                    break

        if canonical:
            # First match for a canonical field wins -- a form with both a
            # standard "email" field and a stray custom question that also
            # mentions "email" should not let the second overwrite the first.
            fields.setdefault(canonical, value)
        else:
            custom_fields[raw_name] = value

    return NormalizedLead(
        leadgen_id=str(graph_lead_response.get("id", "")),
        form_id=str(graph_lead_response.get("form_id", "")),
        ad_id=graph_lead_response.get("ad_id"),
        created_time=graph_lead_response.get("created_time"),
        fields=fields,
        custom_fields=custom_fields,
    )
