CREATE TABLE raw_documents (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connector_name text NOT NULL REFERENCES connectors(name),
    external_id    text NOT NULL,          -- source's own id (objectID, accession no, "us:topfree:...:date")
    doc_type       text NOT NULL,          -- 'hn_ask' | 'hn_show' | 'edgar_formd' | 'app_store_ranking' |
                                            -- 'wikipedia_pageviews_series'
    fetched_at     timestamptz NOT NULL,
    published_at   timestamptz,
    source_url     text,
    title          text,
    body           text,
    country_code   text,                   -- 'us' | 'jp' | 'kr' | 'br' for app store rows
    category       text,
    content_hash   text NOT NULL,
    raw_json       jsonb NOT NULL,
    UNIQUE (connector_name, external_id)
);
CREATE INDEX ix_raw_documents_hash ON raw_documents (content_hash);
CREATE INDEX ix_raw_documents_connector_fetched ON raw_documents (connector_name, fetched_at DESC);
CREATE INDEX ix_raw_documents_published ON raw_documents (published_at);
