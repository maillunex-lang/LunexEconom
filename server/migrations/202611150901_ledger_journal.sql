CREATE TABLE IF NOT EXISTS ledger_accounts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner_id bigint REFERENCES accounts(id),
    kind text NOT NULL,
    balance bigint NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ledger_transfers (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ledger_entries (
    transfer_id bigint NOT NULL REFERENCES ledger_transfers(id),
    account_id bigint NOT NULL REFERENCES ledger_accounts(id),
    amount bigint NOT NULL CHECK(amount <> 0),
    PRIMARY KEY(transfer_id,account_id)
);
