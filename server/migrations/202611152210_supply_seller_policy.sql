-- Opt-in seller consent: never allow implicit stock liquidation.
-- Independent migration preserves already-applied checksums.
CREATE TABLE supply_seller_policy (
 enterprise_id bigint PRIMARY KEY REFERENCES enterprises(id) ON DELETE CASCADE,
 allow_direct_sales boolean NOT NULL DEFAULT false,
 allow_city_market boolean NOT NULL DEFAULT false,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX supply_seller_market_idx ON supply_seller_policy(enterprise_id)
 WHERE allow_city_market;
