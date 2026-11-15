-- A2 immutable per-game-day metrics, idempotent growth switches, bounded error diagnostics.
CREATE TABLE IF NOT EXISTS admin_daily_stats (
 day_index bigint PRIMARY KEY CHECK (day_index>=0),
 players bigint NOT NULL CHECK (players>=0),
 enterprises bigint NOT NULL CHECK (enterprises>=0),
 player_money bigint NOT NULL,
 retail_revenue bigint NOT NULL CHECK (retail_revenue>=0),
 vat bigint NOT NULL CHECK (vat>=0),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS admin_growth_requests (
 request_id text PRIMARY KEY CHECK(length(request_id) BETWEEN 8 AND 128),
 city_id text NOT NULL REFERENCES world_cities(id),
 enabled boolean NOT NULL,
 reason text NOT NULL CHECK(length(reason) BETWEEN 1 AND 500),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS admin_error_log (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 origin text NOT NULL CHECK(origin IN ('tick','api')),
 day_index bigint,
 error_code text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(origin,day_index)
);
