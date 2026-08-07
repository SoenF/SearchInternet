-- This table *is* the ranking cache. Its key includes the time window by
-- construction, so a query for "today's backlog" can never silently return a
-- stale/frozen ranking from an earlier window. It also doubles as the raw data
-- source for the (production-only, not unit-testable) 7-day top-10-turnover
-- measurement in scripts/measure_top10_turnover.sql.
CREATE TABLE backlog_snapshots (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    generated_at        timestamptz NOT NULL DEFAULT now(),
    window_start        date NOT NULL,
    window_end          date NOT NULL,
    rank                int NOT NULL,
    opportunity_id      bigint NOT NULL REFERENCES opportunities(id),
    composite_score     numeric(6, 2) NOT NULL,
    strategy            detection_strategy_name NOT NULL,
    category            text,
    is_exploration_slot boolean NOT NULL DEFAULT false,
    UNIQUE (window_start, window_end, rank)
);
CREATE INDEX ix_backlog_snapshots_opportunity ON backlog_snapshots (opportunity_id, generated_at DESC);
