BEGIN;

-- Drop dependent materialized views before changing base tables.
DROP MATERIALIZED VIEW IF EXISTS mv_user_result_summary_counts;
DROP MATERIALIZED VIEW IF EXISTS mv_user_recent_results;
DROP MATERIALIZED VIEW IF EXISTS mv_daily_schedule_batch_runs;
DROP MATERIALIZED VIEW IF EXISTS mv_user_submission_jobs;

-- Remove user_name from operational tables.
ALTER TABLE IF EXISTS jobs DROP COLUMN IF EXISTS user_name;
ALTER TABLE IF EXISTS daily_schedules DROP COLUMN IF EXISTS user_name;
ALTER TABLE IF EXISTS batch_file_uploads DROP COLUMN IF EXISTS user_name;
ALTER TABLE IF EXISTS schedule_subscriptions DROP COLUMN IF EXISTS user_name;
ALTER TABLE IF EXISTS user_business_units DROP COLUMN IF EXISTS user_name;

COMMIT;
