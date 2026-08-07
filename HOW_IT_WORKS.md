# How the Opportunity Engine works

A plain-language walkthrough of what the code actually does, step by step,
and exactly where (and where not) an LLM is involved. For setup/commands see
`HOW_TO_RUN.md`; for architecture rules and rationale see `CLAUDE.md`.

## The one-sentence version

Every day, the pipeline reads six free/official sources for signs someone
has an unmet need or a working-but-improvable product, scores each signal on
four dimensions, and writes out a ranked shortlist — almost all of it
without ever calling an LLM.

## Step 1 — Ingest

Six connectors each pull raw items published in the last `--days` (default:
1 day) from their source:

| Connector | What it pulls | Cost/access |
|---|---|---|
| Hacker News (Algolia) | Ask HN pain points, Show HN launches | Free, no key |
| SEC EDGAR | Form D private funding filings | Free, no key |
| Wikipedia Pageviews | Daily views for articles you're watching | Free, no key |
| iTunes/App Store | Top-100 charts, 4 countries | Free, no key |
| Stack Exchange | Questions on Software Recommendations | Free, key optional |
| GitHub Issues | Open issues labeled `enhancement` | Free, key optional |
| Reddit (opt-in) | Posts from a few configured subreddits | Free, needs credentials |
| Product Hunt (opt-in) | New launches | Free, needs a token |

Every item becomes one row in `raw_documents` — no interpretation happens
yet, just "here's what this source said, verbatim." No LLM involved.

## Step 2 — Dedup

Each new document gets converted to a 768-number vector (a local embedding
model, `multilingual-e5-base`, runs entirely on your machine — no network
call, no LLM, no per-item cost) that captures its meaning, not just its
words. That vector is compared against every existing "opportunity"'s
centroid:

- **Very similar (≥0.92 cosine similarity)** → merged into the existing
  opportunity (this is the same idea, mentioned again).
- **Very different (<0.75)** → a brand-new opportunity is created.
- **In between** → also a new opportunity, but flagged for later review —
  the model isn't confident either way.

This is how "SSL certificate auto-renewal" mentioned three different ways
across HN, Reddit, and a GitHub issue all end up as *one* tracked
opportunity instead of three duplicates. No LLM involved — this is pure
vector math (cosine similarity), not language understanding.

## Step 2.5 — Check competitors

For each opportunity that's never been checked before (once per opportunity,
not daily — this doesn't change fast enough to justify repeated calls), its
title gets searched against GitHub's repo search and npm's package search,
free and keyless. The total number of matches becomes a stored count. This
*is* a real (free, no-signup-required) network call, unlike every other step
in the daily pipeline — but still no LLM, and still fully deterministic: a
keyword count, not an opinion. That count feeds a warning in Step 3 below,
never an automatic rejection — competitors existing can just as easily mean
a validated market as a crowded one. It's a strong signal for developer-
tool-shaped ideas and a blind spot for anything with no GitHub/npm
footprint (a consumer app, a physical product) — an honest limitation, not
a bug.

## Step 3 — Score

Every still-open opportunity gets re-scored daily on four dimensions, none
of which use an LLM:

1. **Momentum** — is mention/pageview/chart-rank activity trending up over
   the last 7 days vs. an 8-week baseline? A brand-new opportunity that
   hasn't had time to build a baseline gets `insufficient_history`, not a
   penalty — its score is based on the other dimension alone until real
   history exists (a well-evidenced idea shouldn't have to wait weeks to
   rank well).
2. **Market proof** — has anyone put real money behind this? A disclosed
   revenue number in a post, an SEC funding filing, a top App Store rank —
   each contributes a weighted, time-decayed point value. One EDGAR funding
   filing alone can outweigh a dozen "I wish this existed" comments,
   deliberately — money is a stronger signal than intent.
3. **Buildability** (pass/fail gate) — rejects anything that's clearly a
   regulated industry, requires heavy third-party integrations, or reads
   like a capital-intensive enterprise sale. Keyword-based, not an LLM
   judgment call — see `tools/regulatory.py`.
4. **Vendability** (pass/fail gate) — rejects non-recurring-revenue models
   and anything that needs daily manual intervention to run. Also flags (but
   doesn't reject) opportunities that look tied to one specific person's
   personal brand, and separately flags (also without rejecting) a high
   competitor-match count from Step 2.5 — both are warnings, not automatic
   disqualifications, since neither can be judged reliably from these
   sources alone.

Opportunities tagged "arbitrage" (something popular in one country's App
Store charts, absent from another) have one more hard rule: if no real
barrier (language, payments, regulation) explains the absence, it's
rejected outright — "nobody's built it there yet" isn't itself an
opportunity if there's no reason it hasn't been built.

Everything in this step itself is arithmetic and keyword matching against
structured data already in the database — no network calls here (Step 2.5
already made the one exception in the daily pipeline, and only to two free
registries). Zero LLM calls anywhere — enforced by a static test that scans
the source code and fails the build if an LLM import shows up anywhere
outside the one file that's allowed to have one.

## Step 4 — Rank

The scored opportunities get assembled into a ranked shortlist (default: top
20), balancing "the actual best scores" against two things pure ranking
would miss: keeping a healthy mix of the two detection strategies
(pain-driven vs. arbitrage) instead of one dominating, and a small
"exploration" slice reserved for under-represented categories so a good
idea in a quiet category isn't permanently buried by score alone. Also pure
math — no LLM.

## Step 5 — Feedback (passive, no command to run)

Every time something gets rejected, it becomes a soft warning sign for
future candidates: if a brand-new opportunity's embedding sits very close to
a *previously rejected* opportunity's, it takes a small score penalty. This
happens automatically as part of Step 3 — nothing to run separately, and
still no LLM (same cosine-similarity math as dedup).

## Where the LLM actually is

**Everywhere above: nowhere.** The daily pipeline (`run-daily` — ingest,
dedup, score, rank) makes exactly zero LLM calls, by design and enforced by
a test, not just by convention. This keeps the daily pipeline free, fast,
deterministic, and fully explainable — every score can be traced back to
the exact evidence and math that produced it.

The **only** place an LLM is called anywhere in this codebase is the
`deep-dive` command — and only when you run it yourself, by hand, on one
specific opportunity you're seriously considering:

```bash
python -m opportunity_engine.cli.main deep-dive 42
```

This sends that one opportunity's full evidence (every linked document, all
proof events, its current score breakdown) to Claude and asks for a
structured dossier: a summary, an honest read on the market evidence, a
buildability/vendability assessment, key risks, and a pursue/pursue-with-
caution/pass recommendation. It defaults to Claude Haiku (cheapest, fastest)
and only escalates to Sonnet if you explicitly pass `--escalate --reason
"..."` explaining why Haiku wasn't enough — Opus is not reachable at all,
anywhere in this codebase, at any phase. Every call's cost is logged and
capped by a pre-flight budget check (`~$3.30` ceiling per dossier by
default) before it's ever sent.

In short: the LLM is a magnifying glass you point at one opportunity at a
time, by choice, after the free rule-based pipeline has already done the
work of surfacing it — never a step the daily pipeline takes on its own.
