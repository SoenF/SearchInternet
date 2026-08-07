-- Phase 3+: free, rule-based competitor-saturation signal (GitHub repo search
-- + npm registry search by opportunity title keywords, zero LLM). Checked
-- once per opportunity, not re-checked daily -- "does a competitor already
-- exist" doesn't change fast enough to justify repeated API calls against a
-- growing backlog. competitor_checked_at IS NULL is how agents/
-- competitor_check_agent.py finds opportunities still needing a check.
ALTER TABLE opportunities
    ADD COLUMN competitor_match_count int,
    ADD COLUMN competitor_matches     jsonb,
    ADD COLUMN competitor_checked_at  timestamptz;
