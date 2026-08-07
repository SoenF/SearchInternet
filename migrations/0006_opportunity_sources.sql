CREATE TABLE opportunity_sources (
    opportunity_id  bigint NOT NULL REFERENCES opportunities(id),
    raw_document_id bigint NOT NULL REFERENCES raw_documents(id),
    linked_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (opportunity_id, raw_document_id)
);
CREATE INDEX ix_opportunity_sources_doc ON opportunity_sources (raw_document_id);
