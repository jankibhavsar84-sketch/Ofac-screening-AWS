BEGIN;

-- Drop dependent materialized views before removing legacy columns.
DROP MATERIALIZED VIEW IF EXISTS mv_user_result_summary_counts;
DROP MATERIALIZED VIEW IF EXISTS mv_user_recent_results;
DROP MATERIALIZED VIEW IF EXISTS mv_daily_schedule_batch_runs;
DROP MATERIALIZED VIEW IF EXISTS mv_user_submission_jobs;

-- Ensure bigint user reference columns exist everywhere.
ALTER TABLE IF EXISTS jobs ADD COLUMN IF NOT EXISTS user_ref_id BIGINT;
ALTER TABLE IF EXISTS daily_schedules ADD COLUMN IF NOT EXISTS user_ref_id BIGINT;
ALTER TABLE IF EXISTS batch_file_uploads ADD COLUMN IF NOT EXISTS user_ref_id BIGINT;
ALTER TABLE IF EXISTS schedule_subscriptions ADD COLUMN IF NOT EXISTS user_ref_id BIGINT;
ALTER TABLE IF EXISTS schedule_notifications ADD COLUMN IF NOT EXISTS user_ref_id BIGINT;
ALTER TABLE IF EXISTS user_business_units ADD COLUMN IF NOT EXISTS user_ref_id BIGINT;
ALTER TABLE IF EXISTS audit_events ADD COLUMN IF NOT EXISTS user_ref_id BIGINT;
ALTER TABLE IF EXISTS external_api_errors ADD COLUMN IF NOT EXISTS user_ref_id BIGINT;
ALTER TABLE IF EXISTS api_access_logs ADD COLUMN IF NOT EXISTS user_ref_id BIGINT;
ALTER TABLE IF EXISTS job_items ADD COLUMN IF NOT EXISTS user_ref_id BIGINT;

-- Build missing app_users rows from legacy text user IDs so every record can be resolved.
CREATE TEMP TABLE tmp_legacy_users (
  old_id TEXT PRIMARY KEY,
  user_name TEXT
) ON COMMIT DROP;

INSERT INTO tmp_legacy_users(old_id, user_name)
SELECT old_id, MAX(user_name) AS user_name
FROM (
  SELECT NULLIF(BTRIM(user_id), '') AS old_id, NULL::TEXT AS user_name FROM jobs
  UNION ALL
  SELECT NULLIF(BTRIM(user_id), ''), NULL::TEXT FROM daily_schedules
  UNION ALL
  SELECT NULLIF(BTRIM(user_id), ''), NULL::TEXT FROM batch_file_uploads
  UNION ALL
  SELECT NULLIF(BTRIM(user_id), ''), NULL::TEXT FROM schedule_subscriptions
  UNION ALL
  SELECT NULLIF(BTRIM(user_id), ''), NULLIF(BTRIM(user_name), '') FROM schedule_notifications
  UNION ALL
  SELECT NULLIF(BTRIM(user_id), ''), NULL::TEXT FROM user_business_units
  UNION ALL
  SELECT NULLIF(BTRIM(user_id), ''), NULLIF(BTRIM(user_name), '') FROM audit_events
  UNION ALL
  SELECT NULLIF(BTRIM(user_id), ''), NULLIF(BTRIM(user_name), '') FROM external_api_errors
  UNION ALL
  SELECT NULLIF(BTRIM(user_id), ''), NULLIF(BTRIM(user_name), '') FROM api_access_logs
) legacy
WHERE old_id IS NOT NULL
GROUP BY old_id;

INSERT INTO app_users(old_id, name, is_active, created_at, updated_at)
SELECT old_id, user_name, TRUE, NOW(), NOW()
FROM tmp_legacy_users lu
WHERE NOT EXISTS (
  SELECT 1
  FROM app_users au
  WHERE au.old_id = lu.old_id
);

-- Backfill bigint foreign keys from legacy text IDs.
UPDATE jobs j
SET user_ref_id = u.user_id
FROM app_users u
WHERE j.user_ref_id IS NULL
  AND NULLIF(BTRIM(j.user_id), '') IS NOT NULL
  AND u.old_id = BTRIM(j.user_id);

UPDATE daily_schedules d
SET user_ref_id = u.user_id
FROM app_users u
WHERE d.user_ref_id IS NULL
  AND NULLIF(BTRIM(d.user_id), '') IS NOT NULL
  AND u.old_id = BTRIM(d.user_id);

UPDATE batch_file_uploads b
SET user_ref_id = u.user_id
FROM app_users u
WHERE b.user_ref_id IS NULL
  AND NULLIF(BTRIM(b.user_id), '') IS NOT NULL
  AND u.old_id = BTRIM(b.user_id);

UPDATE schedule_subscriptions s
SET user_ref_id = u.user_id
FROM app_users u
WHERE s.user_ref_id IS NULL
  AND NULLIF(BTRIM(s.user_id), '') IS NOT NULL
  AND u.old_id = BTRIM(s.user_id);

UPDATE schedule_notifications n
SET user_ref_id = u.user_id
FROM app_users u
WHERE n.user_ref_id IS NULL
  AND NULLIF(BTRIM(n.user_id), '') IS NOT NULL
  AND u.old_id = BTRIM(n.user_id);

UPDATE user_business_units ub
SET user_ref_id = u.user_id
FROM app_users u
WHERE ub.user_ref_id IS NULL
  AND NULLIF(BTRIM(ub.user_id), '') IS NOT NULL
  AND u.old_id = BTRIM(ub.user_id);

