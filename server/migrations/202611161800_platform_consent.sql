-- V2-CONSENT1, non-destructive schema
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS consent_version text;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS consent_at timestamptz;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS delete_requested_at timestamptz;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
CREATE TABLE IF NOT EXISTS account_consents (
 account_id bigint NOT NULL REFERENCES accounts(id),
 version text NOT NULL,
 accepted_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(account_id,version)
);
CREATE INDEX IF NOT EXISTS account_delete_pending_idx ON accounts(delete_requested_at) WHERE deleted_at IS NULL AND delete_requested_at IS NOT NULL;
