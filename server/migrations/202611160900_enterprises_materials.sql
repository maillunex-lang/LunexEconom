-- CAT1 additive: unpaid foundation projects can await both inputs without fake ledger transfers.
-- Existing enterprise rows and prepaid stages retain their original values.
ALTER TABLE enterprises ALTER COLUMN build_transfer_id DROP NOT NULL;
ALTER TABLE enterprise_build_waits DROP CONSTRAINT enterprise_build_waits_stage_check;
ALTER TABLE enterprise_build_waits ADD CONSTRAINT enterprise_build_waits_stage_check CHECK(stage BETWEEN 0 AND 3);
ALTER TABLE enterprise_build_waits ADD COLUMN reason text NOT NULL DEFAULT 'money'
  CHECK (reason IN ('money','materials'));
ALTER TABLE enterprise_build_waits ADD COLUMN missing jsonb NOT NULL DEFAULT '{}'::jsonb
  CHECK (jsonb_typeof(missing) = 'object');
