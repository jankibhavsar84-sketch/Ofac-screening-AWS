BEGIN;

ALTER TABLE IF EXISTS actimize_screening_type_mappings
  ADD COLUMN IF NOT EXISTS "Search_Definition_ID" VARCHAR(50);

ALTER TABLE IF EXISTS actimize_screening_type_mappings
  ADD COLUMN IF NOT EXISTS search_definition_name VARCHAR(255) NOT NULL DEFAULT '';

ALTER TABLE IF EXISTS actimize_screening_type_mappings
  ADD COLUMN IF NOT EXISTS "Screening_Type" VARCHAR(10);

ALTER TABLE IF EXISTS actimize_screening_type_mappings
  ALTER COLUMN "Search_Definition_ID" TYPE VARCHAR(50)
  USING CASE
    WHEN "Search_Definition_ID" IS NULL THEN NULL
    ELSE LEFT("Search_Definition_ID", 50)
  END;

ALTER TABLE IF EXISTS actimize_screening_type_mappings
  ALTER COLUMN search_definition_name TYPE VARCHAR(255)
  USING LEFT(COALESCE(search_definition_name, ''), 255);

ALTER TABLE IF EXISTS actimize_screening_type_mappings
  ALTER COLUMN "Screening_Type" TYPE VARCHAR(10)
  USING CASE
    WHEN "Screening_Type" IS NULL THEN NULL
    ELSE LEFT("Screening_Type", 10)
  END;

COMMIT;
