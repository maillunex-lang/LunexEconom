-- Owner spending ledger (Grok1two, round 3). Idempotent: postgres_db.SCHEMA creates the same table at startup.
-- Reversibility: DROP TABLE eco_owner_spend (loses the history of monthly owner spending, nothing else depends on it).
CREATE TABLE IF NOT EXISTS eco_owner_spend (
 owner TEXT NOT NULL, month_index BIGINT NOT NULL, amount BIGINT NOT NULL,
 PRIMARY KEY(owner, month_index)
);
