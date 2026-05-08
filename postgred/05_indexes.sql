-- Indexes (non-constraint)
-- Generated at: 2026-03-14T23:19:28.960118+00:00
-- Schema: dbacd

CREATE INDEX idx_api_access_logs_correlation ON dbacd.api_access_logs USING btree (correlation_id, created_at);
CREATE INDEX idx_api_access_logs_created_at ON dbacd.api_access_logs USING btree (created_at);
CREATE INDEX idx_api_access_logs_path ON dbacd.api_access_logs USING btree (request_path, created_at);
CREATE INDEX idx_api_access_logs_user_ref_created_at ON dbacd.api_access_logs USING btree (user_ref_id, created_at, access_id);
CREATE INDEX idx_daily_schedules_next_run ON dbacd.daily_schedules USING btree (next_run_at);
CREATE INDEX idx_daily_schedules_active_created ON dbacd.daily_schedules USING btree (is_active, created_at DESC, schedule_id);
CREATE INDEX idx_daily_schedules_user_ref ON dbacd.daily_schedules USING btree (user_ref_id, created_at, schedule_id);
CREATE INDEX idx_external_api_errors_created_at ON dbacd.external_api_errors USING btree (created_at);
CREATE INDEX idx_external_api_errors_job_item ON dbacd.external_api_errors USING btree (job_seq_id, item_key, created_at);
CREATE INDEX idx_external_api_errors_job_seq_id ON dbacd.external_api_errors USING btree (job_seq_id, created_at, error_id);
CREATE INDEX idx_external_api_errors_user_ref_created_at ON dbacd.external_api_errors USING btree (user_ref_id, created_at, error_id);
CREATE INDEX idx_actimize_callbacks_unique_key_created_at ON dbacd.actimize_alert_callbacks USING btree (normalized_unique_key, created_at);
CREATE INDEX idx_actimize_callbacks_alert_id ON dbacd.actimize_alert_callbacks USING btree (alert_id, created_at);
CREATE INDEX idx_notifications_email ON dbacd.schedule_notifications USING btree (email, created_at);
CREATE INDEX idx_schedule_notifications_user_ref ON dbacd.schedule_notifications USING btree (user_ref_id, created_at, notification_id);
CREATE INDEX idx_schedule_subscriptions_user_ref ON dbacd.schedule_subscriptions USING btree (user_ref_id, created_at, subscription_id);
CREATE UNIQUE INDEX idx_app_users_old_id ON dbacd.app_users USING btree (old_id);
CREATE INDEX idx_app_users_email ON dbacd.app_users USING btree (email);
CREATE INDEX idx_jobs_user_ref ON dbacd.jobs USING btree (user_ref_id, updated_at, created_at, job_seq_id);
CREATE UNIQUE INDEX idx_jobs_job_seq_id ON dbacd.jobs USING btree (job_seq_id);
CREATE UNIQUE INDEX idx_schedule_subscriptions_unique ON dbacd.schedule_subscriptions USING btree (schedule_id, email);
CREATE INDEX idx_user_business_units_code ON dbacd.user_business_units USING btree (business_unit_code, is_active);
CREATE INDEX idx_user_business_units_user_ref ON dbacd.user_business_units USING btree (user_ref_id, is_active, business_unit_code);
CREATE INDEX idx_audit_events_user_ref_event ON dbacd.audit_events USING btree (user_ref_id, event_id DESC);
CREATE INDEX idx_batch_file_uploads_user_ref ON dbacd.batch_file_uploads USING btree (user_ref_id, created_at, upload_id);
CREATE INDEX idx_batch_file_uploads_job_seq_id ON dbacd.batch_file_uploads USING btree (job_seq_id, created_at, upload_id);
CREATE INDEX idx_schedule_notifications_job_seq_id ON dbacd.schedule_notifications USING btree (job_seq_id, created_at, notification_id);
CREATE INDEX idx_job_items_job_seq_sort ON dbacd.job_items USING btree (job_seq_id, updated_at DESC, item_key);
CREATE INDEX idx_job_items_job_seq_parsed_status ON dbacd.job_items USING btree (job_seq_id, parsed_status);
CREATE UNIQUE INDEX idx_job_metadata_job_seq_id ON dbacd.job_metadata USING btree (job_seq_id);
CREATE UNIQUE INDEX idx_job_schedule_notifications_job_seq_id ON dbacd.job_schedule_notifications USING btree (job_seq_id);
CREATE INDEX idx_schedule_record_state_last_job_seq_id ON dbacd.schedule_record_state USING btree (last_job_seq_id);
