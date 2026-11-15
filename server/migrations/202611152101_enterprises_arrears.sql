-- V2-04b: per-enterprise unpaid salary/upkeep accrual (draft).
CREATE TABLE enterprise_arrears (
 enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
 month_index bigint NOT NULL CHECK(month_index >= 1),
 amount bigint NOT NULL CHECK(amount > 0),
 consecutive_months integer NOT NULL CHECK(consecutive_months >= 1),
 paid_at timestamptz,
 PRIMARY KEY(enterprise_id,month_index)
);
CREATE INDEX enterprise_arrears_unpaid_idx ON enterprise_arrears(enterprise_id) WHERE paid_at IS NULL;
