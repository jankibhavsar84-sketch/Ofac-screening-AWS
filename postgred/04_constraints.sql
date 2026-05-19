-- Table Constraints
-- Generated at: 2026-05-08T22:36:36.285888+00:00
-- Schema: public

ALTER TABLE ONLY public."actimize_alert_callbacks" ADD CONSTRAINT "actimize_alert_callbacks_pkey" PRIMARY KEY (callback_id);

ALTER TABLE ONLY public."actimize_screening_type_mappings" ADD CONSTRAINT "actimize_screening_type_mappings_pkey" PRIMARY KEY ("Screening_Type");

ALTER TABLE ONLY public."api_access_logs" ADD CONSTRAINT "api_access_logs_pkey" PRIMARY KEY (access_id);

ALTER TABLE ONLY public."api_access_logs" ADD CONSTRAINT "fk_api_access_logs_user_ref_id" FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);

ALTER TABLE ONLY public."app_users" ADD CONSTRAINT "app_users_pkey" PRIMARY KEY (user_id);

ALTER TABLE ONLY public."app_users" ADD CONSTRAINT "app_users_old_id_key" UNIQUE (old_id);

ALTER TABLE ONLY public."audit_events" ADD CONSTRAINT "audit_events_pkey" PRIMARY KEY (event_id);

ALTER TABLE ONLY public."audit_events" ADD CONSTRAINT "fk_audit_events_user_ref_id" FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);

ALTER TABLE ONLY public."batch_file_uploads" ADD CONSTRAINT "batch_file_uploads_pkey" PRIMARY KEY (upload_id);

ALTER TABLE ONLY public."batch_file_uploads" ADD CONSTRAINT "fk_batch_file_uploads_job_id" FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE SET NULL;

ALTER TABLE ONLY public."batch_file_uploads" ADD CONSTRAINT "fk_batch_file_uploads_job_seq_id" FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE SET NULL;

ALTER TABLE ONLY public."batch_file_uploads" ADD CONSTRAINT "fk_batch_file_uploads_user_ref_id" FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);

ALTER TABLE ONLY public."business_units" ADD CONSTRAINT "business_units_pkey" PRIMARY KEY (business_unit_code);

ALTER TABLE ONLY public."business_unit_screening_types" ADD CONSTRAINT "business_unit_screening_types_pkey" PRIMARY KEY (business_unit_code, "Screening_Type");

ALTER TABLE ONLY public."business_unit_screening_types" ADD CONSTRAINT "fk_business_unit_screening_types_business_unit_code" FOREIGN KEY (business_unit_code) REFERENCES business_units(business_unit_code) ON UPDATE CASCADE ON DELETE RESTRICT;

ALTER TABLE ONLY public."business_unit_screening_types" ADD CONSTRAINT "fk_business_unit_screening_types_screening_type" FOREIGN KEY ("Screening_Type") REFERENCES "actimize_screening_type_mappings"("Screening_Type") ON UPDATE CASCADE ON DELETE RESTRICT;

ALTER TABLE ONLY public."Batch_Schedule" ADD CONSTRAINT "Batch_Schedule_pkey" PRIMARY KEY (schedule_id);

ALTER TABLE ONLY public."Batch_Schedule" ADD CONSTRAINT "fk_Batch_Schedule_business_unit_code" FOREIGN KEY (business_unit_code) REFERENCES business_units(business_unit_code) ON UPDATE CASCADE ON DELETE RESTRICT;

ALTER TABLE ONLY public."Batch_Schedule" ADD CONSTRAINT "fk_Batch_Schedule_user_ref_id" FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);

ALTER TABLE ONLY public."external_api_errors" ADD CONSTRAINT "external_api_errors_pkey" PRIMARY KEY (error_id);

ALTER TABLE ONLY public."external_api_errors" ADD CONSTRAINT "fk_external_api_errors_job_seq_id" FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE SET NULL;

ALTER TABLE ONLY public."external_api_errors" ADD CONSTRAINT "fk_external_api_errors_user_ref_id" FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);

ALTER TABLE ONLY public."job_items" ADD CONSTRAINT "job_items_pkey" PRIMARY KEY (job_id, item_key);

ALTER TABLE ONLY public."job_items" ADD CONSTRAINT "fk_job_items_job_seq_id" FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE CASCADE;

ALTER TABLE ONLY public."job_items" ADD CONSTRAINT "fk_job_items_user_ref_id" FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);

ALTER TABLE ONLY public."job_items" ADD CONSTRAINT "job_items_job_id_fkey" FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE;

ALTER TABLE ONLY public."job_items" ADD CONSTRAINT "job_items_parsed_status_check" CHECK (((parsed_status)::text = ANY ((ARRAY['CLEAR'::character varying, 'POTENTIAL'::character varying, 'PENDING'::character varying, 'FAILED'::character varying])::text[])));

ALTER TABLE ONLY public."job_metadata" ADD CONSTRAINT "job_metadata_pkey" PRIMARY KEY (job_id);

