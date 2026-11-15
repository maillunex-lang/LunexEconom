ALTER TABLE accounts ADD COLUMN IF NOT EXISTS email text;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS is_blocked boolean NOT NULL DEFAULT false;
CREATE UNIQUE INDEX IF NOT EXISTS accounts_username_ci_unique ON accounts(lower(username));
CREATE UNIQUE INDEX IF NOT EXISTS accounts_email_unique ON accounts (lower(email)) WHERE email IS NOT NULL;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS refresh_hash text UNIQUE;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS refresh_expires_at timestamptz;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS revoked_at timestamptz;
UPDATE sessions SET revoked_at=now() WHERE refresh_hash IS NULL AND revoked_at IS NULL;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_seen_at timestamptz;
CREATE TABLE IF NOT EXISTS auth_attempts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ip inet,
    identifier text NOT NULL,
    action text NOT NULL,
    attempted_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_attempts_rate_idx ON auth_attempts(action, identifier, attempted_at);
CREATE INDEX IF NOT EXISTS auth_attempts_ip_idx ON auth_attempts(action, ip, attempted_at);
CREATE TABLE IF NOT EXISTS runtime_revisions (
    revision bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key text NOT NULL,
    old_value jsonb,
    new_value jsonb NOT NULL,
    apply_at text NOT NULL CHECK(apply_at IN ('now','next_month')),
    effective_month bigint,
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor text NOT NULL,
    action text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS presence (
    account_id bigint PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    client_version text NOT NULL DEFAULT '',
    seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS game_ticks (
    day_index bigint PRIMARY KEY,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    duration_ms bigint,
    handlers jsonb NOT NULL DEFAULT '[]'::jsonb,
    error text,
    completed boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS platform_clock (
    id smallint PRIMARY KEY CHECK(id = 1),
    epoch timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS presence_daily_peak (
    day date PRIMARY KEY,
    peak integer NOT NULL DEFAULT 0
);
