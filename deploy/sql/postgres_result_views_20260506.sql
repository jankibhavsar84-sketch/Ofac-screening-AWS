BEGIN;

-- Live (non-materialized) dataset view for screening results.
CREATE OR REPLACE VIEW vw_screening_results_dataset AS
SELECT
  COALESCE(ji.user_id, j.user_id) AS user_id,
  j.user_name,
  j.job_id,
  j.job_seq_id,
  j.status AS job_status,
  j.created_at AS job_created_at,
  j.updated_at AS job_updated_at,
  j.total_items,
  j.source_schedule_id,
  j.source_upload_id,
  jm.mode,
  jm.screening_types_json,
  jm.mock_screening,
  jm.batch_name,
  jm.file_name,
  jm.daily_screening,
  jm.schedule_frequency,
  jm.daily_schedule_id,
  jm.query_count,
  jm.deferred_until,
  jm.business_unit_code,
  ji.item_key,
  ji.status AS item_status,
  COALESCE(NULLIF(ji.parsed_status, ''), 'FAILED') AS parsed_status,
  ji.error_text,
  ji.request_json,
  ji.response_json,
  ji.updated_at AS item_updated_at,
  COALESCE(ji.updated_at, j.updated_at, j.created_at) AS sort_ts
FROM job_items ji
INNER JOIN jobs j
  ON (
    (ji.job_seq_id IS NOT NULL AND ji.job_seq_id = j.job_seq_id)
    OR (ji.job_seq_id IS NULL AND ji.job_id = j.job_id)
  )
LEFT JOIN job_metadata jm
  ON jm.job_id = j.job_id;

-- Aggregated live summary view by user.
CREATE OR REPLACE VIEW vw_user_result_summary_counts AS
SELECT
  user_id,
  COUNT(*)::BIGINT AS total,
  SUM(CASE WHEN parsed_status = 'CLEAR' THEN 1 ELSE 0 END)::BIGINT AS clear,
  SUM(CASE WHEN parsed_status = 'POTENTIAL' THEN 1 ELSE 0 END)::BIGINT AS potential,
  SUM(CASE WHEN parsed_status = 'PENDING' THEN 1 ELSE 0 END)::BIGINT AS pending,
  SUM(CASE WHEN parsed_status = 'FAILED' THEN 1 ELSE 0 END)::BIGINT AS failed
FROM vw_screening_results_dataset
WHERE COALESCE(user_id, '') <> ''
GROUP BY user_id;

COMMIT;
