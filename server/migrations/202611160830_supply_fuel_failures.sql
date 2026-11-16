-- V2-FUEL1: failure reasons without modifying existing daily-needs columns.
CREATE TABLE supply_fuel_failures (
 enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 product_id text NOT NULL,
 day_index bigint NOT NULL CHECK(day_index >= 0),
 reason text NOT NULL CHECK(reason IN ('fuel_missing','fuel_unaffordable')),
 PRIMARY KEY (enterprise_id,product_id,day_index)
);
