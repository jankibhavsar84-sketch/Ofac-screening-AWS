-- Indexes (non-constraint)
-- Generated at: 2026-03-14T23:19:28.960118+00:00
-- Schema: dbacd

CREATE INDEX idx_api_access_logs_correlation ON dbacd.api_access_logs USING btree (correlation_id, created_at);
CREATE INDEX idx_api_access_logs_created_at ON dbacd.api_access_logs USING btree (created_at);
CREATE INDEX idx_api_access_logs_path ON dbacd.api_access_logs USING btree (request_path, created_at);
CREATE INDEX idx_api_access_logs_user ON dbacd.api_access_logs USING btree (user_id, created_at);
CREATE INDEX idx_daily_schedules_next_run ON dbacd.daily_schedules USING btree (next_run_at);
CREATE INDEX idx_external_api_errors_created_at ON dbacd.external_api_errors USING btree (created_at);
CREATE INDEX idx_external_api_errors_job_item ON dbacd.external_api_errors USING btree (job_id, item_key, created_at);
CREATE INDEX idx_notifications_email ON dbacd.schedule_notifications USING btree (email, created_at);
CREATE INDEX idx_notifications_user ON dbacd.schedule_notifications USING btree (user_id, created_at);
CREATE UNIQUE INDEX idx_schedule_subscriptions_unique ON dbacd.schedule_subscriptions USING btree (schedule_id, email);
CREATE INDEX idx_user_business_units_code ON dbacd.user_business_units USING btree (business_unit_code, is_active);
CREATE INDEX idx_user_business_units_user ON dbacd.user_business_units USING btree (user_id, is_active);
