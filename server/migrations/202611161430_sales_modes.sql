-- V2-SALES-IMPL1: all quantities and payments are references, not duplicated inventory/ledger.
CREATE TABLE sales_policies (
 enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 product_id text NOT NULL,
 mode text NOT NULL CHECK(mode IN ('private','public','mixed','invited')),
 reserve_bp integer NOT NULL CHECK(reserve_bp BETWEEN 0 AND 10000),
 price bigint NOT NULL CHECK(price>0),
 effective_day bigint NOT NULL CHECK(effective_day>=0),
 version bigint NOT NULL CHECK(version>0),
 PRIMARY KEY(enterprise_id,product_id)
);
CREATE TABLE sales_policy_changes (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 product_id text NOT NULL,
 request_id text NOT NULL UNIQUE CHECK(length(request_id) BETWEEN 1 AND 100),
 owner_id bigint NOT NULL REFERENCES accounts(id),
 mode text NOT NULL CHECK(mode IN ('private','public','mixed','invited')),
 reserve_bp integer NOT NULL CHECK(reserve_bp BETWEEN 0 AND 10000),
 price bigint NOT NULL CHECK(price>0),
 effective_day bigint NOT NULL CHECK(effective_day>=0),
 version bigint NOT NULL CHECK(version>0),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(enterprise_id,product_id,version)
);
CREATE INDEX sales_policy_changes_due_idx ON sales_policy_changes(effective_day,enterprise_id,product_id);
CREATE TABLE sales_invites (
 enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 product_id text NOT NULL,
 buyer_owner_id bigint NOT NULL REFERENCES accounts(id),
 active boolean NOT NULL DEFAULT true,
 PRIMARY KEY(enterprise_id,product_id,buyer_owner_id)
);
CREATE TABLE sales_contract_reservations (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 request_id text NOT NULL UNIQUE CHECK(length(request_id) BETWEEN 1 AND 100),
 seller_enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 buyer_enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 product_id text NOT NULL,
 volume bigint NOT NULL CHECK(volume>0),
 reserved_remaining bigint NOT NULL CHECK(reserved_remaining>=0 AND reserved_remaining<=volume),
 delivered bigint NOT NULL DEFAULT 0 CHECK(delivered>=0),
 start_day bigint NOT NULL CHECK(start_day>=0),
 end_day bigint NOT NULL CHECK(end_day>=start_day),
 price bigint NOT NULL CHECK(price>0),
 status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','fulfilled','expired')),
 CHECK(seller_enterprise_id<>buyer_enterprise_id),
 CHECK(delivered+reserved_remaining<=volume)
);
CREATE INDEX sales_contracts_seller_idx ON sales_contract_reservations(seller_enterprise_id,product_id,start_day,end_day) WHERE status='active';
CREATE TABLE sales_daily_offers (
 seller_enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 product_id text NOT NULL,
 day_index bigint NOT NULL CHECK(day_index>=0),
 city_id text NOT NULL REFERENCES world_cities(id),
 frozen_stock bigint NOT NULL CHECK(frozen_stock>=0),
 own_quota bigint NOT NULL DEFAULT 0 CHECK(own_quota>=0),
 contract_quota bigint NOT NULL DEFAULT 0 CHECK(contract_quota>=0),
 spot_quota bigint NOT NULL DEFAULT 0 CHECK(spot_quota>=0),
 mode text NOT NULL CHECK(mode IN ('private','public','mixed','invited')),
 price bigint NOT NULL CHECK(price>0),
 quality integer NOT NULL CHECK(quality BETWEEN 1 AND 100),
 PRIMARY KEY(seller_enterprise_id,product_id,day_index),
 CHECK(own_quota+contract_quota+spot_quota<=frozen_stock)
);
CREATE TABLE sales_daily_allocations (
 seller_enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 buyer_enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 product_id text NOT NULL,
 day_index bigint NOT NULL CHECK(day_index>=0),
 source text NOT NULL CHECK(source IN ('own','contract','spot')),
 ordered bigint NOT NULL CHECK(ordered>=0),
 shipped bigint NOT NULL CHECK(shipped>=0 AND shipped<=ordered),
 unfilled bigint NOT NULL CHECK(unfilled>=0),
 receipt text UNIQUE,
 PRIMARY KEY(seller_enterprise_id,buyer_enterprise_id,product_id,day_index,source),
 CHECK(shipped+unfilled=ordered)
);
CREATE TABLE sales_reliability_30d (
 enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 product_id text NOT NULL,
 day_index bigint NOT NULL CHECK(day_index>=0),
 ordered bigint NOT NULL CHECK(ordered>=0),
 fulfilled bigint NOT NULL CHECK(fulfilled>=0 AND fulfilled<=ordered),
 PRIMARY KEY(enterprise_id,product_id,day_index)
);
CREATE TABLE sales_metrics_daily (
 seller_enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 product_id text NOT NULL,
 day_index bigint NOT NULL CHECK(day_index>=0),
 offered bigint NOT NULL CHECK(offered>=0),
 shipped bigint NOT NULL CHECK(shipped>=0),
 unfilled bigint NOT NULL CHECK(unfilled>=0),
 revenue bigint NOT NULL CHECK(revenue>=0),
 PRIMARY KEY(seller_enterprise_id,product_id,day_index)
);
CREATE TABLE sales_purchase_receipts (
 request_id text PRIMARY KEY CHECK(length(request_id) BETWEEN 1 AND 100),
 buyer_enterprise_id bigint NOT NULL REFERENCES enterprises(id),
 seller_enterprise_id bigint NOT NULL REFERENCES enterprises(id),
 product_id text NOT NULL,
 quantity bigint NOT NULL CHECK(quantity>0),
 unit_price bigint NOT NULL CHECK(unit_price>=0),
 day_index bigint NOT NULL CHECK(day_index>=0),
 shipment_request_id text NOT NULL UNIQUE REFERENCES shipments(request_id),
 contract_id bigint REFERENCES sales_contract_reservations(id)
);

CREATE TABLE sales_day_receipts (day_index bigint PRIMARY KEY CHECK(day_index>=0));
