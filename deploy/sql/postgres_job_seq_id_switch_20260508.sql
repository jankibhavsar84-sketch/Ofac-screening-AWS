BEGIN;

-- 1) Ensure bigint sequence key exists and is populated on jobs.
ALTER TABLE IF EXISTS jobs
  ADD COLUMN IF NOT EXISTS job_seq_id BIGINT;

CREATE SEQUENCE IF NOT EXISTS jobs_job_seq_id_seq;

ALTER TABLE IF EXISTS jobs
  ALTER COLUMN job_seq_id SET DEFAULT nextval('jobs_job_seq_id_seq');

UPDATE jobs
SET job_seq_id = nextval('jobs_job_seq_id_seq')
WHERE job_seq_id IS NULL;

SELECT setval(
  'jobs_job_seq_id_seq',
  GREATEST(COALESCE((SELECT MAX(job_seq_id) FROM jobs), 1), 1),
  true
);

ALTER TABLE IF EXISTS jobs
  ALTER COLUMN job_seq_id SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_job_seq_id
  ON jobs(job_seq_id);

-- 2) Ensure job_items tracks job_seq_id and is FK'd by bigint.
ALTER TABLE IF EXISTS job_items
  ADD COLUMN IF NOT EXISTS job_seq_id BIGINT;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'job_items'
      AND column_name = 'job_id'
  ) THEN
    UPDATE job_items ji
    SET job_seq_id = j.job_seq_id
    FROM jobs j
    WHERE ji.job_id = j.job_id
      AND (ji.job_seq_id IS NULL OR ji.job_seq_id <> j.job_seq_id);
  END IF;
END $$;

ALTER TABLE IF EXISTS job_items
  ALTER COLUMN job_seq_id SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_job_items_job_seq_id'
  ) THEN
    ALTER TABLE job_items
      ADD CONSTRAINT fk_job_items_job_seq_id
      FOREIGN KEY (job_seq_id)
      REFERENCES jobs(job_seq_id)
      ON DELETE CASCADE;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_job_items_job_seq_sort
  ON job_items(job_seq_id, updated_at DESC, item_key);

CREATE INDEX IF NOT EXISTS idx_job_items_job_seq_parsed_status
  ON job_items(job_seq_id, parsed_status);

-- 3) Add bigint job_seq_id references to related tables and backfill.
ALTER TABLE IF EXISTS job_metadata
  ADD COLUMN IF NOT EXISTS job_seq_id BIGINT;
ALTER TABLE IF EXISTS job_schedule_notifications
  ADD COLUMN IF NOT EXISTS job_seq_id BIGINT;
ALTER TABLE IF EXISTS batch_file_uploads
  ADD COLUMN IF NOT EXISTS job_seq_id BIGINT;
ALTER TABLE IF EXISTS external_api_errors
  ADD COLUMN IF NOT EXISTS job_seq_id BIGINT;
ALTER TABLE IF EXISTS schedule_notifications
  ADD COLUMN IF NOT EXISTS job_seq_id BIGINT;
ALTER TABLE IF EXISTS schedule_record_state
  ADD COLUMN IF NOT EXISTS last_job_seq_id BIGINT;

-- Remove impossible parentless rows for strict one-to-one job tables.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'job_metadata'
      AND column_name = 'job_id'
  ) THEN
    DELETE FROM job_metadata m
    WHERE NOT EXISTS (
      SELECT 1
      FROM jobs j
      WHERE j.job_id = m.job_id
    );

    UPDATE job_metadata m
    SET job_seq_id = j.job_seq_id
    FROM jobs j
    WHERE m.job_id = j.job_id
      AND (m.job_seq_id IS NULL OR m.job_seq_id <> j.job_seq_id);
  END IF;

  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'job_schedule_notifications'
      AND column_name = 'job_id'
  ) THEN
    DELETE FROM job_schedule_notifications n
    WHERE NOT EXISTS (
      SELECT 1
      FROM jobs j
      WHERE j.job_id = n.job_id
    );

    UPDATE job_schedule_notifications n
    SET job_seq_id = j.job_seq_id
    FROM jobs j
    WHERE n.job_id = j.job_id
      AND (n.job_seq_id IS NULL OR n.job_seq_id <> j.job_seq_id);
  END IF;

  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'batch_file_uploads'
      AND column_name = 'job_id'
  ) THEN
    UPDATE batch_file_uploads b
    SET job_seq_id = j.job_seq_id
    FROM jobs j
    WHERE b.job_id = j.job_id
      AND (b.job_seq_id IS NULL OR b.job_seq_id <> j.job_seq_id);
  END IF;

  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'schedule_notifications'
      AND column_name = 'job_id'
  ) THEN
    UPDATE schedule_notifications n
    SET job_seq_id = j.job_seq_id
    FROM jobs j
    WHERE n.job_id = j.job_id
      AND (n.job_seq_id IS NULL OR n.job_seq_id <> j.job_seq_id);
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
    UPDATE external_api_errors e
    SET job_seq_id = j.job_seq_id
    FROM jobs j
    WHERE e.job_id = j.job_id
      AND (e.job_seq_id IS NULL OR e.job_seq_id <> j.job_seq_id);
  END IF;
END $$;

UPDATE schedule_record_state s
SET last_job_seq_id = j.job_seq_id
FROM jobs j
WHERE s.last_job_id = j.job_id
  AND (s.last_job_seq_id IS NULL OR s.last_job_seq_id <> j.job_seq_id);

ALTER TABLE IF EXISTS job_metadata
  ALTER COLUMN job_seq_id SET NOT NULL;
