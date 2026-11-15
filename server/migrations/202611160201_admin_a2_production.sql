-- A2 exact daily output reconstructed from post-production load and carry.
CREATE TABLE admin_production_daily (
 day_index bigint NOT NULL CHECK(day_index>=0),
 product_id text NOT NULL,
 quantity bigint NOT NULL CHECK(quantity>=0),
 PRIMARY KEY(day_index,product_id)
);
CREATE TABLE admin_production_receipts (
 day_index bigint PRIMARY KEY CHECK(day_index>=0)
);
