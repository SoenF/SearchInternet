-- Phase 4: on-demand LLM deep-dive dossiers. One row per generation (not
-- one row per opportunity) so re-running a dossier -- e.g. after escalating
-- from Haiku to Sonnet -- keeps prior attempts for comparison rather than
-- overwriting them; `opportunities.description` is not touched by this
-- table and stays whatever Phase 1-2 populated it with.
CREATE TABLE opportunity_dossiers (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    opportunity_id   bigint NOT NULL REFERENCES opportunities(id),
    model            text NOT NULL,
    purpose          text NOT NULL,          -- e.g. 'phase4_dossier'
    escalation_reason text,                  -- required (by the CLI) whenever model != the Haiku default
    content          jsonb NOT NULL,         -- the structured dossier itself
    input_tokens     int NOT NULL,
    output_tokens    int NOT NULL,
    cost_usd         numeric(10, 4) NOT NULL,
    latency_ms       numeric(10, 1) NOT NULL,
    generated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_opportunity_dossiers_opportunity ON opportunity_dossiers (opportunity_id, generated_at DESC);
