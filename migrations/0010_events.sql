-- Append-only: the trigger below rejects any UPDATE/DELETE outright. This is the
-- single event log all agents communicate history through (never each other
-- directly). "payload" is deliberately schema-flexible jsonb so future event
-- types (phase 4 'llm_call', phase 5 'human_feedback', ...) need no migration.
CREATE TABLE events (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at    timestamptz NOT NULL DEFAULT now(),
    event_type     text NOT NULL,     -- 'document_ingested' | 'opportunity_created' |
                                       -- 'opportunity_created_gray_zone_review' | 'opportunity_merged' |
                                       -- 'opportunity_rejected' | 'opportunity_scored' | 'opportunity_proposed' | ...
    opportunity_id bigint REFERENCES opportunities(id),
    connector_name text,
    payload        jsonb NOT NULL DEFAULT '{}',
    actor          text NOT NULL DEFAULT 'system'
);
CREATE INDEX ix_events_type_time ON events (event_type, occurred_at DESC);
CREATE INDEX ix_events_opportunity ON events (opportunity_id, occurred_at DESC)
    WHERE opportunity_id IS NOT NULL;

CREATE OR REPLACE FUNCTION forbid_events_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'events is append-only: % not allowed', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER events_no_update BEFORE UPDATE ON events
    FOR EACH ROW EXECUTE FUNCTION forbid_events_mutation();
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION forbid_events_mutation();
