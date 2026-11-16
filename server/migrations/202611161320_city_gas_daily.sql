-- Optional city gas utility, persisted daily results double as idempotency receipts.
CREATE TABLE city_gas_daily (
    city_id text NOT NULL REFERENCES world_cities(id),
    day_index bigint NOT NULL CHECK(day_index >= 0),
    needed_m3 bigint NOT NULL CHECK(needed_m3 >= 0),
    bought_m3 bigint NOT NULL CHECK(bought_m3 >= 0),
    spent_rub bigint NOT NULL CHECK(spent_rub >= 0),
    short_m3 bigint NOT NULL CHECK(short_m3 >= 0),
    seller_enterprise_id bigint REFERENCES enterprises(id),
    PRIMARY KEY (city_id, day_index),
    CHECK (needed_m3 = bought_m3 + short_m3)
);
