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

**If you're running the hosted-subscription model (§6b), read this before
signing up a single customer.** Steps 1-6 above only grant **Standard
Access** — it works for Pages *you personally administer*. Reading leads
from a *subscriber's* Page requires **Advanced Access** to
`leads_retrieval`/`ads_management`, which means submitting this app for
**Meta App Review**: a verified business, a screencast demo per permission,
and a written justification — not instant, not guaranteed, can take weeks.
Without it, every subscriber's Page beyond your own will fail exactly like
thread 1's bug, permanently. This is a real administrative gate, not
something the code can route around — budget the time for it before
marketing the subscription publicly.

## 2. Deploy the service

This has to be **always-on**, not scale-to-zero: Facebook expects a fast ACK
on every webhook delivery and can eventually disable a subscription that's
consistently unreachable. That rules out free/sleep-on-idle tiers.

**Recommended: Render, Starter plan (~$7/mo).** Connect the GitHub repo,
point it at this directory's `Dockerfile`, add a small (~1GB, ~$1/mo)
persistent disk mounted at `/app/data` for the SQLite dedup file, set the
env vars from `.env.example` in the dashboard. No CLI, no manual TLS setup.

Alternatives if cost matters more than dashboard simplicity:
- **Fly.io** (~$10-20/mo all-in with a volume) — `fly launch` reads the
  Dockerfile directly; CLI-first, and 2026 reports flag volume/snapshot
  billing as easy to get wrong, so read `fly.io/docs/about/pricing` before
  committing.
- **A $5/mo VPS** (Hetzner, DigitalOcean) — cheapest, but you're now also
  responsible for TLS (e.g. Caddy) and process supervision yourself.

Whichever you pick, no host was chosen or paid for on your behalf — this is
the concrete recommendation, not an action taken.

**Hosting more than one product on Render.** One Render account/workspace
holds many independent services, not just this one — each product in the
portfolio gets its own Web Service (own repo, own Dockerfile, own env vars,
own disk), billed separately for compute. The free **Hobby** workspace tier
covers up to 25 services at no workspace fee; you only pay per service you
actually run always-on (~$7/mo Starter each, so 5 products ≈ $35/mo total,
not a shared/discounted bundle). You'd only need the paid **Pro** workspace
($25/mo flat) for team seats or higher limits — not something a single
operator running under 25 services needs yet.

```
docker build -t leadbridge .
docker run -p 8000:8000 --env-file .env leadbridge
```

Set these env vars (see `.env.example`) — split by which monetization model
you're running (§6 below); a deployment can run one or both:

| Var | Needed for | Where it comes from |
|---|---|---|
| `FB_APP_SECRET` | both | Meta App dashboard → Settings → Basic |
| `FB_WEBHOOK_VERIFY_TOKEN` | both | Any string you make up — used in step 3 |
| `FB_PAGE_ACCESS_TOKEN` | one-time self-hosted | Step 1.6 above |
| `MAKE_WEBHOOK_URL` | one-time self-hosted | Step 4 below |
| `STRIPE_WEBHOOK_SECRET` | selling either way | §6a/§6b |
| `RESEND_API_KEY`, `EMAIL_FROM_ADDRESS` | selling either way | §6a/§6b |
| `LINK_SIGNING_SECRET` | selling either way | §6a/§6b |
| `BASE_URL` | selling either way | this deployment's own public URL |

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

## 5. Testing this yourself — layered by what it needs

You don't need every layer working before trusting the layers below it.

**Layer 1 — code correctness, zero accounts, already done:**
`pytest` feeds the service realistic fake Facebook/Stripe payloads (real
shapes, captured as fixtures under `tests/fixtures/`) and checks it behaves
correctly. This is what "61 tests passing" means: the logic is proven, not
the live integration.

**Layer 2 — run it locally and hit it yourself:**
```
.venv/bin/uvicorn leadbridge.main:app --reload
# in another terminal:
curl "http://localhost:8000/webhook?hub.mode=subscribe&hub.verify_token=<FB_WEBHOOK_VERIFY_TOKEN>&hub.challenge=hello123"
# should echo back: hello123
curl http://localhost:8000/health
# should return: {"status":"ok"}
```

