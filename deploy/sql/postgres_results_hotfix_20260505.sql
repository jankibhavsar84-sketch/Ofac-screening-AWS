BEGIN;

ALTER TABLE job_items
  ADD COLUMN IF NOT EXISTS user_id TEXT;

UPDATE job_items ji
SET user_id = j.user_id
FROM jobs j
WHERE ji.job_id = j.job_id
  AND ji.user_id IS DISTINCT FROM j.user_id;

CREATE INDEX IF NOT EXISTS idx_job_items_user_recent
  ON job_items(user_id, updated_at DESC, job_seq_id DESC, item_key);

CREATE INDEX IF NOT EXISTS idx_job_items_user_status
  ON job_items(user_id, parsed_status);

CREATE OR REPLACE FUNCTION set_job_items_user_id()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.user_id IS NULL OR BTRIM(NEW.user_id) = '' THEN
    SELECT user_id
    INTO NEW.user_id
    FROM jobs
    WHERE job_id = NEW.job_id;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_job_items_set_user_id ON job_items;

CREATE TRIGGER trg_job_items_set_user_id
BEFORE INSERT OR UPDATE OF job_id ON job_items
FOR EACH ROW
EXECUTE FUNCTION set_job_items_user_id();

CREATE OR REPLACE FUNCTION sync_job_items_user_id_from_jobs()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF OLD.user_id IS DISTINCT FROM NEW.user_id THEN
    UPDATE job_items
    SET user_id = NEW.user_id
    WHERE job_id = NEW.job_id;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_jobs_sync_job_items_user_id ON jobs;

CREATE TRIGGER trg_jobs_sync_job_items_user_id
AFTER UPDATE OF user_id ON jobs
FOR EACH ROW
EXECUTE FUNCTION sync_job_items_user_id_from_jobs();

COMMIT;
