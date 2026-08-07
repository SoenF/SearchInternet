# How to run the Opportunity Engine

This is the operational guide: setup, credentials, every CLI command, cost
expectations, and a realistic day-to-day workflow across all five phases.
For architecture, schema, and the rules this codebase must not violate, see
`CLAUDE.md` instead — this file assumes that context and doesn't repeat it.

Phase 1-2 (connectors, storage, dedup, scoring, ranking) need nothing but
Docker and Python — no API keys, no money. Phase 3's Reddit/Product Hunt
connectors and archive import are opt-in. Phase 4 (LLM deep-dive) is the
only thing that spends money, and only when you explicitly run it. Phase 5
(rejection feedback) requires no commands at all — it's a passive effect of
Phase 2's scoring.

## 1. Prerequisites

- Python 3.12 (the venv must be built with 3.12 specifically — see below)
- Docker, for Postgres + pgvector
- ~1.5GB free disk for the local embedding model (`intfloat/multilingual-e5-base`)
- Optional, only if you want them: an Anthropic API key (Phase 4), a Reddit
  "script" app's client id/secret (Phase 3), a Product Hunt developer token
  (Phase 3)

## 2. First-time setup

```bash
docker compose up -d db

/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env   # edit — see the env var reference below
python -m opportunity_engine.cli.main migrate
```

Warm the embedding model cache once, with network available, before running
`dedup` or anything that depends on it offline:

```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-base')"
```

It downloads to `~/.cache/huggingface` and is reused from there afterward —
`dedup`/`import-archive`/the embedding-dependent integration tests all work
without network once this step has run.

## 3. Environment variables

Full defaults live in `.env.example`; this groups them by what they're for.

### Required, no default

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string. |
| `EDGAR_USER_AGENT` | SEC EDGAR's fair-access policy requires a descriptive User-Agent with contact info — not an API key. |
| `WIKIPEDIA_USER_AGENT` | Same idea, for Wikimedia's API etiquette. |

### Phase 1-2 tuning (all have working code defaults)

`DISABLED_CONNECTORS`, `EMBEDDING_MODEL_NAME`, `EMBEDDING_DEVICE`,
`MOMENTUM_RECENT_DAYS`, `MOMENTUM_BASELINE_DAYS`, `MOMENTUM_MIN_BASELINE_DAYS`,
`DEDUP_MERGE_THRESHOLD`, `DEDUP_NOVEL_THRESHOLD`, `RESURFACE_SCORE_DELTA_PCT`,
`BACKLOG_TOP_N`, `BACKLOG_EXPLORATION_SHARE`, `BACKLOG_ARBITRAGE_QUOTA`,
`BACKLOG_MAX_CATEGORY_SHARE`. Only override these to deliberately tune
behavior — see `CLAUDE.md`'s "Known, deliberate limitations" section before
treating the dedup thresholds in particular as already-tuned values.

### Phase 3 — Reddit (opt-in)

| Variable | Purpose |
|---|---|
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | From a Reddit "script" app: create one at https://www.reddit.com/prefs/apps, type "script". |
| `REDDIT_USER_AGENT` | Reddit requires a descriptive one, e.g. `"OpportunityEngine/0.1 (contact: you@example.com)"`. |
| `REDDIT_SUBREDDITS` | Comma-separated. Defaults to `SaaS,Entrepreneur,smallbusiness,SideProject` if unset. |

Leave `REDDIT_CLIENT_ID` blank and the connector is silently skipped by
`collectors/registry.py` — no error, just absent from `ingest`/`run-daily`.

**ToS caveat**: Reddit's connector manifest carries `tos_status:
"review_needed"`, not `"compliant"`. Reddit's 2023 Data API Terms impose
commercial-use restrictions this project has not had legal review against.
Treat enabling Reddit as a deliberate decision, not a default — get that
review before depending on it for anything beyond local experimentation, and
especially before any of the later portfolio-pipeline phases resell or
publish anything derived from it.

### Phase 3 — Product Hunt (opt-in)

| Variable | Purpose |
|---|---|
| `PRODUCTHUNT_ACCESS_TOKEN` | A developer token from https://www.producthunt.com/v2/oauth/applications (Applications tab → your app → "Developer Token"). Every request needs one — there's no anonymous tier at all. |

Same silent-skip-if-blank behavior, and the same `tos_status: "review_needed"`
caveat as Reddit — see `CLAUDE.md`.

### Phase 4 — LLM deep-dive (opt-in, the only phase that spends money)

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Required only for the `deep-dive` command. Everything else in this project makes zero LLM calls, enforced structurally (see `CLAUDE.md` rule #9). |

### Test-only

| Variable | Purpose |
|---|---|
| `OPPORTUNITY_ENGINE_TEST_DATABASE_URL` | Must point at a **different** database than `DATABASE_URL` — integration tests `TRUNCATE` every app table before each test. Unset means integration tests are skipped, not failed. |

## 4. Phase 1-2: the free daily pipeline

```bash
python -m opportunity_engine.cli.main run-daily            # ingest -> dedup -> score -> rank
```

Or step by step (useful for debugging a specific stage):

```bash
python -m opportunity_engine.cli.main ingest --days 1       # HN, EDGAR, Wikipedia, App Store
python -m opportunity_engine.cli.main dedup                 # embed + merge/create opportunities
python -m opportunity_engine.cli.main score                 # gates + momentum + market proof + composite
python -m opportunity_engine.cli.main rank                  # write today's backlog_snapshots
```

Other Phase 1-2 commands:

```bash
# Watch a Wikipedia article for pageview momentum (corroborating evidence for
# an arbitrage candidate) -- usually seeded once you've spotted a candidate,
# not run on a schedule:
python -m opportunity_engine.cli.main track-topic ja.wikipedia インボイス制度 \
  --opportunity-id 42

