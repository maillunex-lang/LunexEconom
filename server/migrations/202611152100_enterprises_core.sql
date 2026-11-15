-- V2-04 enterprises, inventory, idempotent requests, reports.
CREATE TABLE enterprises (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 owner_id bigint NOT NULL REFERENCES accounts(id),
 building_id text NOT NULL,
 px bigint NOT NULL, py bigint NOT NULL,
 x bigint NOT NULL, y bigint NOT NULL,
 width integer NOT NULL CHECK(width BETWEEN 1 AND 6),
 height integer NOT NULL CHECK(height BETWEEN 1 AND 6),
 city_id text REFERENCES world_cities(id),
 name text NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
 build_cost bigint NOT NULL CHECK(build_cost > 0),
 build_days integer NOT NULL CHECK(build_days > 0),
 upkeep_month bigint NOT NULL CHECK(upkeep_month >= 0),
 jobs integer NOT NULL CHECK(jobs >= 0),
 storage_capacity bigint NOT NULL CHECK(storage_capacity >= 0),
 started_day bigint NOT NULL CHECK(started_day >= 0),
 stage smallint NOT NULL DEFAULT 0 CHECK(stage BETWEEN 0 AND 4),
 running boolean NOT NULL DEFAULT true,
 staffing_bp integer NOT NULL DEFAULT 10000 CHECK(staffing_bp BETWEEN 0 AND 10000),
 load_bp integer NOT NULL DEFAULT 0 CHECK(load_bp BETWEEN 0 AND 10000),
 recipe_id text,
 min_stock jsonb NOT NULL DEFAULT '{}'::jsonb,
 wear integer NOT NULL DEFAULT 0 CHECK(wear BETWEEN 0 AND 100),
 last_production_day bigint NOT NULL DEFAULT -1,
 sold_at timestamptz,
 build_request_id text NOT NULL UNIQUE,
 build_transfer_id bigint NOT NULL REFERENCES ledger_transfers(id),
 last_month bigint NOT NULL DEFAULT -1,
 FOREIGN KEY(px,py) REFERENCES world_parcels(px,py)
);
CREATE INDEX enterprises_owner_idx ON enterprises(owner_id) WHERE sold_at IS NULL;
CREATE TABLE enterprise_inventory (
 enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 product_id text NOT NULL,
 quantity bigint NOT NULL CHECK(quantity >= 0),
 quality integer NOT NULL CHECK(quality BETWEEN 1 AND 100),
 output_carry bigint NOT NULL DEFAULT 0 CHECK(output_carry BETWEEN 0 AND 9999),
 input_carry bigint NOT NULL DEFAULT 0 CHECK(input_carry BETWEEN 0 AND 9999),
 PRIMARY KEY(enterprise_id,product_id)
);
CREATE TABLE enterprise_daily_load (
 enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 day_index bigint NOT NULL CHECK(day_index >= 0),
 load_bp integer NOT NULL CHECK(load_bp BETWEEN 0 AND 10000),
 PRIMARY KEY(enterprise_id,day_index)
);
CREATE TABLE enterprise_month_reports (
 enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 month_index bigint NOT NULL CHECK(month_index >= 0),
 revenue bigint NOT NULL DEFAULT 0,
 expenses bigint NOT NULL DEFAULT 0 CHECK(expenses >= 0),
 average_load_bp integer NOT NULL DEFAULT 0 CHECK(average_load_bp BETWEEN 0 AND 10000),
 inventory jsonb NOT NULL DEFAULT '{}'::jsonb,
 wear integer NOT NULL,
 PRIMARY KEY(enterprise_id,month_index)
);
CREATE TABLE enterprise_sale_requests (
 request_id text PRIMARY KEY,
 enterprise_id bigint NOT NULL UNIQUE REFERENCES enterprises(id),
 owner_id bigint NOT NULL REFERENCES accounts(id),
 price bigint NOT NULL CHECK(price > 0),
 transfer_id bigint NOT NULL REFERENCES ledger_transfers(id)
);
