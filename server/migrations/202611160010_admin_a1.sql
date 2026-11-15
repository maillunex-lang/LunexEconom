-- V2-ADM1: web admin sessions, role expansion and audit metadata.
ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_role_check;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS blocked_until timestamptz;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS block_reason text;
ALTER TABLE accounts ADD CONSTRAINT accounts_role_check CHECK (role IN ('player','developer','viewer','support','admin','owner'));
CREATE TABLE IF NOT EXISTS admin_sessions (
    token_hash text PRIMARY KEY,
    account_id bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    ip inet,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    absolute_expires_at timestamptz NOT NULL,
    revoked_at timestamptz
);
CREATE INDEX IF NOT EXISTS admin_sessions_account_idx ON admin_sessions(account_id, revoked_at);
ALTER TABLE audit ADD COLUMN IF NOT EXISTS actor_role text;
ALTER TABLE audit ADD COLUMN IF NOT EXISTS target_account_id bigint REFERENCES accounts(id) ON DELETE SET NULL;
ALTER TABLE audit ADD COLUMN IF NOT EXISTS ip inet;
ALTER TABLE audit ADD COLUMN IF NOT EXISTS old_value jsonb;
ALTER TABLE audit ADD COLUMN IF NOT EXISTS new_value jsonb;
CREATE INDEX IF NOT EXISTS audit_action_idx ON audit(action, created_at DESC);
CREATE INDEX IF NOT EXISTS audit_target_idx ON audit(target_account_id, created_at DESC);