# Upsert every enabled connector's manifest into the `connectors` table --
# harmless to run any time, `run-daily`'s `ingest` step already does this
# per-connector automatically:
python -m opportunity_engine.cli.main sync-connectors
```

View today's backlog directly:

```sql
SELECT rank, o.title, b.composite_score, b.strategy, b.category, b.is_exploration_slot
FROM backlog_snapshots b
JOIN opportunities o ON o.id = b.opportunity_id
WHERE b.window_end = CURRENT_DATE
ORDER BY rank;
```

Everything in this section costs nothing beyond your own compute — no API
keys, no LLM calls (`NoOpLLMProvider` would raise if anything tried).

## 5. Phase 3: Reddit, Product Hunt, and historical backfill

Once `REDDIT_CLIENT_ID`/`PRODUCTHUNT_ACCESS_TOKEN` are set, both connectors
join `ingest`/`run-daily` automatically — no separate command. Their
`reddit_post`/`producthunt_post` documents flow through the same
dedup/scoring/ranking pipeline as HN posts, tagged `pain_driven`.

### Historical Reddit archive import

Live daily ingestion only sees what's posted from today onward, so a
freshly-added subreddit starts with `insufficient_history` momentum
confidence until `MOMENTUM_MIN_BASELINE_DAYS` (28 by default) of real days
pass. `import-archive` fixes that in one shot by bulk-loading a historical
dump and backfilling `opportunity_daily_signal` day-by-day from it.

This project does not bundle or link to a specific dump file — Pushshift
lost official Reddit API access in 2023, and third-party mirrors of its
archives change over time. Obtain a Pushshift-format submissions dump
(`RS_*.zst`, or any plain NDJSON with the same per-line fields: `id`,
`subreddit`, `title`, `selftext`, `created_utc`, `permalink`, `url`, `score`,
`num_comments`) yourself, then:

```bash
python -m opportunity_engine.cli.main import-archive /path/to/RS_2025-01.zst \
  --subreddits SaaS,Entrepreneur,smallbusiness,SideProject
```

`--subreddits` is optional — omit it to import every subreddit in the dump
(only sensible for an already subreddit-scoped dump; a full Reddit-wide
monthly dump is large and mostly irrelevant to this project). The command
prints `lines_read`, `documents_stored`, `skipped_wrong_subreddit`,
`skipped_malformed`, and `opportunity_days_backfilled` when it finishes.

This is a manual, occasional operation — run it once per subreddit/period
you care about, not on a schedule. It needs the embedding model cached
(step 2) since it runs Phase 1-2's `dedup` internally.

## 6. Phase 4: on-demand LLM deep-dive

The only command in this project that spends real money, and only when you
run it — never from `run-daily`.

```bash
python -m opportunity_engine.cli.main deep-dive 42
```

Defaults to Haiku (`claude-haiku-4-5`) and a $3.30 per-dossier budget
ceiling (`DEFAULT_BUDGET_USD`, an approximate USD stand-in for the project's
"<3 EUR per dossier" target — Anthropic bills in USD). Escalating to Sonnet
requires a written reason demonstrating Haiku specifically failed:

```bash
python -m opportunity_engine.cli.main deep-dive 42 \
  --escalate --reason "Haiku's dossier missed the regulatory angle entirely on two attempts"