ALTER TABLE ONLY public."job_metadata" ADD CONSTRAINT "fk_job_metadata_business_unit_code" FOREIGN KEY (business_unit_code) REFERENCES business_units(business_unit_code) ON UPDATE CASCADE ON DELETE RESTRICT;

ALTER TABLE ONLY public."job_metadata" ADD CONSTRAINT "fk_job_metadata_job_id" FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE;

ALTER TABLE ONLY public."job_metadata" ADD CONSTRAINT "fk_job_metadata_job_seq_id" FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE CASCADE;

ALTER TABLE ONLY public."job_schedule_notifications" ADD CONSTRAINT "job_schedule_notifications_pkey" PRIMARY KEY (job_id);

ALTER TABLE ONLY public."job_schedule_notifications" ADD CONSTRAINT "fk_job_schedule_notifications_job_id" FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE;

ALTER TABLE ONLY public."job_schedule_notifications" ADD CONSTRAINT "fk_job_schedule_notifications_job_seq_id" FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE CASCADE;

ALTER TABLE ONLY public."jobs" ADD CONSTRAINT "jobs_pkey" PRIMARY KEY (job_id);

ALTER TABLE ONLY public."jobs" ADD CONSTRAINT "fk_jobs_user_ref_id" FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);

ALTER TABLE ONLY public."schedule_notifications" ADD CONSTRAINT "schedule_notifications_pkey" PRIMARY KEY (notification_id);

ALTER TABLE ONLY public."schedule_notifications" ADD CONSTRAINT "fk_schedule_notifications_job_id" FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE SET NULL;

ALTER TABLE ONLY public."schedule_notifications" ADD CONSTRAINT "fk_schedule_notifications_job_seq_id" FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE SET NULL;

ALTER TABLE ONLY public."schedule_notifications" ADD CONSTRAINT "fk_schedule_notifications_user_ref_id" FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);

ALTER TABLE ONLY public."schedule_record_state" ADD CONSTRAINT "schedule_record_state_pkey" PRIMARY KEY (schedule_id, record_hash);

ALTER TABLE ONLY public."schedule_record_state" ADD CONSTRAINT "fk_schedule_record_state_last_job_id" FOREIGN KEY (last_job_id) REFERENCES jobs(job_id) ON DELETE SET NULL;

ALTER TABLE ONLY public."schedule_record_state" ADD CONSTRAINT "fk_schedule_record_state_last_job_seq_id" FOREIGN KEY (last_job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE SET NULL;

ALTER TABLE ONLY public."schedule_subscriptions" ADD CONSTRAINT "schedule_subscriptions_pkey" PRIMARY KEY (subscription_id);

ALTER TABLE ONLY public."schedule_subscriptions" ADD CONSTRAINT "fk_schedule_subscriptions_user_ref_id" FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);


ALTER TABLE ONLY public."batch_file_uploads" ADD CONSTRAINT "fk_batch_file_uploads_schedule_id" FOREIGN KEY (schedule_id) REFERENCES "Batch_Schedule"(schedule_id) ON DELETE SET NULL;

ALTER TABLE ONLY public."job_metadata" ADD CONSTRAINT "fk_job_metadata_daily_schedule_id" FOREIGN KEY (daily_schedule_id) REFERENCES "Batch_Schedule"(schedule_id) ON DELETE SET NULL;

ALTER TABLE ONLY public."job_schedule_notifications" ADD CONSTRAINT "fk_job_schedule_notifications_schedule_id" FOREIGN KEY (schedule_id) REFERENCES "Batch_Schedule"(schedule_id) ON DELETE CASCADE;

ALTER TABLE ONLY public."jobs" ADD CONSTRAINT "fk_jobs_source_schedule_id" FOREIGN KEY (source_schedule_id) REFERENCES "Batch_Schedule"(schedule_id) ON DELETE SET NULL;

ALTER TABLE ONLY public."schedule_notifications" ADD CONSTRAINT "fk_schedule_notifications_schedule_id" FOREIGN KEY (schedule_id) REFERENCES "Batch_Schedule"(schedule_id) ON DELETE SET NULL;

ALTER TABLE ONLY public."schedule_record_state" ADD CONSTRAINT "fk_schedule_record_state_schedule_id" FOREIGN KEY (schedule_id) REFERENCES "Batch_Schedule"(schedule_id) ON DELETE CASCADE;

ALTER TABLE ONLY public."schedule_subscriptions" ADD CONSTRAINT "fk_schedule_subscriptions_schedule_id" FOREIGN KEY (schedule_id) REFERENCES "Batch_Schedule"(schedule_id) ON DELETE CASCADE;

ALTER TABLE ONLY public."user_business_units" ADD CONSTRAINT "user_business_units_pkey" PRIMARY KEY (user_ref_id, business_unit_code);

ALTER TABLE ONLY public."user_business_units" ADD CONSTRAINT "fk_user_business_units_business_unit_code" FOREIGN KEY (business_unit_code) REFERENCES business_units(business_unit_code) ON UPDATE CASCADE ON DELETE RESTRICT;

ALTER TABLE ONLY public."user_business_units" ADD CONSTRAINT "fk_user_business_units_user_ref_id" FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id);
