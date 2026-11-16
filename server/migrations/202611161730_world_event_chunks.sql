-- MAP-RT1. New rows indexed transactionally; old rows stay untouched.
CREATE TABLE IF NOT EXISTS world_event_chunks (
 event_id bigint NOT NULL REFERENCES world_events(version) ON DELETE CASCADE,
 cx bigint NOT NULL, cy bigint NOT NULL,
 PRIMARY KEY (event_id,cx,cy)
);
CREATE INDEX IF NOT EXISTS world_event_chunks_lookup_idx ON world_event_chunks(cx,cy,event_id);
-- The primary key starts with event_id and supports journal retention.
