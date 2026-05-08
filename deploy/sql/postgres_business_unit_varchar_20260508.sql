BEGIN;

ALTER TABLE IF EXISTS business_units
  ALTER COLUMN business_unit_code TYPE VARCHAR(50)
  USING LEFT(COALESCE(business_unit_code, ''), 50);

ALTER TABLE IF EXISTS business_units
  ALTER COLUMN business_unit_name TYPE VARCHAR(255)
  USING LEFT(COALESCE(business_unit_name, ''), 255);

ALTER TABLE IF EXISTS job_metadata
  ALTER COLUMN business_unit_code TYPE VARCHAR(50)
  USING CASE
    WHEN business_unit_code IS NULL THEN NULL
    ELSE LEFT(business_unit_code, 50)
  END;

ALTER TABLE IF EXISTS daily_schedules
  ALTER COLUMN business_unit_code TYPE VARCHAR(50)
  USING CASE
    WHEN business_unit_code IS NULL THEN NULL
    ELSE LEFT(business_unit_code, 50)
  END;

ALTER TABLE IF EXISTS user_business_units
  ALTER COLUMN business_unit_code TYPE VARCHAR(50)
  USING LEFT(COALESCE(business_unit_code, ''), 50);

COMMIT;