```

Output is the dossier's structured JSON (`summary`, `market_evidence`,
`buildability_assessment`, `vendability_assessment`, `key_risks`,
`recommendation`), plus the actual model and cost used. Every call is
persisted to `opportunity_dossiers` and logged as an `llm_call` event —
query `events WHERE event_type = 'llm_call'` for a running cost ledger.

**Cost expectations**, at the current pricing table in
`providers/llm_provider.py` ($1/$5 per MTok Haiku, $3/$15 per MTok Sonnet):
a typical opportunity's evidence (a handful of linked documents, a few
proof events) runs a few hundred to low thousands of input tokens plus up to
`MAX_OUTPUT_TOKENS=2000` output tokens — expect low cents per Haiku dossier,
and well under the $3.30 ceiling even on Sonnet. The pre-flight cost
estimate in `_estimate_cost_ceiling()` raises `BudgetExceeded` *before*
calling the API if a single opportunity's evidence is unusually large — this
is a safety net, not a guarantee of the final bill, which is only known
after the call returns.

**Opus is never reachable here or anywhere else in this codebase** — see
`CLAUDE.md` rule #9 and `providers/llm_provider.py`'s `ALLOWED_MODELS`.

Reserve `deep-dive` for opportunities you're seriously about to commit build
time to, not for browsing the backlog — it's the one place in this pipeline
where running it "just to see" has a real cost, however small.

## 7. Phase 5: rejection feedback

No command to run. Every time `score` (or `run-daily`) processes a
candidate, it checks whether the candidate's embedding sits near a
*previously rejected* opportunity's centroid and, if so, subtracts a penalty
from its composite score (`tools/feedback.py`, wired into
`agents/scoring_agent.py`). The effect compounds automatically as more
opportunities get rejected over time — nothing to configure beyond the
existing `DEDUP_MERGE_THRESHOLD`/`DEDUP_NOVEL_THRESHOLD` similarity
thresholds the penalty reuses. Check `score_history.inputs_snapshot ->
'rejection_penalty_points'` and `-> 'rejection_penalty_neighbors'` for why a
specific score included (or didn't include) a penalty.

## 8. A realistic weekly workflow

1. **Once, at setup**: steps 1-2 above, plus `import-archive` for any
   subreddit you already know you care about, if you have a dump.
2. **Daily** (cron, or by hand): `run-daily`. Takes minutes, costs nothing.
3. **Weekly**: skim the backlog query from section 4. For anything that's
   climbed into the top 10 and stayed novel (not a near-duplicate of
   something already rejected — check `rejection_penalty_points`), consider
   a `deep-dive`.
4. **Before committing build time to an opportunity**: run `deep-dive`
   (escalate to Sonnet only if Haiku's first dossier is visibly missing
   something specific). Read `key_risks` and `recommendation` before
   deciding, not just the score.
5. **Occasionally** (not scheduled, not CI): `scripts/refresh_fixtures.py`
   to check whether a live connector's response shape has drifted from its
   committed test fixture; `scripts/measure_top10_turnover.sql` once
   `backlog_snapshots` has 8+ days of history, to check acceptance
   criterion #1 (top-10 churn) against real data.
6. **If a connector looks stuck or empty**: check `connector_runs` (status,
   `items_fetched`/`items_stored`, `error_message`) and `events` — every
   ingestion/scoring/rejection/dossier decision is logged there.

## 9. Testing

```bash
pytest                 # unit + connector fixture tests -- no network, no DB
mypy src/               # strict mode; applies to src/, not tests/
ruff check .
ruff format --check .
```

To also run integration tests against a real (local Docker) Postgres, first
create a **separate** test database on the same instance:

```bash
docker compose exec db psql -U opportunity_engine -d postgres -c \
  "CREATE DATABASE opportunity_engine_test OWNER opportunity_engine;"
export OPPORTUNITY_ENGINE_TEST_DATABASE_URL=postgresql://opportunity_engine:opportunity_engine@localhost:5433/opportunity_engine_test
python -m opportunity_engine.cli.main migrate   # against the test DB too, once
pytest tests/integration
```

`pytest-socket` blocks all real sockets everywhere by default; integration
tests only ever reach the test Postgres, never a real external API or LLM —
`AnthropicProvider`/`RedditCollector`/`ProductHuntCollector` are always
exercised in tests through an injected fake client, never the real network
client. A few integration tests (dedup, archive import) additionally need
the embedding model cache from step 2 warmed first, or they skip themselves
with a clear message rather than failing.

## 10. Troubleshooting

- **`RuntimeError: missing required environment variable: ...`** — one of
  `DATABASE_URL`/`EDGAR_USER_AGENT`/`WIKIPEDIA_USER_AGENT` isn't set. These
  three have no default on purpose.
- **A connector is silently missing from `ingest`'s output** — for Reddit or
  Product Hunt, check that the relevant credential env var is actually set;
  for any connector, check it isn't listed in `DISABLED_CONNECTORS`.
- **Integration tests all skip** — `OPPORTUNITY_ENGINE_TEST_DATABASE_URL`
  isn't set. This is by design, not a failure.
- **Dedup/archive-import integration tests skip with an `OSError`** — the
  embedding model isn't cached yet; run the warm-up command in step 2.
- **`MigrationDriftError`** — an already-applied migration file's contents
  changed after the fact. Migrations in `migrations/` are append-only by
  convention; fix by adding a new migration, never by editing an applied one.
- **`deep-dive` raises `BudgetExceeded`** — that opportunity's linked
  evidence is unusually large. Pass `--budget-usd` explicitly if you've
  reviewed the evidence and are fine with a higher ceiling.