UPDATE audit_events a
SET user_ref_id = u.user_id
FROM app_users u
WHERE a.user_ref_id IS NULL
  AND NULLIF(BTRIM(a.user_id), '') IS NOT NULL
  AND u.old_id = BTRIM(a.user_id);

UPDATE external_api_errors e
SET user_ref_id = u.user_id
FROM app_users u
WHERE e.user_ref_id IS NULL
  AND NULLIF(BTRIM(e.user_id), '') IS NOT NULL
  AND u.old_id = BTRIM(e.user_id);

UPDATE api_access_logs l
SET user_ref_id = u.user_id
FROM app_users u
WHERE l.user_ref_id IS NULL
  AND NULLIF(BTRIM(l.user_id), '') IS NOT NULL
  AND u.old_id = BTRIM(l.user_id);

UPDATE job_items ji
SET user_ref_id = j.user_ref_id
FROM jobs j
WHERE ji.user_ref_id IS NULL
  AND ji.job_seq_id = j.job_seq_id
  AND j.user_ref_id IS NOT NULL;

-- Remove duplicate user-business-unit rows before rebuilding PK.
DELETE FROM user_business_units ub1
USING user_business_units ub2
WHERE ub1.ctid < ub2.ctid
  AND ub1.user_ref_id = ub2.user_ref_id
  AND ub1.business_unit_code = ub2.business_unit_code;

-- Remove records that still cannot be mapped.
DELETE FROM user_business_units WHERE user_ref_id IS NULL;

-- Drop old indexes built on text user_id columns.
DROP INDEX IF EXISTS idx_api_access_logs_user;
DROP INDEX IF EXISTS idx_notifications_user;
DROP INDEX IF EXISTS idx_user_business_units_user;
DROP INDEX IF EXISTS idx_audit_events_user_event;
DROP INDEX IF EXISTS idx_job_items_user_recent;
DROP INDEX IF EXISTS idx_job_items_user_status;

-- Remove legacy triggers/functions tied to jobs.user_id and job_items.user_id.
DROP TRIGGER IF EXISTS trg_job_items_set_user_id ON job_items;
DROP TRIGGER IF EXISTS trg_jobs_sync_job_items_user_id ON jobs;
DROP FUNCTION IF EXISTS set_job_items_user_id();
DROP FUNCTION IF EXISTS sync_job_items_user_id_from_jobs();

-- Move user_business_units primary key to bigint user_ref_id.
ALTER TABLE IF EXISTS user_business_units DROP CONSTRAINT IF EXISTS user_business_units_pkey;
ALTER TABLE IF EXISTS user_business_units
  ADD CONSTRAINT user_business_units_pkey PRIMARY KEY (user_ref_id, business_unit_code);

-- Drop legacy text user_id columns.
ALTER TABLE IF EXISTS jobs DROP COLUMN IF EXISTS user_id;
ALTER TABLE IF EXISTS daily_schedules DROP COLUMN IF EXISTS user_id;
ALTER TABLE IF EXISTS batch_file_uploads DROP COLUMN IF EXISTS user_id;
ALTER TABLE IF EXISTS schedule_subscriptions DROP COLUMN IF EXISTS user_id;
ALTER TABLE IF EXISTS schedule_notifications DROP COLUMN IF EXISTS user_id;
ALTER TABLE IF EXISTS user_business_units DROP COLUMN IF EXISTS user_id;
ALTER TABLE IF EXISTS audit_events DROP COLUMN IF EXISTS user_id;
ALTER TABLE IF EXISTS external_api_errors DROP COLUMN IF EXISTS user_id;
ALTER TABLE IF EXISTS api_access_logs DROP COLUMN IF EXISTS user_id;
ALTER TABLE IF EXISTS job_items DROP COLUMN IF EXISTS user_id;

-- Ensure user_ref indexes exist.
CREATE INDEX IF NOT EXISTS idx_jobs_user_ref
  ON jobs(user_ref_id, updated_at DESC, created_at DESC, job_id);
CREATE INDEX IF NOT EXISTS idx_daily_schedules_user_ref
  ON daily_schedules(user_ref_id, created_at DESC, schedule_id);
CREATE INDEX IF NOT EXISTS idx_batch_file_uploads_user_ref
  ON batch_file_uploads(user_ref_id, created_at DESC, upload_id);
CREATE INDEX IF NOT EXISTS idx_schedule_subscriptions_user_ref
  ON schedule_subscriptions(user_ref_id, created_at DESC, subscription_id);
CREATE INDEX IF NOT EXISTS idx_schedule_notifications_user_ref
  ON schedule_notifications(user_ref_id, created_at DESC, notification_id);
CREATE INDEX IF NOT EXISTS idx_user_business_units_user_ref
  ON user_business_units(user_ref_id, is_active, business_unit_code);
CREATE INDEX IF NOT EXISTS idx_audit_events_user_ref_event
  ON audit_events(user_ref_id, event_id DESC);
CREATE INDEX IF NOT EXISTS idx_external_api_errors_user_ref_created_at
  ON external_api_errors(user_ref_id, created_at DESC, error_id DESC);
CREATE INDEX IF NOT EXISTS idx_api_access_logs_user_ref_created_at
  ON api_access_logs(user_ref_id, created_at DESC, access_id DESC);
CREATE INDEX IF NOT EXISTS idx_job_items_user_ref_id
  ON job_items(user_ref_id);

COMMIT;
