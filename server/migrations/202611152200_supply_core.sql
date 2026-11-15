-- V2-05 supply, city market and port; all economic parameters balance: draft.
CREATE TABLE supply_links (
 enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 product_id text NOT NULL,
 slot smallint NOT NULL CHECK(slot BETWEEN 1 AND 3),
 source_type text NOT NULL CHECK(source_type IN ('enterprise','market','port')),
 source_enterprise_id bigint REFERENCES enterprises(id),
 share integer NOT NULL CHECK(share BETWEEN 1 AND 1000),
 priority smallint NOT NULL CHECK(priority BETWEEN 1 AND 3),
 max_price bigint NOT NULL CHECK(max_price >= 0),
 min_quality smallint NOT NULL CHECK(min_quality BETWEEN 0 AND 100),
 PRIMARY KEY(enterprise_id,product_id,slot),
 UNIQUE(enterprise_id,product_id,priority),
 CHECK ((source_type='enterprise') = (source_enterprise_id IS NOT NULL)),
 CHECK (source_enterprise_id IS NULL OR source_enterprise_id <> enterprise_id)
);
CREATE INDEX supply_links_supplier_idx ON supply_links(source_enterprise_id) WHERE source_enterprise_id IS NOT NULL;
CREATE TABLE supply_daily_needs (
 enterprise_id bigint NOT NULL REFERENCES enterprises(id),
 product_id text NOT NULL,
 day_index bigint NOT NULL CHECK(day_index>=0),
 requested bigint NOT NULL CHECK(requested>=0),
 linked bigint NOT NULL DEFAULT 0 CHECK(linked>=0),
 market_filled bigint NOT NULL DEFAULT 0 CHECK(market_filled>=0),
 port_ordered bigint NOT NULL DEFAULT 0 CHECK(port_ordered>=0),
 unfilled bigint NOT NULL DEFAULT 0 CHECK(unfilled>=0),
 PRIMARY KEY(enterprise_id,product_id,day_index)
);
CREATE TABLE market_prices (
 city_id text NOT NULL REFERENCES world_cities(id),
 product_id text NOT NULL,
 day_index bigint NOT NULL CHECK(day_index>=0),
 price bigint NOT NULL CHECK(price>=1),
 demand bigint NOT NULL CHECK(demand>=0),
 supply bigint NOT NULL CHECK(supply>=0),
 volume bigint NOT NULL CHECK(volume>=0),
 PRIMARY KEY(city_id,product_id,day_index)
);
CREATE TABLE shipments (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 request_id text NOT NULL UNIQUE,
 buyer_enterprise_id bigint NOT NULL REFERENCES enterprises(id),
 seller_enterprise_id bigint REFERENCES enterprises(id),
 source_type text NOT NULL CHECK(source_type IN ('enterprise','port')),
 product_id text NOT NULL,
 quantity bigint NOT NULL CHECK(quantity>0),
 quality integer NOT NULL CHECK(quality BETWEEN 1 AND 100),
 unit_price bigint NOT NULL CHECK(unit_price>=0),
 transport_cost bigint NOT NULL DEFAULT 0 CHECK(transport_cost>=0),
 dispatched_day bigint NOT NULL CHECK(dispatched_day>=0),
 arrival_day bigint NOT NULL CHECK(arrival_day>=dispatched_day),
 status text NOT NULL DEFAULT 'transit' CHECK(status IN ('transit','delivered','waiting_capacity')),
 transfer_id bigint REFERENCES ledger_transfers(id)
);
CREATE INDEX shipments_due_idx ON shipments(arrival_day,id) WHERE status<>'delivered';
CREATE TABLE supply_receipts (
 day_index bigint NOT NULL CHECK(day_index>=0),
 phase text NOT NULL CHECK(phase IN ('links','market')),
 PRIMARY KEY(day_index,phase)
);
