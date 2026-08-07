-- Composite PK (not one-per-document) intentionally: lets an old and a new
-- embedding-model generation coexist during a future model migration, without
-- deleting history.
CREATE TABLE document_embeddings (
    raw_document_id bigint NOT NULL REFERENCES raw_documents(id),
    model_name      text NOT NULL,        -- 'intfloat/multilingual-e5-base'
    model_version   text NOT NULL,
    embedding       vector(768) NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (raw_document_id, model_name)
);
