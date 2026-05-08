BEGIN;

-- Ensure every user-carrying table has an integer user reference.
ALTER TABLE IF EXISTS job_items
  ADD COLUMN IF NOT EXISTS user_ref_id BIGINT;

-- Backfill from old text user_id via app_users.old_id where possible.
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

-- job_items follows owning job user.
UPDATE job_items ji
SET user_ref_id = j.user_ref_id
FROM jobs j
WHERE ji.user_ref_id IS NULL
  AND ji.job_seq_id = j.job_seq_id
  AND j.user_ref_id IS NOT NULL;

UPDATE job_items ji
SET user_ref_id = u.user_id
FROM app_users u
WHERE ji.user_ref_id IS NULL
  AND NULLIF(BTRIM(ji.user_id), '') IS NOT NULL
  AND u.old_id = BTRIM(ji.user_id);

CREATE INDEX IF NOT EXISTS idx_job_items_user_ref_id
ON job_items(user_ref_id);

CREATE INDEX IF NOT EXISTS idx_daily_schedules_active_created
ON daily_schedules(is_active, created_at DESC, schedule_id);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_jobs_user_ref_id') THEN
    ALTER TABLE jobs
      ADD CONSTRAINT fk_jobs_user_ref_id
      FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_daily_schedules_user_ref_id') THEN
    ALTER TABLE daily_schedules
      ADD CONSTRAINT fk_daily_schedules_user_ref_id
      FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_batch_file_uploads_user_ref_id') THEN
    ALTER TABLE batch_file_uploads
      ADD CONSTRAINT fk_batch_file_uploads_user_ref_id
      FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_schedule_subscriptions_user_ref_id') THEN
    ALTER TABLE schedule_subscriptions
      ADD CONSTRAINT fk_schedule_subscriptions_user_ref_id
      FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_schedule_notifications_user_ref_id') THEN
    ALTER TABLE schedule_notifications
      ADD CONSTRAINT fk_schedule_notifications_user_ref_id
      FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_user_business_units_user_ref_id') THEN
    ALTER TABLE user_business_units
      ADD CONSTRAINT fk_user_business_units_user_ref_id
      FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_audit_events_user_ref_id') THEN
    ALTER TABLE audit_events
      ADD CONSTRAINT fk_audit_events_user_ref_id
      FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_external_api_errors_user_ref_id') THEN
    ALTER TABLE external_api_errors
      ADD CONSTRAINT fk_external_api_errors_user_ref_id
      FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_api_access_logs_user_ref_id') THEN
    ALTER TABLE api_access_logs
      ADD CONSTRAINT fk_api_access_logs_user_ref_id
      FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_job_items_user_ref_id') THEN
    ALTER TABLE job_items
      ADD CONSTRAINT fk_job_items_user_ref_id
      FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);
  END IF;
END $$;

COMMIT;
