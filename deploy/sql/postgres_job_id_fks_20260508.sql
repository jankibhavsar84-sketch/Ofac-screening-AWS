BEGIN;

-- Legacy cleanup: remove text job_id-based foreign keys from child tables.
ALTER TABLE IF EXISTS job_metadata
  DROP CONSTRAINT IF EXISTS fk_job_metadata_job_id;
ALTER TABLE IF EXISTS job_schedule_notifications
  DROP CONSTRAINT IF EXISTS fk_job_schedule_notifications_job_id;
ALTER TABLE IF EXISTS batch_file_uploads
  DROP CONSTRAINT IF EXISTS fk_batch_file_uploads_job_id;
ALTER TABLE IF EXISTS schedule_notifications
  DROP CONSTRAINT IF EXISTS fk_schedule_notifications_job_id;
ALTER TABLE IF EXISTS job_items
  DROP CONSTRAINT IF EXISTS job_items_job_id_fkey;

COMMIT;
