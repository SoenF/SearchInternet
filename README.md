# Opportunity Engine

Detects, scores, and ranks micro-SaaS opportunities from free/official signal
sources into a persistent, deduplicated backlog. See `CLAUDE.md` for the full
architecture, schema, and phase status — this file is just the quick start.

## Setup

```bash
docker compose up -d db
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # edit if needed
python -m opportunity_engine.cli.main migrate
```

The embedding model (`intfloat/multilingual-e5-base`, ~1GB) downloads from
Hugging Face on first use and is cached under `~/.cache/huggingface`. Warm the
cache once, with network available, before running dedup or the embedding
tests offline:

```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-base')"
```

## Run

```bash
python -m opportunity_engine.cli.main run-daily
```

## Test

```bash
pytest                 # unit + connector fixture tests, no network, no DB required
mypy src/
```

To also run integration tests against a real (local Docker) Postgres, first
create a **separate** test database on the same instance -- integration
tests truncate every app table before each test, so this must never be the
same database as `DATABASE_URL`:

```bash
docker compose exec db psql -U opportunity_engine -d postgres -c \
  "CREATE DATABASE opportunity_engine_test OWNER opportunity_engine;"
export OPPORTUNITY_ENGINE_TEST_DATABASE_URL=postgresql://opportunity_engine:opportunity_engine@localhost:5433/opportunity_engine_test
pytest tests/integration
```