ALTER TABLE IF EXISTS job_schedule_notifications
  ALTER COLUMN job_seq_id SET NOT NULL;

-- 4) Enforce bigint foreign keys.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_job_metadata_job_seq_id') THEN
    ALTER TABLE job_metadata
      ADD CONSTRAINT fk_job_metadata_job_seq_id
      FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_job_schedule_notifications_job_seq_id') THEN
    ALTER TABLE job_schedule_notifications
      ADD CONSTRAINT fk_job_schedule_notifications_job_seq_id
      FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_batch_file_uploads_job_seq_id') THEN
    ALTER TABLE batch_file_uploads
      ADD CONSTRAINT fk_batch_file_uploads_job_seq_id
      FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE SET NULL;
  END IF;
END $$;

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
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_schedule_notifications_job_seq_id') THEN
    ALTER TABLE schedule_notifications
      ADD CONSTRAINT fk_schedule_notifications_job_seq_id
      FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_schedule_record_state_last_job_seq_id') THEN
    ALTER TABLE schedule_record_state
      ADD CONSTRAINT fk_schedule_record_state_last_job_seq_id
      FOREIGN KEY (last_job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE SET NULL;
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_job_metadata_job_seq_id
  ON job_metadata(job_seq_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_job_schedule_notifications_job_seq_id
  ON job_schedule_notifications(job_seq_id);
CREATE INDEX IF NOT EXISTS idx_batch_file_uploads_job_seq_id
  ON batch_file_uploads(job_seq_id);
CREATE INDEX IF NOT EXISTS idx_external_api_errors_job_seq_id
  ON external_api_errors(job_seq_id);
CREATE INDEX IF NOT EXISTS idx_schedule_notifications_job_seq_id
  ON schedule_notifications(job_seq_id);
CREATE INDEX IF NOT EXISTS idx_schedule_record_state_last_job_seq_id
  ON schedule_record_state(last_job_seq_id);

CREATE OR REPLACE FUNCTION set_schedule_record_last_job_seq_id()
RETURNS trigger AS $$
BEGIN
  IF NEW.last_job_seq_id IS NULL AND NEW.last_job_id IS NOT NULL THEN
    SELECT j.job_seq_id
    INTO NEW.last_job_seq_id
    FROM jobs j
    WHERE j.job_id = NEW.last_job_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_schedule_record_state_set_last_job_seq_id ON schedule_record_state;
CREATE TRIGGER trg_schedule_record_state_set_last_job_seq_id
BEFORE INSERT OR UPDATE OF last_job_id, last_job_seq_id ON schedule_record_state
FOR EACH ROW
EXECUTE FUNCTION set_schedule_record_last_job_seq_id();

-- 6) Final cutover: remove legacy text job_id columns from child tables.
DROP TRIGGER IF EXISTS trg_job_metadata_set_job_seq_id ON job_metadata;
DROP TRIGGER IF EXISTS trg_job_schedule_notifications_set_job_seq_id ON job_schedule_notifications;
DROP TRIGGER IF EXISTS trg_batch_file_uploads_set_job_seq_id ON batch_file_uploads;
DROP TRIGGER IF EXISTS trg_external_api_errors_set_job_seq_id ON external_api_errors;
DROP TRIGGER IF EXISTS trg_schedule_notifications_set_job_seq_id ON schedule_notifications;
DROP FUNCTION IF EXISTS set_related_job_seq_id_from_job_id();

ALTER TABLE IF EXISTS job_items
  DROP CONSTRAINT IF EXISTS job_items_pkey;
ALTER TABLE IF EXISTS job_items
  DROP CONSTRAINT IF EXISTS job_items_job_id_fkey;
ALTER TABLE IF EXISTS job_items
  DROP COLUMN IF EXISTS job_id;
ALTER TABLE IF EXISTS job_items
  ADD CONSTRAINT job_items_pkey PRIMARY KEY (job_seq_id, item_key);

ALTER TABLE IF EXISTS job_metadata
  DROP CONSTRAINT IF EXISTS job_metadata_pkey;
ALTER TABLE IF EXISTS job_metadata
  DROP CONSTRAINT IF EXISTS fk_job_metadata_job_id;
ALTER TABLE IF EXISTS job_metadata
  DROP COLUMN IF EXISTS job_id;
ALTER TABLE IF EXISTS job_metadata
  ADD CONSTRAINT job_metadata_pkey PRIMARY KEY (job_seq_id);

ALTER TABLE IF EXISTS job_schedule_notifications
  DROP CONSTRAINT IF EXISTS job_schedule_notifications_pkey;
ALTER TABLE IF EXISTS job_schedule_notifications
  DROP CONSTRAINT IF EXISTS fk_job_schedule_notifications_job_id;
ALTER TABLE IF EXISTS job_schedule_notifications
  DROP COLUMN IF EXISTS job_id;
ALTER TABLE IF EXISTS job_schedule_notifications
  ADD CONSTRAINT job_schedule_notifications_pkey PRIMARY KEY (job_seq_id);

ALTER TABLE IF EXISTS batch_file_uploads
  DROP CONSTRAINT IF EXISTS fk_batch_file_uploads_job_id;
ALTER TABLE IF EXISTS batch_file_uploads
  DROP COLUMN IF EXISTS job_id;

ALTER TABLE IF EXISTS schedule_notifications
  DROP CONSTRAINT IF EXISTS fk_schedule_notifications_job_id;
ALTER TABLE IF EXISTS schedule_notifications
  DROP COLUMN IF EXISTS job_id;

COMMIT;
