-- Raw per-channel counts only, never a pre-mixed composite: normalization and
-- channel weighting happen at read time in tools/scoring_tools.py, so the
-- weighting can change without a backfill of this table.
CREATE TABLE opportunity_daily_signal (
    opportunity_id     bigint NOT NULL REFERENCES opportunities(id),
    signal_date        date NOT NULL,
    mention_count      int,      -- distinct HN raw_documents linked that day
    pageview_count     bigint,   -- summed tracked_topics pageviews that day
    app_rank_best      int,      -- best (lowest) chart rank observed that day, any tracked country
    edgar_filing_count int,      -- Form D filings linked that day
    PRIMARY KEY (opportunity_id, signal_date)
);
CREATE INDEX ix_daily_signal_date ON opportunity_daily_signal (signal_date);
