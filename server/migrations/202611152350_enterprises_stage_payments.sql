-- V2-04d: staged construction, paid-stage ledger references and stalled projects.
-- Additive: all preexisting enterprises were fully charged in V2-04.
ALTER TABLE enterprises
  ADD COLUMN stage_progress_days bigint NOT NULL DEFAULT 0
    CHECK (stage_progress_days >= 0);

CREATE TABLE enterprise_stage_payments (
  enterprise_id bigint NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
  stage smallint NOT NULL CHECK(stage BETWEEN 0 AND 3),
  amount bigint NOT NULL CHECK(amount >= 0),
  request_id text UNIQUE,
  transfer_id bigint REFERENCES ledger_transfers(id),
  paid_at timestamptz NOT NULL DEFAULT now(),
  legacy_prepaid boolean NOT NULL DEFAULT false,
  PRIMARY KEY (enterprise_id,stage),
  CONSTRAINT enterprise_stage_payment_source CHECK (
    (legacy_prepaid AND request_id IS NULL AND transfer_id IS NULL)
    OR (NOT legacy_prepaid AND request_id IS NOT NULL
        AND ((amount = 0 AND transfer_id IS NULL)
             OR (amount > 0 AND transfer_id IS NOT NULL)))
  )
);

CREATE TABLE enterprise_build_waits (
  enterprise_id bigint PRIMARY KEY REFERENCES enterprises(id) ON DELETE CASCADE,
  stage smallint NOT NULL CHECK(stage BETWEEN 1 AND 3),
  amount bigint NOT NULL CHECK(amount >= 0),
  first_wait_day bigint NOT NULL CHECK(first_wait_day >= 0),
  last_wait_day bigint NOT NULL CHECK(last_wait_day >= first_wait_day),
  waiting_days bigint NOT NULL CHECK(waiting_days >= 1),
  first_waited_at timestamptz NOT NULL DEFAULT now()
);

-- Legacy payments: one full ledger transfer already exists, never duplicate it.
-- Mark four stages as prepaid; the original single build_transfer_id is retained.
INSERT INTO enterprise_stage_payments
    (enterprise_id,stage,amount,legacy_prepaid)
SELECT e.id, s.stage,
       CASE s.stage
         WHEN 0 THEN e.build_cost * 300 / 1000
         WHEN 1 THEN e.build_cost * 400 / 1000
         WHEN 2 THEN e.build_cost * 200 / 1000
         ELSE e.build_cost
           - (e.build_cost * 300 / 1000)
           - (e.build_cost * 400 / 1000)
           - (e.build_cost * 200 / 1000)
       END,
       true
FROM enterprises e CROSS JOIN generate_series(0,3) AS s(stage);

-- Approximate already elapsed time for unfinished legacy construction so its
-- schedule is not reset to zero on rollout. Fully operational rows are unchanged.
UPDATE enterprises
SET stage_progress_days = LEAST(
    GREATEST(
      0,
      last_production_day - started_day + 1
      - CASE stage
          WHEN 0 THEN 0
          WHEN 1 THEN build_days * 250 / 1000
          WHEN 2 THEN build_days * 600 / 1000
          WHEN 3 THEN build_days * 900 / 1000
          ELSE build_days
        END
    ),
    CASE stage
      WHEN 0 THEN build_days * 250 / 1000
      WHEN 1 THEN build_days * 600 / 1000 - build_days * 250 / 1000
      WHEN 2 THEN build_days * 900 / 1000 - build_days * 600 / 1000
      WHEN 3 THEN build_days - build_days * 900 / 1000
      ELSE 0
    END
)
WHERE stage < 4;
