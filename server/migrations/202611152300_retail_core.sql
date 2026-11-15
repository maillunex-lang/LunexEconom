-- V2-06 retail M1. All additive; catalog balance values draft.
CREATE TABLE retail_cells (
 enterprise_id bigint NOT NULL REFERENCES enterprises(id),
 cell_index integer NOT NULL CHECK(cell_index BETWEEN 0 AND 255),
 product_id text NOT NULL,
 supply_link_slot smallint CHECK(supply_link_slot BETWEEN 1 AND 3),
 price bigint NOT NULL CHECK(price BETWEEN 1 AND 9223372036854775807),
 min_stock bigint NOT NULL DEFAULT 0 CHECK(min_stock >= 0),
 PRIMARY KEY (enterprise_id,cell_index)
);
CREATE INDEX retail_cells_product_idx ON retail_cells(product_id,enterprise_id);
CREATE TABLE retail_sales_daily (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 enterprise_id bigint NOT NULL REFERENCES enterprises(id),
 cell_index integer NOT NULL CHECK(cell_index >= 0),
 product_id text NOT NULL,
 day_index bigint NOT NULL CHECK(day_index >= 0),
 city_id text NOT NULL REFERENCES world_cities(id),
 district_id integer,
 income_layer smallint NOT NULL DEFAULT 0 CHECK(income_layer BETWEEN 0 AND 3),
 quantity bigint NOT NULL CHECK(quantity >= 0),
 price bigint NOT NULL CHECK(price > 0),
 revenue bigint NOT NULL CHECK(revenue >= 0),
 rating smallint NOT NULL CHECK(rating BETWEEN 0 AND 100),
 vat_bp integer NOT NULL CHECK(vat_bp BETWEEN 0 AND 10000),
 UNIQUE NULLS NOT DISTINCT(enterprise_id,cell_index,day_index,district_id,income_layer)
);
CREATE INDEX retail_sales_date_idx ON retail_sales_daily(enterprise_id,day_index);
CREATE TABLE retail_alerts (
 enterprise_id bigint NOT NULL REFERENCES enterprises(id),
 product_id text NOT NULL,
 day_index bigint NOT NULL CHECK(day_index >= 0),
 alert_type text NOT NULL CHECK(alert_type IN ('low_stock','out_of_stock')),
 PRIMARY KEY(enterprise_id,product_id,day_index,alert_type)
);
CREATE TABLE retail_receipts (
 day_index bigint PRIMARY KEY CHECK(day_index>=0)
);
CREATE TABLE retail_month_receipts (
 enterprise_id bigint NOT NULL REFERENCES enterprises(id),
 month_index bigint NOT NULL CHECK(month_index>=0),
 revenue bigint NOT NULL CHECK(revenue>=0),
 vat bigint NOT NULL CHECK(vat>=0),
 paid boolean NOT NULL DEFAULT false,
 PRIMARY KEY(enterprise_id,month_index)
);
