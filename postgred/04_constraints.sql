-- Table Constraints
-- Generated at: 2026-03-14T23:19:28.525842+00:00
-- Schema: dbacd

ALTER TABLE ONLY dbacd."api_access_logs" ADD CONSTRAINT "api_access_logs_pkey" PRIMARY KEY (access_id);

ALTER TABLE ONLY dbacd."audit_events" ADD CONSTRAINT "audit_events_pkey" PRIMARY KEY (event_id);

ALTER TABLE ONLY dbacd."batch_file_uploads" ADD CONSTRAINT "batch_file_uploads_pkey" PRIMARY KEY (upload_id);

ALTER TABLE ONLY dbacd."business_units" ADD CONSTRAINT "business_units_pkey" PRIMARY KEY (business_unit_code);

ALTER TABLE ONLY dbacd."daily_schedules" ADD CONSTRAINT "daily_schedules_pkey" PRIMARY KEY (schedule_id);

ALTER TABLE ONLY dbacd."external_api_errors" ADD CONSTRAINT "external_api_errors_pkey" PRIMARY KEY (error_id);

ALTER TABLE ONLY dbacd."actimize_alert_callbacks" ADD CONSTRAINT "actimize_alert_callbacks_pkey" PRIMARY KEY (callback_id);

ALTER TABLE ONLY dbacd."job_items" ADD CONSTRAINT "job_items_pkey" PRIMARY KEY (job_id, item_key);
ALTER TABLE ONLY dbacd."job_items" ADD CONSTRAINT "job_items_job_id_fkey" FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE;

ALTER TABLE ONLY dbacd."job_metadata" ADD CONSTRAINT "job_metadata_pkey" PRIMARY KEY (job_id);

ALTER TABLE ONLY dbacd."job_schedule_notifications" ADD CONSTRAINT "job_schedule_notifications_pkey" PRIMARY KEY (job_id);

ALTER TABLE ONLY dbacd."jobs" ADD CONSTRAINT "jobs_pkey" PRIMARY KEY (job_id);

ALTER TABLE ONLY dbacd."schedule_notifications" ADD CONSTRAINT "schedule_notifications_pkey" PRIMARY KEY (notification_id);

ALTER TABLE ONLY dbacd."schedule_record_state" ADD CONSTRAINT "schedule_record_state_pkey" PRIMARY KEY (schedule_id, record_hash);

ALTER TABLE ONLY dbacd."schedule_subscriptions" ADD CONSTRAINT "schedule_subscriptions_pkey" PRIMARY KEY (subscription_id);

ALTER TABLE ONLY dbacd."user_business_units" ADD CONSTRAINT "user_business_units_pkey" PRIMARY KEY (user_id, business_unit_code);

