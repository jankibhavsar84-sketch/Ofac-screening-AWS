-- Indexes (non-constraint)
-- Generated at: 2026-05-08T22:36:36.285888+00:00
-- Schema: public

CREATE INDEX idx_actimize_callbacks_alert_id ON public.actimize_alert_callbacks USING btree (alert_id, created_at);
CREATE INDEX idx_actimize_callbacks_unique_key_created_at ON public.actimize_alert_callbacks USING btree (normalized_unique_key, created_at);
CREATE INDEX idx_api_access_logs_correlation ON public.api_access_logs USING btree (correlation_id, created_at);
CREATE INDEX idx_api_access_logs_created_at ON public.api_access_logs USING btree (created_at);
CREATE INDEX idx_api_access_logs_path ON public.api_access_logs USING btree (request_path, created_at);
CREATE INDEX idx_api_access_logs_user_ref_created_at ON public.api_access_logs USING btree (user_ref_id, created_at DESC, access_id DESC);
CREATE INDEX idx_app_users_email ON public.app_users USING btree (email);
CREATE UNIQUE INDEX idx_app_users_old_id ON public.app_users USING btree (old_id);
CREATE INDEX idx_audit_events_event_id ON public.audit_events USING btree (event_id DESC);
CREATE INDEX idx_audit_events_user_ref_event ON public.audit_events USING btree (user_ref_id, event_id DESC);
CREATE INDEX idx_batch_file_uploads_job_seq_id ON public.batch_file_uploads USING btree (job_seq_id);
CREATE INDEX idx_batch_file_uploads_user_ref ON public.batch_file_uploads USING btree (user_ref_id, created_at DESC, upload_id);
CREATE INDEX idx_business_unit_screening_types_bu_active ON public.business_unit_screening_types USING btree (business_unit_code, is_active, "Screening_Type");
CREATE INDEX idx_business_unit_screening_types_screening_active ON public.business_unit_screening_types USING btree ("Screening_Type", is_active, business_unit_code);
CREATE INDEX idx_batch_schedule_active_created ON public."Batch_Schedule" USING btree (is_active, created_at DESC, schedule_id);
CREATE INDEX idx_batch_schedule_next_run ON public."Batch_Schedule" USING btree (next_run_at);
CREATE INDEX idx_batch_schedule_user_ref ON public."Batch_Schedule" USING btree (user_ref_id, created_at DESC, schedule_id);
CREATE INDEX idx_external_api_errors_created_at ON public.external_api_errors USING btree (created_at);
CREATE INDEX idx_external_api_errors_job_item ON public.external_api_errors USING btree (job_seq_id, item_key, created_at);
CREATE INDEX idx_external_api_errors_job_seq_id ON public.external_api_errors USING btree (job_seq_id);
CREATE INDEX idx_external_api_errors_user_ref_created_at ON public.external_api_errors USING btree (user_ref_id, created_at DESC, error_id DESC);
CREATE INDEX idx_job_items_item_key ON public.job_items USING btree (item_key);
CREATE INDEX idx_job_items_job_seq_parsed_status ON public.job_items USING btree (job_seq_id, parsed_status);
CREATE INDEX idx_job_items_job_seq_sort ON public.job_items USING btree (job_seq_id, updated_at DESC, item_key);
CREATE INDEX idx_job_items_parsed_status ON public.job_items USING btree (parsed_status);
CREATE INDEX idx_job_items_user_ref_id ON public.job_items USING btree (user_ref_id);
CREATE UNIQUE INDEX idx_job_metadata_job_seq_id ON public.job_metadata USING btree (job_seq_id);
CREATE UNIQUE INDEX idx_job_schedule_notifications_job_seq_id ON public.job_schedule_notifications USING btree (job_seq_id);
CREATE INDEX idx_jobs_user_ref ON public.jobs USING btree (user_ref_id, updated_at DESC, created_at DESC, job_id);
CREATE UNIQUE INDEX idx_mv_daily_schedule_batch_runs_job ON public.mv_daily_schedule_batch_runs USING btree (job_id);
CREATE INDEX idx_mv_daily_schedule_batch_runs_sched_created ON public.mv_daily_schedule_batch_runs USING btree (schedule_id, created_at DESC, job_id);
CREATE UNIQUE INDEX idx_mv_user_recent_results_pk ON public.mv_user_recent_results USING btree (job_id, item_key);
CREATE INDEX idx_mv_user_recent_results_user_sort ON public.mv_user_recent_results USING btree (user_ref_id, sort_ts DESC, job_id, item_key);
CREATE UNIQUE INDEX idx_mv_user_result_summary_counts_user ON public.mv_user_result_summary_counts USING btree (user_ref_id);
CREATE UNIQUE INDEX idx_mv_user_submission_jobs_pk ON public.mv_user_submission_jobs USING btree (job_id);
CREATE INDEX idx_mv_user_submission_jobs_user_created ON public.mv_user_submission_jobs USING btree (user_ref_id, created_at DESC, job_id);
CREATE INDEX idx_mv_user_submission_jobs_user_name_created ON public.mv_user_submission_jobs USING btree (lower(COALESCE(NULLIF((user_name)::text, ''::text), user_id, ''::text)), created_at DESC, job_id);
CREATE INDEX idx_notifications_email ON public.schedule_notifications USING btree (email, created_at);
CREATE INDEX idx_schedule_notifications_job_seq_id ON public.schedule_notifications USING btree (job_seq_id);
CREATE INDEX idx_schedule_notifications_user_ref ON public.schedule_notifications USING btree (user_ref_id, created_at DESC, notification_id);
CREATE INDEX idx_schedule_record_state_last_job_seq_id ON public.schedule_record_state USING btree (last_job_seq_id);
CREATE UNIQUE INDEX idx_schedule_subscriptions_unique ON public.schedule_subscriptions USING btree (schedule_id, email);
CREATE INDEX idx_schedule_subscriptions_user_ref ON public.schedule_subscriptions USING btree (user_ref_id, created_at DESC, subscription_id);
CREATE INDEX idx_user_business_units_code ON public.user_business_units USING btree (business_unit_code, is_active);
CREATE INDEX idx_user_business_units_user_ref ON public.user_business_units USING btree (user_ref_id, is_active, business_unit_code);
