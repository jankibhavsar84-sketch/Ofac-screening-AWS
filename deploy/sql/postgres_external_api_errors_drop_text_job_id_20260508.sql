-- Remove legacy text job_id usage from external_api_errors and keep only bigint job_seq_id reference.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'external_api_errors'
      AND column_name = 'job_id'
  ) THEN
    UPDATE external_api_errors e
    SET job_seq_id = j.job_seq_id
    FROM jobs j
    WHERE e.job_seq_id IS NULL
      AND e.job_id = j.job_id;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_external_api_errors_job_id') THEN
    ALTER TABLE external_api_errors
      DROP CONSTRAINT fk_external_api_errors_job_id;
  END IF;
END $$;

DROP TRIGGER IF EXISTS trg_external_api_errors_set_job_seq_id ON external_api_errors;

DROP INDEX IF EXISTS idx_external_api_errors_job_item;
CREATE INDEX IF NOT EXISTS idx_external_api_errors_job_item
  ON external_api_errors(job_seq_id, item_key, created_at);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_external_api_errors_job_seq_id') THEN
    ALTER TABLE external_api_errors
      ADD CONSTRAINT fk_external_api_errors_job_seq_id
      FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'external_api_errors'
      AND column_name = 'job_id'
  ) THEN
    ALTER TABLE external_api_errors
      DROP COLUMN job_id;
  END IF;
END $$;
