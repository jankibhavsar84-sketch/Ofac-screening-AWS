-- Views and Materialized Views
-- Generated at: 2026-05-11T00:00:00+00:00
-- Schema: public

-- Drop in dependency-safe order.
DROP MATERIALIZED VIEW IF EXISTS public.mv_user_result_summary_counts;
DROP MATERIALIZED VIEW IF EXISTS public.mv_daily_schedule_batch_runs;
DROP MATERIALIZED VIEW IF EXISTS public.mv_user_submission_jobs;
DROP MATERIALIZED VIEW IF EXISTS public.mv_user_recent_results;

CREATE MATERIALIZED VIEW public.mv_user_recent_results AS
SELECT
  j.user_ref_id,
  au.old_id AS user_id,
  COALESCE(au.name, au.old_id) AS user_name,
  j.job_id,
  ji.item_key,
  COALESCE(ji.updated_at, j.updated_at, j.created_at) AS sort_ts,
  CASE
    WHEN UPPER(COALESCE(NULLIF(ji.parsed_status, ''), '')) IN ('CLEAR', 'POTENTIAL', 'PENDING', 'FAILED')
      THEN UPPER(ji.parsed_status)
    WHEN UPPER(COALESCE(ji.status, '')) IN ('QUEUED', 'PROCESSING')
      THEN 'PENDING'
    WHEN UPPER(COALESCE(ji.status, '')) = 'FAILED'
      THEN 'FAILED'
    WHEN ji.response_json IS NULL
      THEN 'FAILED'
    WHEN UPPER(COALESCE(ji.response_json->>'engine_message', '')) = 'PM'
      THEN 'POTENTIAL'
    WHEN UPPER(COALESCE(ji.response_json->>'engine_message', '')) = 'NM'
      THEN 'CLEAR'
    ELSE 'CLEAR'
  END AS parsed_status
FROM public.jobs j
LEFT JOIN public.app_users au
  ON au.user_id = j.user_ref_id
INNER JOIN public.job_items ji
  ON ji.job_id = j.job_id
WHERE j.user_ref_id IS NOT NULL;

CREATE MATERIALIZED VIEW public.mv_user_result_summary_counts AS
SELECT
  user_ref_id,
  MAX(user_id) AS user_id,
  COUNT(*)::BIGINT AS total,
  SUM(CASE WHEN parsed_status = 'CLEAR' THEN 1 ELSE 0 END)::BIGINT AS clear,
  SUM(CASE WHEN parsed_status = 'POTENTIAL' THEN 1 ELSE 0 END)::BIGINT AS potential,
  SUM(CASE WHEN parsed_status = 'PENDING' THEN 1 ELSE 0 END)::BIGINT AS pending,
  SUM(CASE WHEN parsed_status = 'FAILED' THEN 1 ELSE 0 END)::BIGINT AS failed
FROM public.mv_user_recent_results
GROUP BY user_ref_id;

CREATE MATERIALIZED VIEW public.mv_user_submission_jobs AS
SELECT
  j.job_id,
  j.user_ref_id,
  j.created_at,
  j.total_items,
  j.source_schedule_id,
  j.source_upload_id,
  au.old_id AS user_id,
  COALESCE(au.name, au.old_id) AS user_name,
  jm.mode,
  jm.screening_types_json,
  jm.mock_screening,
  jm.batch_name,
  jm.file_name,
  jm.daily_screening,
  jm.schedule_frequency,
  jm.daily_schedule_id,
  jm.business_unit_code,
  bu.file_name AS upload_file_name,
  bu.s3_uri AS upload_s3_uri
FROM public.jobs j
LEFT JOIN public.app_users au
  ON au.user_id = j.user_ref_id
LEFT JOIN public.job_metadata jm
  ON jm.job_id = j.job_id
LEFT JOIN public.batch_file_uploads bu
  ON bu.upload_id = j.source_upload_id;

CREATE MATERIALIZED VIEW public.mv_daily_schedule_batch_runs AS
SELECT
  j.job_id,
  COALESCE(jm.daily_schedule_id, j.source_schedule_id) AS schedule_id,
  UPPER(COALESCE(j.status, '')) AS job_status,
  j.created_at,
  j.updated_at,
  j.total_items,
  j.source_upload_id,
  j.user_ref_id,
  au.old_id AS user_id,
  COALESCE(au.name, au.old_id) AS user_name,
  COALESCE(
    NULLIF(jm.batch_name, ''),
    NULLIF(ds.batch_name, ''),
    NULLIF(jm.file_name, ''),
    NULLIF(bu.file_name, ''),
    'Scheduled Batch'
  ) AS batch_name,
  NULLIF(COALESCE(NULLIF(jm.schedule_frequency, ''), NULLIF(ds.schedule_frequency, '')), '') AS schedule_frequency,
  NULLIF(COALESCE(NULLIF(bu.file_name, ''), NULLIF(ds.source_file_name, ''), NULLIF(jm.file_name, '')), '') AS source_file_name,
  COALESCE(js.completed_items, 0) AS completed_items,
  COALESCE(js.failed_items, 0) AS failed_items,
  COALESCE(js.pending_items, 0) AS pending_items,
  COALESCE(js.processing_items, 0) AS processing_items
FROM public.jobs j
LEFT JOIN public.app_users au
  ON au.user_id = j.user_ref_id
LEFT JOIN public.job_metadata jm
  ON jm.job_id = j.job_id
LEFT JOIN public.daily_schedules ds
  ON ds.schedule_id = COALESCE(jm.daily_schedule_id, j.source_schedule_id)
LEFT JOIN public.batch_file_uploads bu
  ON bu.upload_id = j.source_upload_id
LEFT JOIN (
  SELECT
    job_id,
    SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed_items,
    SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_items,
    SUM(CASE WHEN status = 'QUEUED' THEN 1 ELSE 0 END) AS pending_items,
    SUM(CASE WHEN status = 'PROCESSING' THEN 1 ELSE 0 END) AS processing_items
  FROM public.job_items
  GROUP BY job_id
) js
  ON js.job_id = j.job_id
WHERE COALESCE(jm.daily_schedule_id, j.source_schedule_id) IS NOT NULL
  AND UPPER(COALESCE(jm.mode, 'BATCH')) = 'BATCH';
