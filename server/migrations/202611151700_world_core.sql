-- World V2-03: sparse edits, deterministic base world, transactional land ownership.
CREATE TABLE IF NOT EXISTS world_cities (
    id text PRIMARY KEY,
    level smallint NOT NULL DEFAULT 1 CHECK(level BETWEEN 1 AND 6),
    population bigint NOT NULL CHECK(population>=0),
    base_population bigint NOT NULL CHECK(base_population>=0),
    last_growth_month bigint NOT NULL DEFAULT -1,
    growth_enabled boolean NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS world_occupied_cells (
    x bigint NOT NULL,
    y bigint NOT NULL,
    city_id text NOT NULL REFERENCES world_cities(id),
    building_ref text NOT NULL CHECK(length(building_ref)>0),
    PRIMARY KEY(x,y)
);
CREATE INDEX IF NOT EXISTS world_occupied_city_idx ON world_occupied_cells(city_id);
CREATE TABLE IF NOT EXISTS world_roads (
    x bigint NOT NULL,
    y bigint NOT NULL,
    builder_id bigint REFERENCES accounts(id),
    PRIMARY KEY(x,y)
);
CREATE TABLE IF NOT EXISTS world_terrain_edits (
    x bigint NOT NULL,
    y bigint NOT NULL,
    terrain text NOT NULL CHECK(terrain IN ('ground','tree','water')),
    PRIMARY KEY(x,y)
);
CREATE TABLE IF NOT EXISTS world_parcels (
    px bigint NOT NULL,
    py bigint NOT NULL,
    city_id text REFERENCES world_cities(id),
    owner_kind text NOT NULL CHECK(owner_kind IN ('city','state','company','player')),
    owner_ref text NOT NULL CHECK(length(owner_ref)>0),
    paid_amount bigint NOT NULL DEFAULT 0 CHECK(paid_amount>=0),
    PRIMARY KEY(px,py)
);
CREATE INDEX IF NOT EXISTS world_parcels_owner_idx ON world_parcels(owner_kind,owner_ref);
CREATE TABLE IF NOT EXISTS world_land_requests (
    request_id text PRIMARY KEY CHECK(length(request_id) BETWEEN 1 AND 128),
    px bigint NOT NULL,
    py bigint NOT NULL,
    buyer_id bigint NOT NULL REFERENCES accounts(id),
    amount bigint NOT NULL CHECK(amount>0),
    transfer_id bigint NOT NULL REFERENCES ledger_transfers(id),
    UNIQUE(px,py)
);
CREATE TABLE IF NOT EXISTS world_chunk_versions (
    cx bigint NOT NULL,
    cy bigint NOT NULL,
    version bigint NOT NULL DEFAULT 1 CHECK(version>=1),
    PRIMARY KEY(cx,cy)
);
CREATE TABLE IF NOT EXISTS world_events (
    version bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind text NOT NULL,
    city_id text REFERENCES world_cities(id),
    cx bigint,
    cy bigint,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS world_events_city_idx ON world_events(city_id,version);
CREATE TABLE IF NOT EXISTS world_growth_receipts (
    city_id text NOT NULL REFERENCES world_cities(id),
    month_index bigint NOT NULL,
    old_level smallint NOT NULL,
    new_level smallint NOT NULL,
    PRIMARY KEY(city_id,month_index),
    CHECK(new_level=old_level+1)
);
