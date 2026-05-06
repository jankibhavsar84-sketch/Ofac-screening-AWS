-- PostgreSQL performance/type upgrade for large per-user result sets.
-- Safe to run multiple times.

BEGIN;

CREATE OR REPLACE FUNCTION _safe_to_timestamptz(p_value TEXT)
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
AS $$
BEGIN
  IF p_value IS NULL OR BTRIM(p_value) = '' THEN
    RETURN NULL;
  END IF;
  BEGIN
    RETURN p_value::timestamptz;
  EXCEPTION WHEN others THEN
    RETURN NULL;
  END;
END;
$$;

DO $$
DECLARE
  rec RECORD;
BEGIN
  FOR rec IN
    SELECT *
    FROM (
      VALUES
        ('jobs', 'created_at'),
        ('jobs', 'updated_at'),
        ('job_items', 'updated_at'),
        ('daily_schedules', 'created_at'),
        ('daily_schedules', 'last_run_at'),
        ('daily_schedules', 'next_run_at'),
        ('batch_file_uploads', 'created_at'),
        ('schedule_record_state', 'first_seen_at'),
        ('schedule_record_state', 'last_screened_at'),
        ('schedule_subscriptions', 'created_at'),
        ('schedule_subscriptions', 'updated_at'),
        ('job_schedule_notifications', 'created_at'),
        ('audit_events', 'created_at'),
        ('api_access_logs', 'created_at'),
        ('external_api_errors', 'created_at'),
        ('actimize_alert_callbacks', 'created_at'),
        ('schedule_notifications', 'created_at'),
        ('business_units', 'created_at'),
        ('business_units', 'updated_at'),
        ('user_business_units', 'created_at'),
        ('user_business_units', 'updated_at'),
        ('actimize_screening_type_mappings', 'created_at'),
        ('actimize_screening_type_mappings', 'updated_at')
    ) AS cols(table_name, column_name)
  LOOP
    IF EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = current_schema()
        AND table_name = rec.table_name
        AND column_name = rec.column_name
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I ALTER COLUMN %I TYPE timestamptz USING _safe_to_timestamptz(%I::text)',
        rec.table_name,
        rec.column_name,
        rec.column_name
      );
    END IF;
  END LOOP;
END
$$;

DO $$
DECLARE
  rec RECORD;
BEGIN
  FOR rec IN
    SELECT *
    FROM (
      VALUES
        ('jobs', 'created_at'),
        ('jobs', 'updated_at'),
        ('job_items', 'updated_at'),
        ('daily_schedules', 'created_at'),
        ('daily_schedules', 'next_run_at'),
        ('batch_file_uploads', 'created_at'),
        ('schedule_record_state', 'first_seen_at'),
        ('schedule_record_state', 'last_screened_at'),
        ('schedule_subscriptions', 'created_at'),
        ('schedule_subscriptions', 'updated_at'),
        ('job_schedule_notifications', 'created_at'),
        ('audit_events', 'created_at'),
        ('api_access_logs', 'created_at'),
        ('external_api_errors', 'created_at'),
        ('actimize_alert_callbacks', 'created_at'),
        ('schedule_notifications', 'created_at'),
        ('business_units', 'created_at'),
        ('business_units', 'updated_at'),
        ('user_business_units', 'created_at'),
        ('user_business_units', 'updated_at'),
        ('actimize_screening_type_mappings', 'created_at'),
        ('actimize_screening_type_mappings', 'updated_at')
    ) AS cols(table_name, column_name)
  LOOP
    IF EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = current_schema()
        AND table_name = rec.table_name
        AND column_name = rec.column_name
    ) THEN
      EXECUTE format('ALTER TABLE %I ALTER COLUMN %I SET DEFAULT now()', rec.table_name, rec.column_name);
    END IF;
  END LOOP;
END
$$;

ALTER TABLE job_items
  ADD COLUMN IF NOT EXISTS parsed_status VARCHAR(16);

UPDATE job_items
SET parsed_status = CASE
  WHEN status IN ('QUEUED', 'PROCESSING') THEN 'PENDING'
  WHEN status = 'FAILED' THEN 'FAILED'
  WHEN COALESCE(BTRIM(response_json), '') = '' THEN 'FAILED'
  WHEN UPPER(response_json) LIKE '%"ENGINE_MESSAGE":"PM"%' THEN 'POTENTIAL'
  WHEN UPPER(response_json) LIKE '%"ENGINE_MESSAGE":"NM"%' THEN 'CLEAR'
  ELSE 'CLEAR'
END
WHERE parsed_status IS NULL OR BTRIM(parsed_status) = '';

ALTER TABLE job_items
  ALTER COLUMN parsed_status SET DEFAULT 'PENDING';

