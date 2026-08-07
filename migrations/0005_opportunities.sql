CREATE TYPE opportunity_status AS ENUM
    ('candidate', 'qualified', 'in_build', 'launched', 'sold', 'rejected');
CREATE TYPE detection_strategy_name AS ENUM ('arbitrage', 'pain_driven');

CREATE TABLE opportunities (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title                   text NOT NULL,
    description             text,
    category                text,
    primary_strategy        detection_strategy_name NOT NULL,
    status                  opportunity_status NOT NULL DEFAULT 'candidate',
    rejection_reason        text,      -- '<gate>:<rule_name>' convention, e.g. 'arbitrage:no_barrier_identified';
                                       -- deliberately text, not an enum, so the rule set can grow without
                                       -- an ALTER TYPE migration per new rule. NULL unless status = 'rejected'.
    rejection_detail        jsonb,     -- evidence dict for the rule that fired
    centroid_embedding      vector(768),
    centroid_updated_at     timestamptz,
    current_score           numeric(6, 2),
    current_score_breakdown jsonb,
    last_proposed_at        timestamptz,
    last_proposed_score     numeric(6, 2),
    first_seen_at           timestamptz NOT NULL DEFAULT now(),
    last_seen_at            timestamptz NOT NULL DEFAULT now(),
    last_scored_at          timestamptz,
    related_opportunity_id  bigint REFERENCES opportunities(id),  -- gray-zone dedup cross-reference
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_opportunities_status ON opportunities (status);
CREATE INDEX ix_opportunities_strategy_category ON opportunities (primary_strategy, category);
CREATE INDEX ix_opportunities_score_active ON opportunities (current_score DESC)
    WHERE status IN ('candidate', 'qualified');   -- partial index matching the ranking hot path
CREATE INDEX ix_opportunities_centroid_hnsw ON opportunities
    USING hnsw (centroid_embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

ALTER TABLE tracked_topics
    ADD CONSTRAINT fk_tracked_topics_opportunity
    FOREIGN KEY (added_by_opportunity_id) REFERENCES opportunities(id);
