# Opportunity Engine

Detects, scores, and ranks micro-SaaS business opportunities from free/official
signal sources, maintaining a persistent, deduplicated, ranked backlog
(`candidate -> qualified -> in_build -> launched -> sold`, or `-> rejected`).
This is the first component of a larger portfolio-building pipeline (build,
launch, operate, and resell many small SaaS products). Later components
(Validation Engine, SaaS Generator, Marketing OS, Analytics Engine, Portfolio
Manager, Exit Manager) are not built yet and are out of scope here — this
codebase only owes them clean extension points (see "Out of scope" below),
not pre-built infrastructure.

## `products/` — built products, not part of the engine

`products/` holds actual SaaS products picked from the engine's own backlog
output and built to sell — the portfolio this engine exists to feed, starting
to take shape. Each is a fully separate codebase (own `pyproject.toml`, own
deps, own tests) living here only for monorepo convenience. None of the
non-negotiable architecture rules below apply to them — they're regular
product code, not the opportunity-detection engine. See each product's own
`README.md` for what it is and its own grounding evidence.

- `products/facebook-leads-make-connector/` — a reliability layer fixing two
  real, current Facebook Lead Ads → Make.com integration failures (variable
  per-form field mapping, and a Graph API lead-retrieval permission bug),
  sourced from the engine's `discourse_forums` connector. Started
  2026-08-07; see its `docs/root_cause_notes.md` for the two real community
  threads this is grounded in.

## Phase status

All five phases from the original spec are now implemented:

- **Phase 1** (level-1 connectors + storage + dedup) and **Phase 2**
  (rule-based scoring + backlog ranking, zero LLM calls) — the free daily
  pipeline: HN, EDGAR, Wikipedia, App Store connectors; semantic dedup;
  momentum + market-proof scoring; buildability/vendability/arbitrage-barrier
  gates; diversity-aware ranking.
- **Phase 3** (`collectors/reddit.py`, `collectors/producthunt.py`,
  `agents/archive_import_agent.py`) — two additional connectors, both
  **opt-in and off by default** (silently skipped without credentials, see
  `collectors/registry.py`), plus `import-archive` for bulk historical Reddit
  backfill. See "Phase 3 ToS caveat" below before enabling either connector
  beyond local experimentation.
- **Phase 4** (`providers/llm_provider.py:AnthropicProvider`,
  `agents/deep_dive_agent.py`) — the on-demand, single-opportunity LLM
  dossier, and the only thing in this codebase allowed to spend money on an
  LLM call. Haiku default, Sonnet ceiling with a required written escalation
  reason, Opus unreachable (`ALLOWED_MODELS` allowlist). Never called from
  the daily pipeline.
- **Phase 5** (`tools/feedback.py`, wired into `agents/scoring_agent.py`) —
  passive: a candidate whose embedding sits near a previously rejected
  opportunity's centroid gets a soft score penalty. No command to run.

Beyond the original 5 phases, two more always-on connectors were added on a
real, current, explicitly-stated need (see "Out of scope" below for the
general rule this satisfies an exception to):
- **`collectors/stackexchange.py`** — Stack Exchange Questions API, default
  site `softwarerecs` ("is there a tool that does X" is its entire premise).
  No credential required; `STACKEXCHANGE_API_KEY` only raises the daily quota.
- **`collectors/github_issues.py`** — GitHub Search Issues API, default
  query `is:issue is:open label:enhancement`. No credential required;
  `GITHUB_TOKEN` only raises the search rate limit.

Both are registered unconditionally in `collectors/registry.py` (like the
Phase 1 four), not opt-in-via-credential like Reddit/Product Hunt, since
neither API gates access behind a key.

Two more, on the same basis, address a real gap: every source above skews
toward a developer audience, so nothing surfaced non-technical pain points
(legal, accounting, real estate, housing) at all.
- **`collectors/app_store_reviews.py`** — iTunes RSS customer reviews for
  apps charting in Finance/Business/Lifestyle genres (verified live: Zillow
  Real Estate & Rentals charts in Lifestyle, ADP Mobile Solutions in
  Business) — reviews on an already-monetizing consumer app, from a
  non-developer audience. No credential required.
