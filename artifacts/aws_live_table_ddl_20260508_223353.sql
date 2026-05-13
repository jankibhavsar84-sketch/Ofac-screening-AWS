-- Live table DDL extracted from AWS RDS PostgreSQL
-- Extracted at UTC: 2026-05-08T22:33:53.752432+00:00
-- Source: account 981450247094, region us-east-2, secret ofac-screening/database-config

CREATE TABLE public.actimize_alert_callbacks (
    callback_id bigint DEFAULT nextval('actimize_alert_callbacks_callback_id_seq'::regclass) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    unique_key text NOT NULL,
    normalized_unique_key text NOT NULL,
    alert_id text NOT NULL,
    screening_cd text,
    status_cd text NOT NULL,
    update_timestamp text,
    source_system_cd text,
    tenant_cd text,
    matched_count integer DEFAULT 0 NOT NULL,
    details_json text,
    CONSTRAINT actimize_alert_callbacks_pkey PRIMARY KEY (callback_id)
);

CREATE TABLE public.actimize_screening_type_mappings (
    Search_Definition_ID character varying(50) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    search_definition_name character varying(255) DEFAULT ''::text NOT NULL,
    Screening_Type character varying(10) DEFAULT ''::text NOT NULL,
    display_order integer DEFAULT 1000 NOT NULL,
    CONSTRAINT actimize_screening_type_mappings_pkey PRIMARY KEY ("Screening_Type")
);

CREATE TABLE public.api_access_logs (
    access_id bigint DEFAULT nextval('api_access_logs_access_id_seq'::regclass) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    correlation_id text,
    request_method text NOT NULL,
    request_path text NOT NULL,
    query_string text,
    status_code integer NOT NULL,
    duration_ms integer NOT NULL,
    client_ip text,
    user_agent text,
    user_name text,
    auth_state text,
    details_json text,
    user_ref_id bigint,
    CONSTRAINT api_access_logs_pkey PRIMARY KEY (access_id),
    CONSTRAINT fk_api_access_logs_user_ref_id FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id)
);

CREATE TABLE public.app_users (
    user_id bigint NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    name character varying(255),
    email character varying(50),
    old_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT app_users_pkey PRIMARY KEY (user_id),
    CONSTRAINT app_users_old_id_key UNIQUE (old_id)
);

CREATE TABLE public.audit_events (
    event_id bigint DEFAULT nextval('audit_events_event_id_seq'::regclass) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    user_name text,
    action text NOT NULL,
    entity_type text,
    entity_id text,
    details_json text,
    user_ref_id bigint,
    CONSTRAINT audit_events_pkey PRIMARY KEY (event_id),
    CONSTRAINT fk_audit_events_user_ref_id FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id)
);

CREATE TABLE public.batch_file_uploads (
    upload_id text NOT NULL,
    schedule_id text,
    job_id text,
    file_name text NOT NULL,
    s3_bucket text,
    s3_key text,
    s3_uri text,
    queries_s3_bucket text,
    queries_s3_key text,
    queries_s3_uri text,
    file_hash text,
    record_count integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    user_ref_id bigint,
    job_seq_id bigint,
    CONSTRAINT batch_file_uploads_pkey PRIMARY KEY (upload_id),
    CONSTRAINT fk_batch_file_uploads_job_id FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE SET NULL,
    CONSTRAINT fk_batch_file_uploads_job_seq_id FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE SET NULL,
    CONSTRAINT fk_batch_file_uploads_user_ref_id FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id)
);

CREATE TABLE public.business_units (
    business_unit_code character varying(50) NOT NULL,
    business_unit_name character varying(255) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT business_units_pkey PRIMARY KEY (business_unit_code)
);

CREATE TABLE public.daily_schedules (
    schedule_id text NOT NULL,
    batch_name text NOT NULL,
    queries_json text NOT NULL,
    screening_types_json text NOT NULL,
    mock_screening boolean DEFAULT false NOT NULL,
    schedule_frequency text DEFAULT 'DAILY'::text NOT NULL,
    timezone text NOT NULL,
    run_hour integer NOT NULL,
    run_minute integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_run_at timestamp with time zone,
    next_run_at timestamp with time zone DEFAULT now() NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    source_upload_id text,
    source_file_name text,
    source_s3_uri text,
    business_unit_code character varying(50),
    user_ref_id bigint,
    CONSTRAINT daily_schedules_pkey PRIMARY KEY (schedule_id),
    CONSTRAINT fk_daily_schedules_business_unit_code FOREIGN KEY (business_unit_code) REFERENCES business_units(business_unit_code) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_daily_schedules_user_ref_id FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id)
);

CREATE TABLE public.external_api_errors (
    error_id bigint DEFAULT nextval('external_api_errors_error_id_seq'::regclass) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    provider text NOT NULL,
    operation text,
    endpoint text,
    status_code integer,
    user_name text,
    item_key text,
    error_text text NOT NULL,
    details_json text,
    user_ref_id bigint,
    job_seq_id bigint,
    CONSTRAINT external_api_errors_pkey PRIMARY KEY (error_id),
    CONSTRAINT fk_external_api_errors_job_seq_id FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE SET NULL,
    CONSTRAINT fk_external_api_errors_user_ref_id FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id)
);

