CREATE TABLE proof_events (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    opportunity_id  bigint NOT NULL REFERENCES opportunities(id),
    proof_type      text NOT NULL,     -- 'edgar_funding' | 'disclosed_revenue' | 'app_store_ranking';
                                        -- open text, not an enum, so phase 3+ types (e.g. 'real_transaction',
                                        -- 'reported_arr_public') need no migration
    raw_document_id bigint REFERENCES raw_documents(id),
    observed_at     date NOT NULL,
    weight          numeric(6, 2) NOT NULL,
    confidence      numeric(3, 2) NOT NULL,
    extracted_value jsonb,             -- e.g. {"amount_usd": 1500000} or {"rank": 12, "country": "jp"}
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_proof_events_opportunity ON proof_events (opportunity_id, observed_at DESC);
CREATE INDEX ix_proof_events_type ON proof_events (proof_type);