- **`collectors/discourse_forums.py`** — public topics from Discourse-based
  no-code/small-business tool communities (default: `forum.bubble.io`,
  `community.make.com`), via Discourse's own documented no-auth `.json` API.
  Reaches small-business/no-code builders who already pay for a SaaS tool.
  No credential required; not every Discourse community responds cleanly to
  a plain JSON GET (Cloudflare, redirects) — see the module docstring before
  adding more via `DISCOURSE_FORUMS`.

Also added on the same explicit-need basis: **`agents/competitor_check_agent.py`**
— zero-LLM competitor-saturation signal. For each opportunity (once, not
re-checked daily), searches GitHub repos + npm packages by title keywords and
stores a total match count + top matches. Feeds `evaluate_vendability` a
warning (`RejectionReason.VENDABILITY_COMPETITOR_SATURATION_WARNING`), never
a rejection — competitors existing can also mean a validated market. Runs in
the free daily pipeline (`check-competitors`, wired into `run-daily` between
`dedup` and `score`) since both APIs are free and uncredentialed, same as
Stack Exchange/GitHub Issues above. Reuses `GITHUB_TOKEN`. Detects developer-
tool-shaped competitors well; a consumer app or service with no GitHub/npm
footprint is a documented blind spot, same honest-limitation pattern as the
personal-brand-risk warning.

See `HOW_TO_RUN.md` for the full operational guide (setup, every CLI command,
credentials, cost expectations, a realistic weekly workflow). This file stays
focused on architecture and rules.

### Phase 3 ToS caveat

`RedditCollector` and `ProductHuntCollector` both carry
`tos_status: "review_needed"` in their `ConnectorManifest`, not
`"compliant"` like the four Phase 1 connectors. Reddit's 2023 Data API Terms
and Product Hunt's API terms both impose restrictions on commercial use this
project has not had legal review against. Both are opt-in (silently skipped
without `REDDIT_CLIENT_ID`/`PRODUCTHUNT_ACCESS_TOKEN`) so this is never an
accidental exposure, but get real legal review before depending on either
structurally — especially before any later portfolio-pipeline phase resells
or publishes anything derived from their data.

## Non-negotiable architecture rules

These came from the project owner directly — do not relitigate them without
being asked.

1. **No agent framework.** No LangChain, LangGraph, CrewAI, or equivalent. If
   one is ever proposed, first answer in writing: what concrete problem it
   solves here, its maintenance cost, and its impact on tests/debugging/
   readability. If the answer isn't obvious, don't use it.
2. **"Agents" are single-responsibility business services**, not LLM agents —
   `src/opportunity_engine/agents/`. They never call each other directly. They
   communicate only through the database and the append-only `events` table.
3. **Cross-cutting dependencies are injected, never inherited**: config,
   logger, LLM provider, DB connection, clock. No god base class accumulating
   responsibilities.
4. **"Tools" are pure, standalone functions** with no dependency on any agent
   class (`search_hackernews()`-style, all under `tools/`).
5. **An interface/ABC exists only with two real implementations, now or within
   3 months.** The only four sanctioned interfaces in this codebase:
   `Collector` (one per data source), `DetectionStrategy` (`PainDrivenStrategy`,
   `ArbitrageStrategy`), `LLMProvider`, `EmbeddingProvider`. Everything else is
   concrete, direct code:
   - **No DB abstraction** — Postgres is a permanent, assumed choice.
   - **No cache abstraction.**
   - **No message bus** — the append-only `events` table is enough with one
     consumer today.
   - **No generic "plugin" layer.**
   - **No interface with a single implementer.**
6. **No Redis, no broker, no heavy ORM.** `psycopg` (psycopg3) is the only DB
   dependency — no SQLAlchemy. Migrations are plain numbered `.sql` files run
   by a ~30-line runner (`migration_runner.py`), not Alembic.
7. **Every connector documents itself**: source, quota, ToS status, date last
   verified — see `ConnectorManifest` in `collectors/base.py` — and can be
   disabled independently via the `DISABLED_CONNECTORS` env var without
   touching the rest of the engine.
8. **Quality bar**: mypy strict, zero network/LLM calls in tests (enforced by
   `pytest-socket`), every connector has a fixture test, every scoring/
   rejection decision is traceable and explainable after the fact
   (`score_history.inputs_snapshot`, `opportunities.rejection_detail`),
   structured (JSON) logs throughout.
