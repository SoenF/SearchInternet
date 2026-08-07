CREATE TABLE score_history (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    opportunity_id        bigint NOT NULL REFERENCES opportunities(id),
    computed_at           timestamptz NOT NULL DEFAULT now(),
    window_end            date NOT NULL,       -- "as of" date used for the momentum computation
    momentum_score        numeric(6, 2),
    momentum_confidence   text NOT NULL,       -- 'ok' | 'insufficient_history'
    market_proof_score    numeric(6, 2) NOT NULL,
    buildability_pass     boolean NOT NULL,
    buildability_reasons  jsonb NOT NULL,
    vendability_pass      boolean NOT NULL,
    vendability_reasons   jsonb NOT NULL,
    barrier_pass          boolean,             -- NULL unless primary_strategy = 'arbitrage'
    barrier_evidence      jsonb,
    composite_score       numeric(6, 2),       -- NULL if any gate failed (= rejected)
    strategy              detection_strategy_name NOT NULL,
    inputs_snapshot       jsonb NOT NULL       -- full traceable inputs, for post-hoc "why this score" queries
);
CREATE INDEX ix_score_history_opportunity ON score_history (opportunity_id, computed_at DESC);
