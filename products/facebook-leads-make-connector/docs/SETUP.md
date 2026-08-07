# Setup guide

Everything in this file requires accounts and credentials nobody but you (or
a customer) can create — Facebook Business Manager access, a Make.com
account, and a place to host the service. None of it was set up for you;
this is the exact sequence to do it.

## 1. Facebook App + Page access

1. Create a Meta App at developers.facebook.com (type: Business).
2. Add the **Webhooks** product, subscribe to the `page` object, `leadgen`
   field.
3. Add the **Marketing API** product (needed for lead retrieval scopes).
4. On the Page you're connecting: make sure the user generating the access
   token has an **advertiser role on the ad account** the lead forms belong
   to, not just admin on the Page. This is the exact gap thread 1
   (`docs/root_cause_notes.md`) hit — Page admin alone is not enough.
5. Generate a **Page Access Token** (via Graph API Explorer or a proper OAuth
   flow) with these scopes granted, all four, not a subset:
   `ads_management`, `leads_retrieval`, `pages_show_list`,
   `pages_read_engagement`.
6. Exchange it for a **long-lived token** (60-day, Meta's documented
   token-exchange endpoint) so it doesn't expire under a customer mid-use.

## 2. Deploy the service

Any host that runs a Docker container or a plain ASGI app works — Render,
Fly.io, Railway, a $5/mo VPS. No specific provider is required or was chosen
for you.

```
docker build -t leadbridge .
docker run -p 8000:8000 --env-file .env leadbridge
```

Set these env vars (see `.env.example`):

| Var | Where it comes from |
|---|---|
| `FB_APP_SECRET` | Meta App dashboard → Settings → Basic |
| `FB_PAGE_ACCESS_TOKEN` | Step 1.6 above |
| `FB_WEBHOOK_VERIFY_TOKEN` | Any string you make up — used only in step 3 below |
| `MAKE_WEBHOOK_URL` | Step 4 below |

## 3. Point Facebook's webhook at the deployed service

In the Meta App's Webhooks product config: callback URL =
`https://<your-deployed-host>/webhook`, verify token = the same string you
put in `FB_WEBHOOK_VERIFY_TOKEN`. Meta calls this URL once with a `GET` to
confirm you control it (`main.py:verify_webhook` handles this); after that,
it POSTs a `leadgen` notification every time a lead comes in on any
subscribed form on the Page.

## 4. Build the one Make scenario

See `docs/make_blueprint_spec.md` for the exact module list. In short: one
**Custom Webhook** trigger in Make gives you a URL — that's
`MAKE_WEBHOOK_URL` above. Everything downstream of it (Airtable / Outlook /
Gmail / wherever) reads from a fixed JSON shape
(`{leadgen_id, form_id, ad_id, created_time, fields: {...}, custom_fields:
{...}}`), the same shape regardless of which Instant Form the lead came from
— that's the fix for thread 2.

## 5. What's tested vs. what isn't yet

Tested (via `pytest`, real Facebook payload shapes as fixtures, no live
calls): webhook signature verification, the verification handshake, field
normalization across differently-shaped forms, dedup on redelivery, and the
exact `GraphMethodException` 100 diagnostic path from thread 1.

**Not yet tested**: an actual live Facebook Page delivering a real lead
through a real deployment into a real Make scenario. That needs a real
Facebook Business Manager + Page + Make account to do — the first time you
(or a customer) run this end-to-end, submit a real test lead via Meta's Lead
Ads Testing Tool and confirm it lands correctly in Make before considering
setup finished.

## 6. Selling it (only once you decide to)

Nothing here creates an account, publishes a page, or takes payment on your
behalf. `landing/index.html` is a draft you can publish yourself (Gumroad
product page, or host it and link a Stripe Payment Link) whenever you're
ready.