9. **Cost discipline**: processing order is SQL -> Python -> local embeddings
   -> cache -> batch -> LLM. Phase 1-2 makes zero LLM calls by construction —
   `NoOpLLMProvider` always raises, and a static test greps `src/` to confirm
   no `anthropic`/`openai` import exists outside `providers/llm_provider.py`.
   **Opus is never to be used or proposed on this project, in any phase** —
   `AnthropicProvider.ALLOWED_MODELS` makes this a hard runtime rejection, not
   just a convention. Phase 4's model default is Haiku; Sonnet is the
   absolute ceiling, used only after a demonstrated, written justification
   that Haiku failed a specific task (`deep-dive --escalate --reason ...`,
   enforced by `agents/deep_dive_agent.py` raising without one).

## Directory map

```
migrations/            versioned SQL, applied in order by migration_runner.py
src/opportunity_engine/
  config.py            Settings dataclass from os.environ, passed explicitly
  clock.py             injected Clock instead of datetime.now()/date.today()
  logging_setup.py     stdlib logging + JSON formatter
  db.py                psycopg3 connection/pool (concrete, no DB abstraction)
  migration_runner.py  applies migrations/*.sql, tracks schema_migrations
  events.py            append_event() + event type constants
  domain/              pure dataclasses/enums shared across the codebase
  collectors/          one Collector implementation per data source: hackernews,
                        edgar, wikipedia_pageviews, app_store (Phase 1), reddit,
                        producthunt (Phase 3, both opt-in), stackexchange,
                        github_issues (always enabled, no credential needed)
  tools/                pure functions: parsing (one module per source format),
                        scoring, dedup, clustering, ranking, storage, feedback
                        (Phase 5 rejection-penalty math)
  strategies/           DetectionStrategy implementations (pain_driven, arbitrage)
  providers/            LLMProvider (NoOpLLMProvider, AnthropicProvider),
                        EmbeddingProvider (LocalE5EmbeddingProvider)
  agents/               ingestion / dedup / scoring / ranking / deep_dive /
                        archive_import / competitor_check — DB + events only,
                        never call each other
  cli/main.py           migrate | ingest | dedup | score | rank | track-topic |
                        sync-connectors | deep-dive | import-archive |
                        check-competitors | run-daily
scripts/                manual/ops tooling, never imported by the app or run in CI
tests/                  unit/ (pure), connectors/ (fixture-driven), integration/
                        (gated on OPPORTUNITY_ENGINE_TEST_DATABASE_URL)
```

## How to run

```
docker compose up -d db
cp .env.example .env   # fill in DATABASE_URL if you changed docker-compose ports
source .venv/bin/activate
python -m opportunity_engine.cli.main migrate
python -m opportunity_engine.cli.main run-daily     # ingest -> dedup -> score -> rank
```