**Layer 3 — Stripe, fully testable with zero real money:** install the
[Stripe CLI](https://docs.stripe.com/stripe-cli), then:
```
stripe listen --forward-to localhost:8000/stripe/webhook
# prints a webhook signing secret -- put it in STRIPE_WEBHOOK_SECRET
stripe trigger checkout.session.completed
```
This fires a real, correctly-signed test event at your local server —
confirms the whole one-time/subscription email flow without a live payment
link or a cent spent, in Stripe's test mode.

**Layer 4 — Facebook, the one that can't be faked:** needs a real Page +
App + Meta's own **Lead Ads Testing Tool** (generates a test lead without
spending on ads). No shortcut around this — it's the first genuinely live
step, and the point of doing it before considering setup finished.

**Layer 5 — Make, no test-mode shortcut either:** `docs/make_blueprint_spec.md`
is written as an exact module list so you don't need to already know Make
to follow it. Build it once, use Make's own "Run once" mode to send a
manual test payload through, and confirm it lands in Airtable/Outlook.

## 6. Selling it with Stripe (only once you decide to)

Nothing here creates an account, publishes a page, or takes payment on your
behalf — Stripe, Resend, and any hosting/domain setup below all require you
to sign up and configure them yourself. Two independent paths — pick one or
both; the code supports running both off one deployment (§6c).

### 6a. One-time code sale

1. Create a Stripe account and complete verification.
2. Dashboard → **Payment links** → **Create payment link**, **one-time**
   price (landing page's current placeholder is $129).
3. Dashboard → **Webhooks** → add an endpoint at
   `https://<your-deployed-host>/stripe/webhook`, subscribed to
   `checkout.session.completed`. Copy its signing secret into
   `STRIPE_WEBHOOK_SECRET`.
4. Set `RESEND_API_KEY` (Resend dashboard → API Keys) and
   `EMAIL_FROM_ADDRESS` (must be a domain verified in Resend).
5. Set `LINK_SIGNING_SECRET` to a long random value (`openssl rand -hex 32`)
   and `BASE_URL` to this deployment's public URL.
6. **Fulfillment is automatic**: `main.py`'s `/stripe/webhook` catches the
   completed checkout, emails the buyer a signed, expiring download link
   (`LINK_EXPIRY_HOURS`, default 72h) to `/download`, which streams the zip
   built at Docker image build time (`scripts/build_release_zip.py` — never
   includes `.env`, only `.env.example`).

### 6b. Hosted subscription

**Read the Meta App Review callout under §1 first** — this path only works
for customers whose Page you can get Advanced Access to.

1. Same Stripe steps as 6a, except create a **recurring** price instead of
   one-time.
2. Same `STRIPE_WEBHOOK_SECRET`/Resend/`LINK_SIGNING_SECRET`/`BASE_URL`
   setup, plus subscribe the webhook endpoint to `customer.subscription.deleted`
   too (so a cancellation actually stops processing that customer's leads).
3. **Onboarding is automatic**: a new subscription emails the customer a
   signed link to `/setup`, a form where they paste their own Page ID,
   Page Access Token, and Make webhook URL — stored in `tenants.py`,
   looked up by `page_id` on every incoming lead from then on.
4. Leave `FB_PAGE_ACCESS_TOKEN`/`MAKE_WEBHOOK_URL` empty if this deployment
   runs *only* the subscription side — every lead resolves through a
   tenant record instead.

### 6c. VAT/tax — read before going live either way

Unlike Gumroad, Stripe does **not** act as merchant of record by default —
you stay responsible for VAT on digital sales, including the EU's
One-Stop-Shop rules. Stripe Tax helps calculate/collect it, but
registration is still on you. Worth a short conversation with an
accountant before the first real sale, not after.

### 6d. Wiring up the landing page

Once you have the real Payment Link URL(s), send them over and I'll wire
them into `landing/index.html`'s "Buy" buttons (currently placeholders).

## 7. Promoting it without fighting API keys

See `docs/marketing_ops_strategy.md` for the full comparison. Short version:
connect Buffer's official MCP server (`claude mcp add --transport http
buffer https://mcp.buffer.com/mcp`, OAuth sign-in, no API key, free tier
included) and a Claude Code session can draft/schedule/post across every
platform you connect in Buffer — no per-platform developer app needed.
