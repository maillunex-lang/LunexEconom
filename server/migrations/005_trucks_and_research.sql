-- Company lorries and research projects (Grok6). Idempotent: postgres_db.SCHEMA creates the same tables.
-- Reversibility: DROP TABLE truck_trips; DROP TABLE company_trucks; DROP TABLE company_research;
-- No other table references them. Existing worlds keep the legacy per-km tariff until a company buys a lorry.
CREATE TABLE IF NOT EXISTS company_trucks (
 owner TEXT PRIMARY KEY, units INTEGER NOT NULL, capacity_each INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS truck_trips (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, origin TEXT NOT NULL, destination TEXT NOT NULL,
 product TEXT NOT NULL, qty BIGINT NOT NULL, trucks INTEGER NOT NULL,
 depart_month BIGINT NOT NULL, arrive_month BIGINT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_research (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, track TEXT NOT NULL, cost BIGINT NOT NULL,
 start_month BIGINT NOT NULL, ready_month BIGINT NOT NULL, status TEXT NOT NULL
);