See `HOW_TO_RUN.md` for the full command reference (including Phase 3's
`import-archive` and Phase 4's `deep-dive`), credentials, cost expectations,
and a realistic weekly workflow. Quick summary of the rest: `track-topic`
(seed a Wikipedia article to watch) and `sync-connectors` (upsert connector
manifests into the `connectors` table for observability).

## Database schema

`migrations/*.sql` is the source of truth — read them directly rather than
trusting a summary here to stay current. Key structural notes:
- Embeddings are `vector(768)`, matching `intfloat/multilingual-e5-base`.
  **Switching embedding models (e.g. to `bge-m3`, 1024-dim) requires a
  migration to alter the column plus a full re-embedding backfill** — pgvector
  columns are fixed-dimension, this is not a config change.
- `opportunity_daily_signal` stores raw per-channel counts only; momentum
  weighting happens at read time in `tools/scoring_tools.py`, so weights can
  change without a backfill.
- `events` is append-only (a trigger raises on UPDATE/DELETE).
- `backlog_snapshots` is keyed by `(window_start, window_end, rank)` — this
  table *is* the ranking cache, and its key already includes the time window,
  so it can't silently return a stale/frozen backlog.
- `opportunity_dossiers` (migration 0012, Phase 4) stores every `deep-dive`
  call's full structured output plus model/purpose/tokens/cost/latency —
  the audit trail behind acceptance criterion #4.

## Adding a new connector

1. Subclass `Collector` in `collectors/`, define a `ConnectorManifest`
   (`name`, `source_description`, `source_url`, `quota_description`,
   `tos_url`, `tos_status`, `last_verified`).
2. Implement `collect(since, until) -> Iterator[RawDocument]`, with parsing
   delegated to a pure function in `tools/`.
3. Record a fixture (a real, saved response) under `tests/fixtures/<name>/`
   and a fixture-driven test under `tests/connectors/`.
4. Register it in `collectors/registry.py`.
5. Note honestly: fixture tests catch *our parser* regressing against a known
   response shape — they do not detect the live API changing shape out from
   under us. Run `scripts/refresh_fixtures.py` occasionally (manually, not in
   CI) to diff a fresh sample against the committed fixture. Exception:
   `tests/fixtures/producthunt/posts_page.json` is hand-constructed, not a
   captured live response — Product Hunt's API requires an OAuth token for
   every request, unavailable in this build environment. Its field shapes
   were verified against the public GraphQL schema instead; say so explicitly
   if you ever add another credential-gated connector the same way.

## Adding a new DetectionStrategy

Subclass `DetectionStrategy` in `strategies/`, implement
`evaluate(evidence) -> StrategyEvaluation`. If the strategy has a hard
elimination rule (like arbitrage's "no barrier identified"), that rejection
must happen *before* scoring, with a persisted, traceable reason.

## Known, deliberate limitations of the Phase 1-2 rule-based gates

The `buildability`/`vendability` eliminatory gates and the arbitrage barrier
check are rule-based approximations (keyword lists, EDGAR SIC codes, App Store
genre categories) because Phase 1-2 makes zero LLM calls. In particular:
- "Transferability" (no dependency on a specific person/brand) is the weakest
  rule available — `is_personal_brand_only_source()` only produces a
  **warning**, never an automatic rejection, given how little Phase-1 sources
  can actually tell about brand dependence.
- `ArbitrageStrategy`'s `language_localization_barrier` is derived purely from
  which countries' App Store RSS charts an app has appeared in during
  ingestion — there is no live iTunes `lookup` call to confirm genuine listing
  absence in the target market (see `agents/scoring_agent.py`'s module
  docstring). An app that's listed in the US but simply doesn't chart top-100
  there looks identical, to this pipeline, to one that's genuinely absent.
  Bounded false-positive risk, kept out of Phase 2 to avoid a live network
  call inside scoring. `tests/fixtures/app_store/lookup_by_id.json` exists
  for when this gets built — still not built as of Phase 4, which became the
  on-demand LLM dossier instead; this remains a real, open enrichment idea,
  not something any implemented phase already covers.
- EDGAR SIC-code enrichment is frequently empty by nature, not by bug: most
  Form D filers are newly formed single-purpose entities with no SIC on file.
  Confirmed against live data — a spot-check ingest (2026-08-07, ~600 Form D
  filings over a 3-day window) found SIC codes populated only for established
  filers (e.g. existing bank holding companies), empty for the rest.
- Dedup thresholds (`DEDUP_MERGE_THRESHOLD=0.92`, `DEDUP_NOVEL_THRESHOLD=0.75`)
  are starting points, not tuned values — see `tools/dedup.py`'s calibration
  note. A live run against ~2,000 real documents (HN + EDGAR + App Store,
  2026-08-07) produced 479 merges, 1 novel, and 1,534 gray-zone
  classifications: multilingual-e5-base's cosine similarity for short text is
  compressed enough that the gray zone catches far more than a naive read of
  the thresholds would suggest. This needs real tuning before the gray-zone
  rate is taken as a health signal one way or the other — don't read too much
  into any single run's ratio, including this one.
- These heuristics are intentional stand-ins for Phase 4's LLM deep-dive, not
  bugs. Don't "fix" them by inventing more brittle keyword rules without that
  context — extend them only if a concrete false-positive/negative is found in
  real data.
- `tools/scoring_tools.py:compute_composite_score` skips the momentum/market-
  proof blend entirely for `insufficient_history` opportunities, scoring on
  market proof alone instead of diluting it by `COMPOSITE_MARKET_PROOF_WEIGHT`
  (fixed 2026-08-07). The project's model is a SaaS factory that ships fast
  and needs to reach MRR quickly — a well-evidenced, brand-new opportunity
  must not be structurally capped at half its market-proof score just
  because it hasn't yet accumulated `MOMENTUM_MIN_BASELINE_DAYS` of daily
  history; "we don't know its momentum yet" is not the same claim as "it has
  no momentum," and the two must not score the same. Momentum still applies
  its full weight once real history exists.
- `tools/scope_classifier.py` (added 2026-08-07) is a keyword heuristic —
  narrow-scope words ("extension", "plugin", "cli", ...), broad-scope words
  ("platform", "all-in-one", "ecosystem", ...), and a count of named cloud/
  SaaS providers mentioned together (≥3 is itself a scope signal,
  independent of adjectives — verified against this project's own real
  data, a Product Hunt pitch naming six providers in one sentence) — that
  nudges `compute_composite_score` by up to `COMPOSITE_SCOPE_WEIGHT` (15
  points) toward narrow, solo-buildable ideas and away from full platforms.
  Deliberately a nudge, not a dominant factor: verified live against
  production data that it correctly boosts genuinely narrow pain_driven
  ideas (Chrome extensions, CLIs, calculators) by the intended amount, but
  15 points is nowhere near enough to outrank App Store arbitrage entries,
  whose market-proof scores structurally run far higher. If the goal is an
  automated top-20 that doesn't need hand-curation to remove full-platform
  arbitrage picks, the next lever is `tools/ranking.py`'s diversity/quota
  mechanism, not a bigger scope weight here — don't chase this by inflating
  `COMPOSITE_SCOPE_WEIGHT` without evidence it's the right lever.
- `tools/competitor_search.py:build_search_query` (fixed 2026-08-07) prefers
  a tagline (first line of a linked document's body) over the bare title,
  and strips dollar amounts/MRR-ARR jargon/HN narration words. Fixed after
  finding on real production data that a made-up brand name alone
  ("CloudQuell") searches as 0 matches (not "no competitors," just "nothing
  to search for"), and an HN title containing "$17K to $170K MRR" pulled in
  noise unrelated to the actual product.
- `tools/demand_signals.py` (added 2026-08-07) is a regex phrase-matcher —
  same zero-LLM, zero-ML philosophy as every other Phase 1-2 heuristic —
  detecting when evidence text *explicitly asks for something to exist*
  ("I wish there was...", "is there a tool for...", "alternative to X",
  "doesn't support Y") rather than merely getting attention. This is a
  different claim than momentum ("attention is growing") and nudges
  `compute_composite_score` by up to `COMPOSITE_DEMAND_WEIGHT` (20 points),
  same additive-nudge pattern as `scope_classifier.py`. Willingness-to-pay
  phrases ("I'd pay $50/mo for this") are deliberately excluded from this
  nudge's own score — they're a monetary claim, so they feed `proof_events`/
  market proof instead (see `agents/scoring_agent.py:_sync_proof_events`),
  the same bucket as disclosed revenue, rather than being double-counted
  across two scoring channels for one piece of evidence.
- `collectors/github_issues.py`'s default search query adds `comments:>0`
  (fixed 2026-08-07) after finding on real ingested data that most open,
  enhancement-labeled issues with zero comments are repo maintenance or
  AI-coding-agent busywork, not real user requests — verified live that
  this one qualifier drops matching volume by roughly three orders of
  magnitude for a single day's window. Honestly incomplete: a one-off
  self-reply still passes, and it's a precision/recall trade, not a fix —
  see the module's own docstring for why `reactions:>N` (a stronger quality
  signal) isn't the default despite being stronger: a freshly created issue
  hasn't had time to accumulate reactions the way an older one has, so it
  trades badly against this connector's daily incremental ingestion window.

## Environment variables

See `.env.example` for the full list with defaults, or `HOW_TO_RUN.md` for
the same list grouped by purpose with setup instructions for each credential.
Required with no default: `DATABASE_URL`, `EDGAR_USER_AGENT`,
`WIKIPEDIA_USER_AGENT` (the latter two identify this project's automated
requests per source ToS, not API keys). Everything else has a code default
and only needs overriding to tune behavior or to opt into Phase 3
(`REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`/`REDDIT_USER_AGENT`,
`PRODUCTHUNT_ACCESS_TOKEN`) or Phase 4 (`ANTHROPIC_API_KEY`).

## Testing

- `pytest` — unit and connector-fixture tests need no network and no Docker.
- `pytest-socket` blocks all real sockets by default; only tests under
  `tests/integration/` touch a database, and only when
  `OPPORTUNITY_ENGINE_TEST_DATABASE_URL` is set (otherwise they're skipped) —
  they still never touch a real external API, only Postgres.
- **`OPPORTUNITY_ENGINE_TEST_DATABASE_URL` must point at a different database
  than `DATABASE_URL`.** Integration tests `TRUNCATE` every app table before
  each test (`tests/conftest.py:db_conn`) — agents commit internally by
  design (a connector's failure durably records its own `connector_runs`/
  `events` without losing other connectors' committed work in the same run),
  so rollback-based test isolation doesn't work here, and pointing the test
  database at your real data will destroy it. This happened once during this
  project's own build (a stray "Test opportunity" row ended up in real
  ingested data) — `opportunity_engine_test`, same Postgres instance,
  different database name, is the fix; see README.md.
- `mypy src/` must be clean (strict mode) — this bar applies to `src/`, not
  `tests/`, which use ordinary (non-strict) idiomatic test patterns.

## Acceptance criteria status

| # | Criterion | Status |
|---|---|---|
| 1 | Top-10 backlog **overlap** stays *under* 50% across 7 consecutive days (i.e. the backlog must churn — this is an anti-stagnation check, not a stability target) | Not testable in a unit test — inherently needs real multi-day production data. `scripts/measure_top10_turnover.sql` computes it once `backlog_snapshots` has 8+ days of history. |
| 2 | No semantic duplicate in the top-20 | `tests/unit/test_dedup_semantic.py` (synthetic vectors) + structural check in `tests/integration/test_ranking_agent.py`. |
| 3 | Every backlog item shows per-dimension score, strategy, sources, rank justification | `tests/integration/test_ranking_agent.py::test_backlog_row_is_fully_traceable_per_dimension_strategy_and_sources`. |
| 4 | Daily cost within budget, by model | The daily pipeline (`run-daily`) is $0 by construction — zero LLM calls. Phase 4's `deep-dive` is the only spend, capped by a pre-flight `BudgetExceeded` check (`DEFAULT_BUDGET_USD`) and fully logged per call in `opportunity_dossiers.cost_usd` and the `llm_call` event payload — `SELECT sum(cost_usd) FROM opportunity_dossiers` for a running total. |
| 5 | Full pipeline runs with zero LLM calls, produces an exploitable ranking | `tests/unit/test_architecture_no_llm_calls.py` (structural guard) + `tests/integration/test_ranking_agent.py::test_full_pipeline_with_zero_llm_calls_produces_an_exploitable_ranking` + a live end-to-end run against all 4 real APIs on 2026-08-07 (1,994 documents ingested, 872 scored, 664 rejected, 20-slot backlog produced). |
| 6 | An injected strong-momentum opportunity reaches the top 10 within 72h | `tests/unit/test_ranking_diversity.py` (pure ranking half) + `tests/integration/test_ranking_agent.py::test_strong_momentum_opportunity_reaches_top_ten_within_the_daily_cycle` (full momentum + ranking pipeline). |
| 7 | No Opus model calls appear anywhere | True by construction, at both the static and runtime layers: `tests/unit/test_architecture_no_llm_calls.py` greps `src/` for a `claude-opus-*`/`claude_opus_*` model-ID string (not the bare English word, so this file's own prose explaining the ban doesn't trip it) and fails if found; independently, `AnthropicProvider.ALLOWED_MODELS` rejects any non-allowlisted model string at call time regardless of what the static guard catches. |

## Out of scope (do not build speculatively)

All five phases from the original spec are implemented (see "Phase status"
above). Nothing beyond them is in scope without a new, explicit ask —
in particular:

- No batch API or prompt-caching-driven bulk LLM usage: Phase 4 is
  deliberately a single on-demand call per `deep-dive` invocation, not a
  bulk-dossier-generation feature. Building that without being asked is the
  over-design this project's owner has explicitly ruled out.
- No further connectors or signal-check agents beyond what's built (Stack
  Exchange, GitHub Issues, App Store reviews, Discourse forums, and the
  competitor-saturation check were all added 2026-08-07 on exactly this kind
  of real, current, explicitly-stated need), no additional DetectionStrategy
  beyond `pain_driven`/`arbitrage`, no new sanctioned interface beyond the
  four in rule #5, unless a real, current need is stated again.
- The later portfolio-pipeline components (Validation Engine, SaaS
  Generator, Marketing OS, Analytics Engine, Portfolio Manager, Exit
  Manager) remain out of scope entirely — this codebase only owes them the
  extension points already in place (schema-flexible `events.payload`, open
  `text` `proof_type`/`rejection_reason` columns), not pre-built
  infrastructure.
