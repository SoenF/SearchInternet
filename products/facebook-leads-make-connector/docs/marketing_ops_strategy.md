# Marketing ops: posting everywhere without fighting API keys

Scope: how to promote *this* product (and every later one, since the
tooling is product-agnostic) without hand-rolling OAuth for X/LinkedIn/
Instagram/Facebook/TikTok/etc. individually. This is a tooling strategy, not
a build task — nothing below was signed up for, connected, or posted on
your behalf.

## The actual problem

Each social platform's native API means its own developer app, its own
review/approval process, its own OAuth dance, its own rate limits, and its
own key rotation to babysit. Multiply that by every platform × every
product in the portfolio and it becomes a real maintenance job on its own —
exactly what you flagged wanting to avoid. The fix is the same shape as
`leadbridge` itself: put one layer between you and the platforms so you
manage one credential, not N.

## Which accounts are actually worth creating

Not "all of them" — the audience for LeadBridge is narrow (people who run
Facebook Lead Ads into Make.com, mostly agencies/freelancers managing
client campaigns), and each platform's relevance to that audience is very
different:

- **The Make.com community forum itself** — highest intent of anything on
  this list: it's literally where the two threads this product is built
  from came from. **Buffer cannot post here** — checked its actual channel
  list (X, LinkedIn, Instagram, Facebook, TikTok, YouTube Shorts,
  Pinterest, Google Business Profile, Mastodon, Threads); Discourse-based
  forums aren't and likely won't be on it, since Buffer's whole model is
  scheduled broadcast posts, not threaded community replies. This is the
  right split, not a gap: an auto-scheduled forum reply would read as spam
  and undercut exactly the credibility that makes this channel worth
  bothering with. Post here manually, as yourself, in the actual threads —
  disclose you built it, don't drop a bare link with no context.
- **LinkedIn** — real fit. This is where marketing-ops people, no-code
  agency owners, and consultants managing client ad accounts actually are.
  Primary channel.
- **X** — decent secondary. There's a real "build in public" / no-code /
  indie-hacker crowd there that overlaps with Make.com power users.
- **Reddit** — situational, and a *personal account you post from manually*
  is unrelated to the Opportunity Engine's earlier Reddit API decision
  (that was about programmatic data collection, a different concern
  entirely). r/Automate, r/nocode, r/FacebookAds, r/msp are plausible fits
  — but Reddit's per-subreddit self-promotion rules are strict and vary a
  lot; check each subreddit's rules before posting, some ban it outright or
  require a participation history first.
- **Instagram / Facebook (organic posts)** — weak fit. This is a visual,
  consumer-attention platform; the audience for "GraphMethodException 100
  fix" isn't scrolling it for that. Skip organic posting here — only
  reconsider if you later decide to run *paid* ads targeting agencies
  specifically, which is its own separate budget decision, not something
  covered by Buffer's free posting tier.

So: **LinkedIn + the Make forum first, X second**, Reddit only where a
specific subreddit's rules allow it, and Instagram/Facebook skipped for now.

## Recommended: Buffer's MCP server (start here, today, free)

Buffer shipped an **official MCP server** in 2026: `https://mcp.buffer.com/mcp`.
Connection is OAuth — you sign in to Buffer once, approve access, and there
is no API key to generate, paste, or rotate at all. Once connected, an
agent (Claude Code itself, right in a session like this one) can draft,
schedule, and publish posts across every platform you've connected to your
Buffer account, driven by conversation instead of code.

- Setup is one command: `claude mcp add --transport http buffer https://mcp.buffer.com/mcp`,
  then `/mcp` in a session to sign in.
- API/MCP access is included on Buffer's **free tier** (3,000 requests /
  30 days) — no cost to try this today.
- This means "the marketing ops agent" doesn't need to be a separate thing
  you build — for a single operator, it can just be a Claude Code session
  with this MCP server attached, asked to draft and queue posts about
  LeadBridge across whichever channels you've connected in Buffer.

**This is the one thing here that's actually actionable right now** — say
so and I can run the `claude mcp add` command in this session; it still
needs *you* to complete the OAuth sign-in yourself (that step can't be done
on your behalf).

## Video and images: what I can actually produce vs. what needs you

- **Static graphics**: yes — the landing page's "messy JSON → clean JSON"
  panel and the two error cards (`landing/index.html`) are already
  screenshot-able as standalone social images, and I can draft more in the
  same style (code snippets, before/after diagrams) on request.
- **Post copy**: yes, drafted per-platform once Buffer is connected.
- **A real demo video** (the webhook firing, Make receiving one clean
  payload): no, not fabricated — that only means something once shot
  against an actual live deployment with a real Facebook Page and Make
  scenario. That needs `docs/SETUP.md` finished first; recording it is
  either you screen-recording your own working setup, or, once it's live,
  something I could walk through with you.

## If you outgrow Buffer's free tier or want zero recurring cost

**Postiz** — open-source (AGPL-3.0), genuinely free if self-hosted (same
"pay nothing if you bring the server" deal as everything else in this
portfolio's cost model), with a public API and native n8n/Make.com
integration, covering ~30 platforms. Trade-off: you're back to running a
small always-on service for it, the same hosting decision as `leadbridge`
itself (`docs/SETUP.md` §2) — worth it once posting volume outgrows
Buffer's rate limit, not before.

## If the portfolio grows into managing *other people's* social accounts

**Ayrshare** — built explicitly for agencies/SaaS managing many end-users'
social accounts under one account, not just your own. Real cost: $149/mo
minimum. Not worth it for promoting one product you own; worth revisiting
if a later product in this portfolio is itself a tool that posts on
*customers'* behalf.

## What this doc deliberately does not do

No Buffer/Postiz/Ayrshare account was created, no OAuth was approved, no
post was scheduled or published, and no subscription was purchased. All
three require an explicit decision and, for Buffer, your own sign-in — this
is the comparison to make that decision from, not the decision itself.