CREATE TABLE public.job_items (
    job_id text NOT NULL,
    item_key text NOT NULL,
    request_json text NOT NULL,
    response_json text,
    status text NOT NULL,
    error_text text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    parsed_status character varying(16) DEFAULT 'PENDING'::character varying NOT NULL,
    job_seq_id bigint NOT NULL,
    user_ref_id bigint,
    CONSTRAINT job_items_pkey PRIMARY KEY (job_id, item_key),
    CONSTRAINT fk_job_items_job_seq_id FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE CASCADE,
    CONSTRAINT fk_job_items_user_ref_id FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id),
    CONSTRAINT job_items_job_id_fkey FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
    CONSTRAINT job_items_parsed_status_check CHECK (((parsed_status)::text = ANY ((ARRAY['CLEAR'::character varying, 'POTENTIAL'::character varying, 'PENDING'::character varying, 'FAILED'::character varying])::text[])))
);

CREATE TABLE public.job_metadata (
    job_id text NOT NULL,
    mode text DEFAULT 'BATCH'::text NOT NULL,
    screening_types_json text DEFAULT '[]'::text NOT NULL,
    mock_screening boolean DEFAULT false NOT NULL,
    batch_name text,
    file_name text,
    daily_screening boolean DEFAULT false NOT NULL,
    schedule_frequency text,
    daily_schedule_id text,
    query_count integer DEFAULT 0 NOT NULL,
    deferred_until text,
    business_unit_code character varying(50),
    job_seq_id bigint NOT NULL,
    CONSTRAINT job_metadata_pkey PRIMARY KEY (job_id),
    CONSTRAINT fk_job_metadata_business_unit_code FOREIGN KEY (business_unit_code) REFERENCES business_units(business_unit_code) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_job_metadata_job_id FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
    CONSTRAINT fk_job_metadata_job_seq_id FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE CASCADE
);

CREATE TABLE public.job_schedule_notifications (
    job_id text NOT NULL,
    schedule_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    job_seq_id bigint NOT NULL,
    CONSTRAINT job_schedule_notifications_pkey PRIMARY KEY (job_id),
    CONSTRAINT fk_job_schedule_notifications_job_id FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
    CONSTRAINT fk_job_schedule_notifications_job_seq_id FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE CASCADE
);

CREATE TABLE public.jobs (
    job_id text NOT NULL,
    status text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    total_items integer NOT NULL,
    source_schedule_id text,
    source_upload_id text,
    job_seq_id bigint DEFAULT nextval('jobs_job_seq_id_seq'::regclass) NOT NULL,
    user_ref_id bigint,
    CONSTRAINT jobs_pkey PRIMARY KEY (job_id),
    CONSTRAINT fk_jobs_user_ref_id FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id)
);

CREATE TABLE public.schedule_notifications (
    notification_id bigint DEFAULT nextval('schedule_notifications_notification_id_seq'::regclass) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    user_name text,
    email text,
    schedule_id text,
    job_id text,
    title text NOT NULL,
    message text NOT NULL,
    summary_json text,
    user_ref_id bigint,
    job_seq_id bigint,
    CONSTRAINT schedule_notifications_pkey PRIMARY KEY (notification_id),
    CONSTRAINT fk_schedule_notifications_job_id FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE SET NULL,
    CONSTRAINT fk_schedule_notifications_job_seq_id FOREIGN KEY (job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE SET NULL,
    CONSTRAINT fk_schedule_notifications_user_ref_id FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id)
);

CREATE TABLE public.schedule_record_state (
    schedule_id text NOT NULL,
    record_hash text NOT NULL,
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_screened_at timestamp with time zone DEFAULT now() NOT NULL,
    last_job_id text,
    last_job_seq_id bigint,
    CONSTRAINT schedule_record_state_pkey PRIMARY KEY (schedule_id, record_hash),
    CONSTRAINT fk_schedule_record_state_last_job_id FOREIGN KEY (last_job_id) REFERENCES jobs(job_id) ON DELETE SET NULL,
    CONSTRAINT fk_schedule_record_state_last_job_seq_id FOREIGN KEY (last_job_seq_id) REFERENCES jobs(job_seq_id) ON DELETE SET NULL
);

CREATE TABLE public.schedule_subscriptions (
    subscription_id text NOT NULL,
    schedule_id text NOT NULL,
    email text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    user_ref_id bigint,
    CONSTRAINT schedule_subscriptions_pkey PRIMARY KEY (subscription_id),
    CONSTRAINT fk_schedule_subscriptions_user_ref_id FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id)
);

CREATE TABLE public.user_business_units (
    business_unit_code character varying(50) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    user_ref_id bigint NOT NULL,
    CONSTRAINT user_business_units_pkey PRIMARY KEY (user_ref_id, business_unit_code),
    CONSTRAINT fk_user_business_units_business_unit_code FOREIGN KEY (business_unit_code) REFERENCES business_units(business_unit_code) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_user_business_units_user_ref_id FOREIGN KEY (user_ref_id) REFERENCES app_users(user_id)
);
