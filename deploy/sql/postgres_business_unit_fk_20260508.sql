BEGIN;

-- Safety cleanup before adding FK constraints.
UPDATE daily_schedules d
SET business_unit_code = NULL
WHERE d.business_unit_code IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM business_units b
    WHERE b.business_unit_code = d.business_unit_code
  );

UPDATE job_metadata jm
SET business_unit_code = NULL
WHERE jm.business_unit_code IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM business_units b
    WHERE b.business_unit_code = jm.business_unit_code
  );

DELETE FROM user_business_units ubu
WHERE NOT EXISTS (
  SELECT 1
  FROM business_units b
  WHERE b.business_unit_code = ubu.business_unit_code
);

ALTER TABLE IF EXISTS daily_schedules
  DROP CONSTRAINT IF EXISTS fk_daily_schedules_business_unit_code;
ALTER TABLE IF EXISTS daily_schedules
  ADD CONSTRAINT fk_daily_schedules_business_unit_code
  FOREIGN KEY (business_unit_code)
  REFERENCES business_units(business_unit_code)
  ON UPDATE CASCADE
  ON DELETE RESTRICT;

ALTER TABLE IF EXISTS job_metadata
  DROP CONSTRAINT IF EXISTS fk_job_metadata_business_unit_code;
ALTER TABLE IF EXISTS job_metadata
  ADD CONSTRAINT fk_job_metadata_business_unit_code
  FOREIGN KEY (business_unit_code)
  REFERENCES business_units(business_unit_code)
  ON UPDATE CASCADE
  ON DELETE RESTRICT;

ALTER TABLE IF EXISTS user_business_units
  DROP CONSTRAINT IF EXISTS fk_user_business_units_business_unit_code;
ALTER TABLE IF EXISTS user_business_units
  ADD CONSTRAINT fk_user_business_units_business_unit_code
  FOREIGN KEY (business_unit_code)
  REFERENCES business_units(business_unit_code)
  ON UPDATE CASCADE
  ON DELETE RESTRICT;

COMMIT;
