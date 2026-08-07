# Make.com scenario spec

This is a precise, buildable module list — written to be followed exactly in
Make's scenario editor. **It is not an exported/imported blueprint file**:
building one requires a live Make account to construct and test in Make's
own UI, which this build environment doesn't have. Don't claim to a customer
that a ready-to-import `.json` blueprint exists until one has actually been
built and exported from a real Make account and test-run against a real
lead — track that as the one remaining unverified step (see `docs/SETUP.md`
§5).

## Module 1 — Custom Webhook (trigger)

App: **Webhooks** → **Custom webhook**. Create it, copy the generated URL
into `MAKE_WEBHOOK_URL`. Run the scenario once in "Run once" mode and send
one test POST from `leadbridge` (or `curl`) to it so Make learns the payload
structure — this is what lets later modules autocomplete `fields.email`
etc. as mappable tokens.

Expected payload shape (produced by `leadbridge`, identical regardless of
which Facebook Instant Form the lead came from):

```json
{
  "leadgen_id": "1930628924301148",
  "form_id": "998877665544",
  "ad_id": "554433221199",
  "created_time": "2026-08-07T14:29:22+0000",
  "fields": { "full_name": "...", "email": "...", "phone_number": "..." },
  "custom_fields": { "what_s_your_monthly_training_budget_": "500-1000" }
}
```

## Module 2 — Router (optional)

Only needed if this one scenario must fan out to more than one destination
per the pitch (Airtable **and** Outlook **and** Gmail). Add one route per
destination; each route below is independent.

## Module 3a — Airtable: Create a Record

App: **Airtable** → **Create a Record**. Map:
- `Name` ← `{{1.fields.full_name}}`
- `Email` ← `{{1.fields.email}}`
- `Phone` ← `{{1.fields.phone_number}}`
- `Company` ← `{{1.fields.company_name}}`
- `Notes` ← a **Text aggregator** or **Set variable** step run first to
  JSON-stringify `{{1.custom_fields}}`, so per-form custom questions still
  land somewhere instead of being dropped (mirrors `leadbridge`'s own
  "custom_fields, not discarded" behavior).

## Module 3b — Microsoft 365 / Outlook: Send an Email

App: **Microsoft 365 Email** → **Send an Email**. This is the exact module
from thread 2 (`docs/root_cause_notes.md`) that was failing to receive field
data — with `leadbridge` in front, its inputs are now always
`{{1.fields.*}}`, present and identically named no matter which form the
lead came from.
- To: the shared inbox address.
- Subject: `New lead: {{1.fields.full_name}}`
- Body: template combining `{{1.fields.*}}` plus the same JSON-stringified
  `{{1.custom_fields}}` block as above.

## Module 3c — Gmail: Send an Email

Same mapping as 3b, using the **Gmail** app's **Send an Email** module
instead, for customers on Gmail rather than Microsoft 365.

## Error handling

Add Make's built-in **Break** error handler on each destination module,
routed to a **Slack** or **Email** notification module, so a downstream
failure (e.g. Airtable rate limit) surfaces immediately instead of silently
dropping a lead — this is the "reliable" half of the pitch, not just the
field-mapping half.
