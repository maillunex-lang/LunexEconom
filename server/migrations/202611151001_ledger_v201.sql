ALTER TABLE ledger_accounts ADD COLUMN IF NOT EXISTS account_key text UNIQUE;
ALTER TABLE ledger_accounts ADD COLUMN IF NOT EXISTS allow_negative boolean NOT NULL DEFAULT false;
ALTER TABLE ledger_accounts ADD CONSTRAINT ledger_nonnegative_check CHECK (allow_negative OR balance >= 0);
ALTER TABLE ledger_entries DROP CONSTRAINT IF EXISTS ledger_entries_amount_check;
ALTER TABLE ledger_entries ALTER COLUMN amount DROP NOT NULL;
ALTER TABLE ledger_entries ALTER COLUMN amount SET NOT NULL;
INSERT INTO ledger_accounts(kind,account_key,allow_negative)
SELECT 'system', 'system:' || name, true
FROM unnest(ARRAY['treasury','market','bank','upkeep','escrow']) AS name
ON CONFLICT (account_key) DO NOTHING;
CREATE INDEX IF NOT EXISTS ledger_entries_account_idx ON ledger_entries(account_id, transfer_id);
CREATE INDEX IF NOT EXISTS ledger_transfers_time_idx ON ledger_transfers(created_at DESC, id DESC);