ALTER TABLE job_items
  ALTER COLUMN parsed_status SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'job_items_parsed_status_check'
  ) THEN
    ALTER TABLE job_items
      ADD CONSTRAINT job_items_parsed_status_check
      CHECK (parsed_status IN ('CLEAR', 'POTENTIAL', 'PENDING', 'FAILED'));
  END IF;
END
$$;

ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS job_seq_id BIGINT;

CREATE SEQUENCE IF NOT EXISTS jobs_job_seq_id_seq;

ALTER TABLE jobs
  ALTER COLUMN job_seq_id SET DEFAULT nextval('jobs_job_seq_id_seq');

UPDATE jobs
SET job_seq_id = nextval('jobs_job_seq_id_seq')
WHERE job_seq_id IS NULL;

SELECT setval(
  'jobs_job_seq_id_seq',
  GREATEST(COALESCE((SELECT MAX(job_seq_id) FROM jobs), 1), 1),
  TRUE
);

ALTER TABLE jobs
  ALTER COLUMN job_seq_id SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_job_seq_id
  ON jobs(job_seq_id);

ALTER TABLE job_items
  ADD COLUMN IF NOT EXISTS job_seq_id BIGINT;

UPDATE job_items ji
SET job_seq_id = j.job_seq_id
FROM jobs j
WHERE ji.job_id = j.job_id
  AND (ji.job_seq_id IS NULL OR ji.job_seq_id <> j.job_seq_id);

ALTER TABLE job_items
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
END
$$;

CREATE OR REPLACE FUNCTION set_job_items_job_seq_id()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.job_seq_id IS NULL THEN
    SELECT job_seq_id
    INTO NEW.job_seq_id
    FROM jobs
    WHERE job_id = NEW.job_id;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_job_items_set_job_seq_id ON job_items;

CREATE TRIGGER trg_job_items_set_job_seq_id
BEFORE INSERT OR UPDATE OF job_id ON job_items
FOR EACH ROW
EXECUTE FUNCTION set_job_items_job_seq_id();

CREATE INDEX IF NOT EXISTS idx_jobs_user_sort
  ON jobs(user_id, updated_at DESC, created_at DESC, job_seq_id DESC);

CREATE INDEX IF NOT EXISTS idx_job_items_job_seq_sort
  ON job_items(job_seq_id, updated_at DESC, item_key);

CREATE INDEX IF NOT EXISTS idx_job_items_parsed_status
  ON job_items(parsed_status);

CREATE INDEX IF NOT EXISTS idx_job_items_job_seq_parsed_status
  ON job_items(job_seq_id, parsed_status);

DROP MATERIALIZED VIEW IF EXISTS mv_user_result_summary_counts;
DROP MATERIALIZED VIEW IF EXISTS mv_user_recent_results;

CREATE MATERIALIZED VIEW mv_user_recent_results AS
SELECT
  j.user_id,
  j.job_seq_id,
  ji.job_id,
  ji.item_key,
  COALESCE(ji.updated_at, j.updated_at, j.created_at) AS sort_ts,
  COALESCE(NULLIF(UPPER(BTRIM(ji.parsed_status)), ''), 'FAILED') AS parsed_status
FROM jobs j
INNER JOIN job_items ji ON ji.job_seq_id = j.job_seq_id
WHERE COALESCE(BTRIM(j.user_id), '') <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_user_recent_results_pk
  ON mv_user_recent_results(job_seq_id, item_key);

CREATE INDEX IF NOT EXISTS idx_mv_user_recent_results_user_sort
  ON mv_user_recent_results(user_id, sort_ts DESC, job_seq_id, item_key);

CREATE MATERIALIZED VIEW mv_user_result_summary_counts AS
SELECT
  user_id,
  COUNT(*)::BIGINT AS total,
  SUM(CASE WHEN parsed_status = 'CLEAR' THEN 1 ELSE 0 END)::BIGINT AS clear,
  SUM(CASE WHEN parsed_status = 'POTENTIAL' THEN 1 ELSE 0 END)::BIGINT AS potential,
  SUM(CASE WHEN parsed_status = 'PENDING' THEN 1 ELSE 0 END)::BIGINT AS pending,
  SUM(CASE WHEN parsed_status = 'FAILED' THEN 1 ELSE 0 END)::BIGINT AS failed
FROM mv_user_recent_results
GROUP BY user_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_user_result_summary_counts_user
  ON mv_user_result_summary_counts(user_id);

REFRESH MATERIALIZED VIEW mv_user_recent_results;
REFRESH MATERIALIZED VIEW mv_user_result_summary_counts;

DROP FUNCTION IF EXISTS _safe_to_timestamptz(TEXT);

COMMIT;
