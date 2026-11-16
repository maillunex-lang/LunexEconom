-- SEC1: durable refresh rotation family; old pre-upgrade sessions are isolated.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS refresh_family_id uuid;
CREATE INDEX IF NOT EXISTS sessions_refresh_family_idx ON sessions(refresh_family_id);