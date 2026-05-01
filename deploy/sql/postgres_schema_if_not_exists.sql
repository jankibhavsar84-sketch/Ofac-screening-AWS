-- OFAC Screening - PostgreSQL schema bootstrap
-- Idempotent: safe to run multiple times.

BEGIN;

CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  total_items INTEGER NOT NULL,
  source_schedule_id TEXT,
  source_upload_id TEXT,
  user_id TEXT,
  user_name TEXT
);

CREATE TABLE IF NOT EXISTS job_items (
  job_id TEXT NOT NULL,
  item_key TEXT NOT NULL,
  request_json TEXT NOT NULL,
  response_json TEXT,
  status TEXT NOT NULL,
  error_text TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (job_id, item_key),
  FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS job_metadata (
  job_id TEXT PRIMARY KEY,
  mode TEXT NOT NULL DEFAULT 'BATCH',
  screening_types_json TEXT NOT NULL DEFAULT '[]',
  mock_screening BOOLEAN NOT NULL DEFAULT FALSE,
  batch_name TEXT,
  file_name TEXT,
  daily_screening BOOLEAN NOT NULL DEFAULT FALSE,
  schedule_frequency TEXT,
  daily_schedule_id TEXT,
  query_count INTEGER NOT NULL DEFAULT 0,
  deferred_until TEXT,
  business_unit_code TEXT
);

CREATE TABLE IF NOT EXISTS daily_schedules (
  schedule_id TEXT PRIMARY KEY,
  batch_name TEXT NOT NULL,
  user_id TEXT,
  user_name TEXT,
  queries_json TEXT NOT NULL,
  screening_types_json TEXT NOT NULL,
  mock_screening BOOLEAN NOT NULL DEFAULT FALSE,
  schedule_frequency TEXT NOT NULL DEFAULT 'DAILY',
  timezone TEXT NOT NULL,
  run_hour INTEGER NOT NULL,
  run_minute INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  last_run_at TEXT,
  next_run_at TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  source_upload_id TEXT,
  source_file_name TEXT,
  source_s3_uri TEXT,
  business_unit_code TEXT
);

CREATE TABLE IF NOT EXISTS batch_file_uploads (
  upload_id TEXT PRIMARY KEY,
  schedule_id TEXT,
  job_id TEXT,
  user_id TEXT,
  user_name TEXT,
  file_name TEXT NOT NULL,
  s3_bucket TEXT,
  s3_key TEXT,
  s3_uri TEXT,
  queries_s3_bucket TEXT,
  queries_s3_key TEXT,
  queries_s3_uri TEXT,
  file_hash TEXT,
  record_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS schedule_record_state (
  schedule_id TEXT NOT NULL,
  record_hash TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_screened_at TEXT NOT NULL,
  last_job_id TEXT,
  PRIMARY KEY (schedule_id, record_hash)
);

CREATE TABLE IF NOT EXISTS schedule_subscriptions (
  subscription_id TEXT PRIMARY KEY,
  schedule_id TEXT NOT NULL,
  user_id TEXT,
  user_name TEXT,
  email TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_schedule_notifications (
  job_id TEXT PRIMARY KEY,
  schedule_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
  event_id BIGSERIAL PRIMARY KEY,
  created_at TEXT NOT NULL,
  user_id TEXT,
  user_name TEXT,
  action TEXT NOT NULL,
  entity_type TEXT,
  entity_id TEXT,
  details_json TEXT
);

CREATE TABLE IF NOT EXISTS api_access_logs (
  access_id BIGSERIAL PRIMARY KEY,
  created_at TEXT NOT NULL,
  correlation_id TEXT,
  request_method TEXT NOT NULL,
  request_path TEXT NOT NULL,
  query_string TEXT,
  status_code INTEGER NOT NULL,
  duration_ms INTEGER NOT NULL,
  client_ip TEXT,
  user_agent TEXT,
  user_id TEXT,
  user_name TEXT,
  auth_state TEXT,
  details_json TEXT
);

CREATE TABLE IF NOT EXISTS external_api_errors (
  error_id BIGSERIAL PRIMARY KEY,
  created_at TEXT NOT NULL,
  provider TEXT NOT NULL,
  operation TEXT,
  endpoint TEXT,
  status_code INTEGER,
  user_id TEXT,
  user_name TEXT,
  job_id TEXT,
  item_key TEXT,
  error_text TEXT NOT NULL,
  details_json TEXT
);

CREATE TABLE IF NOT EXISTS actimize_alert_callbacks (
  callback_id BIGSERIAL PRIMARY KEY,
  created_at TEXT NOT NULL,
  unique_key TEXT NOT NULL,
  normalized_unique_key TEXT NOT NULL,
  alert_id TEXT NOT NULL,
  screening_cd TEXT,
  status_cd TEXT NOT NULL,
  update_timestamp TEXT,
  source_system_cd TEXT,
  tenant_cd TEXT,
  matched_count INTEGER NOT NULL DEFAULT 0,
  details_json TEXT
);

CREATE TABLE IF NOT EXISTS schedule_notifications (
  notification_id BIGSERIAL PRIMARY KEY,
  created_at TEXT NOT NULL,
  user_id TEXT,
  user_name TEXT,
  email TEXT,
  schedule_id TEXT,
  job_id TEXT,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  summary_json TEXT
);

CREATE TABLE IF NOT EXISTS business_units (
  business_unit_code TEXT PRIMARY KEY,
  business_unit_name TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_business_units (
  user_id TEXT NOT NULL,
  user_name TEXT,
  business_unit_code TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, business_unit_code)
);

CREATE TABLE IF NOT EXISTS actimize_screening_type_mappings (
  normalized_source_type TEXT PRIMARY KEY,
  source_screening_type TEXT NOT NULL,
  target_screening_type TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_schedule_subscriptions_unique
ON schedule_subscriptions(schedule_id, email);

CREATE INDEX IF NOT EXISTS idx_daily_schedules_next_run
ON daily_schedules(next_run_at);

CREATE INDEX IF NOT EXISTS idx_notifications_user
ON schedule_notifications(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_notifications_email
ON schedule_notifications(email, created_at);

CREATE INDEX IF NOT EXISTS idx_user_business_units_user
ON user_business_units(user_id, is_active);

CREATE INDEX IF NOT EXISTS idx_user_business_units_code
ON user_business_units(business_unit_code, is_active);

CREATE INDEX IF NOT EXISTS idx_audit_events_event_id
ON audit_events(event_id DESC);

CREATE INDEX IF NOT EXISTS idx_audit_events_user_event
ON audit_events(user_id, event_id DESC);

CREATE INDEX IF NOT EXISTS idx_external_api_errors_created_at
ON external_api_errors(created_at);

CREATE INDEX IF NOT EXISTS idx_external_api_errors_job_item
ON external_api_errors(job_id, item_key, created_at);

CREATE INDEX IF NOT EXISTS idx_actimize_callbacks_unique_key_created_at
ON actimize_alert_callbacks(normalized_unique_key, created_at);

CREATE INDEX IF NOT EXISTS idx_actimize_callbacks_alert_id
ON actimize_alert_callbacks(alert_id, created_at);

CREATE INDEX IF NOT EXISTS idx_api_access_logs_created_at
ON api_access_logs(created_at);

CREATE INDEX IF NOT EXISTS idx_api_access_logs_correlation
ON api_access_logs(correlation_id, created_at);

CREATE INDEX IF NOT EXISTS idx_api_access_logs_user
ON api_access_logs(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_api_access_logs_path
ON api_access_logs(request_path, created_at);

-- Backward-compatible column guards for upgraded environments.
ALTER TABLE IF EXISTS jobs ADD COLUMN IF NOT EXISTS source_schedule_id TEXT;
ALTER TABLE IF EXISTS jobs ADD COLUMN IF NOT EXISTS source_upload_id TEXT;
ALTER TABLE IF EXISTS jobs ADD COLUMN IF NOT EXISTS user_id TEXT;
ALTER TABLE IF EXISTS jobs ADD COLUMN IF NOT EXISTS user_name TEXT;

ALTER TABLE IF EXISTS job_metadata ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'BATCH';
ALTER TABLE IF EXISTS job_metadata ADD COLUMN IF NOT EXISTS screening_types_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE IF EXISTS job_metadata ADD COLUMN IF NOT EXISTS mock_screening BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE IF EXISTS job_metadata ADD COLUMN IF NOT EXISTS batch_name TEXT;
ALTER TABLE IF EXISTS job_metadata ADD COLUMN IF NOT EXISTS file_name TEXT;
ALTER TABLE IF EXISTS job_metadata ADD COLUMN IF NOT EXISTS daily_screening BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE IF EXISTS job_metadata ADD COLUMN IF NOT EXISTS schedule_frequency TEXT;
ALTER TABLE IF EXISTS job_metadata ADD COLUMN IF NOT EXISTS daily_schedule_id TEXT;
ALTER TABLE IF EXISTS job_metadata ADD COLUMN IF NOT EXISTS query_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE IF EXISTS job_metadata ADD COLUMN IF NOT EXISTS deferred_until TEXT;
ALTER TABLE IF EXISTS job_metadata ADD COLUMN IF NOT EXISTS business_unit_code TEXT;

ALTER TABLE IF EXISTS daily_schedules ADD COLUMN IF NOT EXISTS user_id TEXT;
ALTER TABLE IF EXISTS daily_schedules ADD COLUMN IF NOT EXISTS user_name TEXT;
ALTER TABLE IF EXISTS daily_schedules ADD COLUMN IF NOT EXISTS schedule_frequency TEXT NOT NULL DEFAULT 'DAILY';
ALTER TABLE IF EXISTS daily_schedules ADD COLUMN IF NOT EXISTS source_upload_id TEXT;
ALTER TABLE IF EXISTS daily_schedules ADD COLUMN IF NOT EXISTS source_file_name TEXT;
ALTER TABLE IF EXISTS daily_schedules ADD COLUMN IF NOT EXISTS source_s3_uri TEXT;
ALTER TABLE IF EXISTS daily_schedules ADD COLUMN IF NOT EXISTS business_unit_code TEXT;

ALTER TABLE IF EXISTS batch_file_uploads ADD COLUMN IF NOT EXISTS queries_s3_bucket TEXT;
ALTER TABLE IF EXISTS batch_file_uploads ADD COLUMN IF NOT EXISTS queries_s3_key TEXT;
ALTER TABLE IF EXISTS batch_file_uploads ADD COLUMN IF NOT EXISTS queries_s3_uri TEXT;

ALTER TABLE IF EXISTS actimize_screening_type_mappings ADD COLUMN IF NOT EXISTS source_screening_type TEXT NOT NULL;
ALTER TABLE IF EXISTS actimize_screening_type_mappings ADD COLUMN IF NOT EXISTS target_screening_type TEXT NOT NULL;
ALTER TABLE IF EXISTS actimize_screening_type_mappings ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE IF EXISTS actimize_screening_type_mappings ADD COLUMN IF NOT EXISTS created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::TEXT;
ALTER TABLE IF EXISTS actimize_screening_type_mappings ADD COLUMN IF NOT EXISTS updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::TEXT;

-- Seed defaults (idempotent)
INSERT INTO business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES
('US_PRU_OSGLI', 'OSGLI', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_VM', 'Vendor Management', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_HR', 'Human Resources', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_OPES', 'Operation/Enabling Solutions', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_PGIM', 'PGIM', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_PGIM_RE_TENANT', 'PGIM Real Estate tenant', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_PGIM_RE', 'PGIM Real Estate', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_PGIM_FI', 'PGIM Fixed Income', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_PGIM_PP_FI', 'PGIMPublic and Private Fixed Income', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_PGIM_MA', 'PGIM Multi Asset Solutions', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_PGIM_CIO', 'PGIM CIO', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_PGIM_JAPAN', 'PGIM Japan', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_PGIM_JK_ASC', 'PGIM Jenkins Associates', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_PGIM_NE_FI', 'PGIM Netherlands', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_PGIM_QUANT', 'PGIM Quant Compliance', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_PGIM_RE_APAC', 'PGIM Real Estate APAC', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('US_PRU_PGIM_LATAM', 'PGIM LATAM', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT)
ON CONFLICT (business_unit_code) DO NOTHING;

INSERT INTO actimize_screening_type_mappings (
  normalized_source_type, source_screening_type, target_screening_type, is_active, created_at, updated_at
) VALUES
('sanction', 'Sanction', 'SD_US_Customers_Sanctions', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('pep', 'PEP', 'SD_US_Customers_PEP_RCA_International', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('ame', 'AME', 'SD_US_Customers_AME', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('fincen 314(a)', 'Fincen 314(a)', 'SD_US_Customers_314(a)', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('fincen 314a', 'Fincen 314a', 'SD_US_Customers_314(a)', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('fincen314(a)', 'Fincen314(a)', 'SD_US_Customers_314(a)', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('fincen314a', 'Fincen314a', 'SD_US_Customers_314(a)', TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT)
ON CONFLICT (normalized_source_type) DO NOTHING;

COMMIT;

