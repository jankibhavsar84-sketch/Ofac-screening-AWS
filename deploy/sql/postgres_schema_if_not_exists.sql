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
  search_definition_name TEXT NOT NULL DEFAULT '',
  screening_type_name TEXT NOT NULL DEFAULT '',
  display_order INTEGER NOT NULL DEFAULT 1000,
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
ALTER TABLE IF EXISTS actimize_screening_type_mappings ADD COLUMN IF NOT EXISTS search_definition_name TEXT NOT NULL DEFAULT '';
ALTER TABLE IF EXISTS actimize_screening_type_mappings ADD COLUMN IF NOT EXISTS screening_type_name TEXT NOT NULL DEFAULT '';
ALTER TABLE IF EXISTS actimize_screening_type_mappings ADD COLUMN IF NOT EXISTS display_order INTEGER NOT NULL DEFAULT 1000;
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
  normalized_source_type, source_screening_type, target_screening_type, search_definition_name, screening_type_name, display_order, is_active, created_at, updated_at
) VALUES
('sanction', 'Sanction', 'SD_US_Customers_Sanctions', 'Search Definition Customer Sanctions', 'Sanction screening for US Customer', 10, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('pep', 'PEP', 'SD_US_Customers_PEP_RCA_International', 'Search Definition Customer PEP RCA International', 'PEP Screening Exclude US', 20, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('ame', 'AME', 'SD_US_Customers_AME', 'Search Definition Customer AME', 'Adverse Media Screening', 30, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('fincen 314(a)', 'Fincen 314(a)', 'SD_US_Customers_314(a)', 'Search Definition Customer FinCEN 314(a)', 'Fincen 314a Screening', 40, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('fincen 314a', 'Fincen 314a', 'SD_US_Customers_314(a)', 'Search Definition Customer FinCEN 314(a)', 'Fincen 314a Screening', 40, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('fincen314(a)', 'Fincen314(a)', 'SD_US_Customers_314(a)', 'Search Definition Customer FinCEN 314(a)', 'Fincen 314a Screening', 40, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('fincen314a', 'Fincen314a', 'SD_US_Customers_314(a)', 'Search Definition Customer FinCEN 314(a)', 'Fincen 314a Screening', 40, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('sd_us_customers_sanctions_pgim_ma', 'SD_US_Customers_Sanctions_PGIM_MA', 'SD_US_Customers_Sanctions_PGIM_MA', 'Search Definition Customer Sanctions PGIM Multi-Asset Solutions / PGIM Strategic Capital Group', 'PGIM Multi-Asset Solutions/ PGIM Strategic Capital Group Sanction Screening', 50, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('sd_us_customers_sanctions_pgim_cio', 'SD_US_Customers_Sanctions_PGIM_CIO', 'SD_US_Customers_Sanctions_PGIM_CIO', 'Search Definition Customer Sanctions PGIM CIO', 'PGIM CIO Sanction Screening', 60, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('sd_us_customers_sanctions_pgim_fi', 'SD_US_Customers_Sanctions_PGIM_FI', 'SD_US_Customers_Sanctions_PGIM_FI', 'Search Definition Customer Sanctions PGIM Fixed Income', 'PGIM Fixed Income Sanction Screening', 70, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('sd_us_customers_sanctions_pgim_re', 'SD_US_Customers_Sanctions_PGIM_RE', 'SD_US_Customers_Sanctions_PGIM_RE', 'Search Definition Customer Sanctions PGIM Real Estate', 'Search Definition Customer Sanctions PGIM Real Estate', 80, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('sd_us_customers_sanctions_pgim_pp_fi', 'SD_US_Customers_Sanctions_PGIM_PP_FI', 'SD_US_Customers_Sanctions_PGIM_PP_FI', 'Search Definition Customer Sanctions PGIM Public and Private Fixed Income', 'Search Definition Customer Sanctions PGIM Public and Private Fixed Income', 90, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('sd_us_customers_sanctions_pgim_ne_fi', 'SD_US_Customers_Sanctions_PGIM_NE_FI', 'SD_US_Customers_Sanctions_PGIM_NE_FI', 'Search Definition Customer Sanctions Public & Private Fixed Income, PGIM Netherlands B.V.', 'Search Definition Customer Sanctions Public & Private Fixed Income, PGIM Netherlands B.V.', 100, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('sd_us_customers_sanctions_pgim_quant', 'SD_US_Customers_Sanctions_PGIM_QUANT', 'SD_US_Customers_Sanctions_PGIM_QUANT', 'Search Definition Customer Sanctions PGIM Quant', 'Search Definition Customer Sanctions PGIM Quant', 110, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('sd_us_customers_sanctions_pgim_jk_asc', 'SD_US_Customers_Sanctions_PGIM_JK_ASC', 'SD_US_Customers_Sanctions_PGIM_JK_ASC', 'Search Definition Customer Sanctions Jennison Associates', 'Jennison Associates Sanction Screening', 120, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('sd_us_customers_sanctions_pgim_apac', 'SD_US_Customers_Sanctions_PGIM_APAC', 'SD_US_Customers_Sanctions_PGIM_APAC', 'Search Definition Customer Sanctions PGIM Real Estate (APAC) & PGIM Private Capital (Australia)', 'PGIM Real Estate (APAC) & PGIM Private Capital (Australia) Sanction Screening', 130, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('sd_us_customers_sanctions_pgim_latam', 'SD_US_Customers_Sanctions_PGIM_LATAM', 'SD_US_Customers_Sanctions_PGIM_LATAM', 'Search Definition Customer Sanctions PGIM LATAM', 'PGIM LATAM Sanction Screening', 140, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('sd_customers_pep_rca_international', 'SD_Customers_PEP_RCA_International', 'SD_Customers_PEP_RCA_International', 'Global Political Exposed Person', 'Global PEP Screening', 150, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('sd_us_marijuana_dj_external', 'SD_US_Marijuana_DJ_External', 'SD_US_Marijuana_DJ_External', 'Search Definition Marijuana Screening', 'Marijuana Screening', 160, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('sd_customers_sanctions_pgim_japan', 'SD_Customers_Sanctions_PGIM_JAPAN', 'SD_Customers_Sanctions_PGIM_JAPAN', 'Search Definition Customer Sanctions PGIM Japan', 'PGIM Japan Sanction Screening', 170, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT),
('sd_customers_sanctions_pgim_hk', 'SD_Customers_Sanctions_PGIM_HK', 'SD_Customers_Sanctions_PGIM_HK', 'Search Definition Customer Sanctions PGIM HongKong', 'PGIM HongKong Sanction Screening', 180, TRUE, CURRENT_TIMESTAMP::TEXT, CURRENT_TIMESTAMP::TEXT)
ON CONFLICT (normalized_source_type) DO NOTHING;

UPDATE actimize_screening_type_mappings
SET display_order = CASE normalized_source_type
  WHEN 'sanction' THEN 10
  WHEN 'pep' THEN 20
  WHEN 'ame' THEN 30
  WHEN 'fincen 314(a)' THEN 40
  WHEN 'fincen 314a' THEN 40
  WHEN 'fincen314(a)' THEN 40
  WHEN 'fincen314a' THEN 40
  WHEN 'sd_us_customers_sanctions_pgim_ma' THEN 50
  WHEN 'sd_us_customers_sanctions_pgim_cio' THEN 60
  WHEN 'sd_us_customers_sanctions_pgim_fi' THEN 70
  WHEN 'sd_us_customers_sanctions_pgim_re' THEN 80
  WHEN 'sd_us_customers_sanctions_pgim_pp_fi' THEN 90
  WHEN 'sd_us_customers_sanctions_pgim_ne_fi' THEN 100
  WHEN 'sd_us_customers_sanctions_pgim_quant' THEN 110
  WHEN 'sd_us_customers_sanctions_pgim_jk_asc' THEN 120
  WHEN 'sd_us_customers_sanctions_pgim_apac' THEN 130
  WHEN 'sd_us_customers_sanctions_pgim_latam' THEN 140
  WHEN 'sd_customers_pep_rca_international' THEN 150
  WHEN 'sd_us_marijuana_dj_external' THEN 160
  WHEN 'sd_customers_sanctions_pgim_japan' THEN 170
  WHEN 'sd_customers_sanctions_pgim_hk' THEN 180
  ELSE display_order
END
WHERE display_order = 1000;

UPDATE actimize_screening_type_mappings
SET search_definition_name = CASE normalized_source_type
  WHEN 'sanction' THEN 'Search Definition Customer Sanctions'
  WHEN 'pep' THEN 'Search Definition Customer PEP RCA International'
  WHEN 'ame' THEN 'Search Definition Customer AME'
  WHEN 'fincen 314(a)' THEN 'Search Definition Customer FinCEN 314(a)'
  WHEN 'fincen 314a' THEN 'Search Definition Customer FinCEN 314(a)'
  WHEN 'fincen314(a)' THEN 'Search Definition Customer FinCEN 314(a)'
  WHEN 'fincen314a' THEN 'Search Definition Customer FinCEN 314(a)'
  WHEN 'sd_us_customers_sanctions_pgim_ma' THEN 'Search Definition Customer Sanctions PGIM Multi-Asset Solutions / PGIM Strategic Capital Group'
  WHEN 'sd_us_customers_sanctions_pgim_cio' THEN 'Search Definition Customer Sanctions PGIM CIO'
  WHEN 'sd_us_customers_sanctions_pgim_fi' THEN 'Search Definition Customer Sanctions PGIM Fixed Income'
  WHEN 'sd_us_customers_sanctions_pgim_re' THEN 'Search Definition Customer Sanctions PGIM Real Estate'
  WHEN 'sd_us_customers_sanctions_pgim_pp_fi' THEN 'Search Definition Customer Sanctions PGIM Public and Private Fixed Income'
  WHEN 'sd_us_customers_sanctions_pgim_ne_fi' THEN 'Search Definition Customer Sanctions Public & Private Fixed Income, PGIM Netherlands B.V.'
  WHEN 'sd_us_customers_sanctions_pgim_quant' THEN 'Search Definition Customer Sanctions PGIM Quant'
  WHEN 'sd_us_customers_sanctions_pgim_jk_asc' THEN 'Search Definition Customer Sanctions Jennison Associates'
  WHEN 'sd_us_customers_sanctions_pgim_apac' THEN 'Search Definition Customer Sanctions PGIM Real Estate (APAC) & PGIM Private Capital (Australia)'
  WHEN 'sd_us_customers_sanctions_pgim_latam' THEN 'Search Definition Customer Sanctions PGIM LATAM'
  WHEN 'sd_customers_pep_rca_international' THEN 'Global Political Exposed Person'
  WHEN 'sd_us_marijuana_dj_external' THEN 'Search Definition Marijuana Screening'
  WHEN 'sd_customers_sanctions_pgim_japan' THEN 'Search Definition Customer Sanctions PGIM Japan'
  WHEN 'sd_customers_sanctions_pgim_hk' THEN 'Search Definition Customer Sanctions PGIM HongKong'
  ELSE search_definition_name
END
WHERE search_definition_name IS NULL OR TRIM(search_definition_name) = '';

UPDATE actimize_screening_type_mappings
SET screening_type_name = CASE normalized_source_type
  WHEN 'sanction' THEN 'Sanction screening for US Customer'
  WHEN 'pep' THEN 'PEP Screening Exclude US'
  WHEN 'ame' THEN 'Adverse Media Screening'
  WHEN 'fincen 314(a)' THEN 'Fincen 314a Screening'
  WHEN 'fincen 314a' THEN 'Fincen 314a Screening'
  WHEN 'fincen314(a)' THEN 'Fincen 314a Screening'
  WHEN 'fincen314a' THEN 'Fincen 314a Screening'
  WHEN 'sd_us_customers_sanctions_pgim_ma' THEN 'PGIM Multi-Asset Solutions/ PGIM Strategic Capital Group Sanction Screening'
  WHEN 'sd_us_customers_sanctions_pgim_cio' THEN 'PGIM CIO Sanction Screening'
  WHEN 'sd_us_customers_sanctions_pgim_fi' THEN 'PGIM Fixed Income Sanction Screening'
  WHEN 'sd_us_customers_sanctions_pgim_re' THEN 'Search Definition Customer Sanctions PGIM Real Estate'
  WHEN 'sd_us_customers_sanctions_pgim_pp_fi' THEN 'Search Definition Customer Sanctions PGIM Public and Private Fixed Income'
  WHEN 'sd_us_customers_sanctions_pgim_ne_fi' THEN 'Search Definition Customer Sanctions Public & Private Fixed Income, PGIM Netherlands B.V.'
  WHEN 'sd_us_customers_sanctions_pgim_quant' THEN 'Search Definition Customer Sanctions PGIM Quant'
  WHEN 'sd_us_customers_sanctions_pgim_jk_asc' THEN 'Jennison Associates Sanction Screening'
  WHEN 'sd_us_customers_sanctions_pgim_apac' THEN 'PGIM Real Estate (APAC) & PGIM Private Capital (Australia) Sanction Screening'
  WHEN 'sd_us_customers_sanctions_pgim_latam' THEN 'PGIM LATAM Sanction Screening'
  WHEN 'sd_customers_pep_rca_international' THEN 'Global PEP Screening'
  WHEN 'sd_us_marijuana_dj_external' THEN 'Marijuana Screening'
  WHEN 'sd_customers_sanctions_pgim_japan' THEN 'PGIM Japan Sanction Screening'
  WHEN 'sd_customers_sanctions_pgim_hk' THEN 'PGIM HongKong Sanction Screening'
  ELSE screening_type_name
END
WHERE screening_type_name IS NULL OR TRIM(screening_type_name) = '';

COMMIT;
