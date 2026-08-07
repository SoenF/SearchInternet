CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE connectors (
    name                text PRIMARY KEY,          -- e.g. 'hackernews_algolia'
    source_description  text NOT NULL,
    source_url          text NOT NULL,
    quota_description   text NOT NULL,
    tos_url             text NOT NULL,
    tos_status          text NOT NULL,              -- 'compliant' | 'review_needed' | 'unknown'
    last_verified       date NOT NULL,
    enabled             boolean NOT NULL DEFAULT true,  -- mirrors config, for observability/audit only
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE connector_runs (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connector_name text NOT NULL REFERENCES connectors(name),
    started_at     timestamptz NOT NULL,
    finished_at    timestamptz,
    status         text NOT NULL,     -- 'success' | 'partial' | 'failure'
    items_fetched  int NOT NULL DEFAULT 0,
    items_stored   int NOT NULL DEFAULT 0,
    request_count  int NOT NULL DEFAULT 0,
    cost_usd       numeric(10, 4) NOT NULL DEFAULT 0,  -- always 0 in phase 1-2; schema ready for phase 4
    error_message  text
);
CREATE INDEX ix_connector_runs_name_started ON connector_runs (connector_name, started_at DESC);
