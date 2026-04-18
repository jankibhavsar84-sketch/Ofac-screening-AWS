-- Tables
-- Generated at: 2026-03-14T23:19:28.062576+00:00
-- Schema: dbacd

CREATE TABLE IF NOT EXISTS dbacd."api_access_logs" (
    "access_id" bigint DEFAULT nextval('api_access_logs_access_id_seq'::regclass) NOT NULL,
    "created_at" text NOT NULL,
    "correlation_id" text,
    "request_method" text NOT NULL,
    "request_path" text NOT NULL,
    "query_string" text,
    "status_code" integer NOT NULL,
    "duration_ms" integer NOT NULL,
    "client_ip" text,
    "user_agent" text,
    "user_id" text,
    "user_name" text,
    "auth_state" text,
    "details_json" text
);

CREATE TABLE IF NOT EXISTS dbacd."audit_events" (
    "event_id" bigint DEFAULT nextval('audit_events_event_id_seq'::regclass) NOT NULL,
    "created_at" text NOT NULL,
    "user_id" text,
    "user_name" text,
    "action" text NOT NULL,
    "entity_type" text,
    "entity_id" text,
    "details_json" text
);

CREATE TABLE IF NOT EXISTS dbacd."batch_file_uploads" (
    "upload_id" text NOT NULL,
    "schedule_id" text,
    "job_id" text,
    "user_id" text,
    "user_name" text,
    "file_name" text NOT NULL,
    "s3_bucket" text,
    "s3_key" text,
    "s3_uri" text,
    "file_hash" text,
    "record_count" integer DEFAULT 0 NOT NULL,
    "created_at" text NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "queries_s3_bucket" text,
    "queries_s3_key" text,
    "queries_s3_uri" text
);

CREATE TABLE IF NOT EXISTS dbacd."business_units" (
    "business_unit_code" text NOT NULL,
    "business_unit_name" text NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" text NOT NULL,
    "updated_at" text NOT NULL
);

CREATE TABLE IF NOT EXISTS dbacd."daily_schedules" (
    "schedule_id" text NOT NULL,
    "batch_name" text NOT NULL,
    "user_id" text,
    "user_name" text,
    "queries_json" text NOT NULL,
    "screening_types_json" text NOT NULL,
    "mock_screening" boolean DEFAULT false NOT NULL,
    "timezone" text NOT NULL,
    "run_hour" integer NOT NULL,
    "run_minute" integer NOT NULL,
    "created_at" text NOT NULL,
    "last_run_at" text,
    "next_run_at" text NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "schedule_frequency" text DEFAULT 'DAILY'::text NOT NULL,
    "source_upload_id" text,
    "source_file_name" text,
    "source_s3_uri" text,
    "business_unit_code" text
);

CREATE TABLE IF NOT EXISTS dbacd."external_api_errors" (
    "error_id" bigint DEFAULT nextval('external_api_errors_error_id_seq'::regclass) NOT NULL,
    "created_at" text NOT NULL,
    "provider" text NOT NULL,
    "operation" text,
    "endpoint" text,
    "status_code" integer,
    "user_id" text,
    "user_name" text,
    "job_id" text,
    "item_key" text,
    "error_text" text NOT NULL,
    "details_json" text
);

CREATE TABLE IF NOT EXISTS dbacd."actimize_alert_callbacks" (
    "callback_id" bigint DEFAULT nextval('actimize_alert_callbacks_callback_id_seq'::regclass) NOT NULL,
    "created_at" text NOT NULL,
    "unique_key" text NOT NULL,
    "normalized_unique_key" text NOT NULL,
    "alert_id" text NOT NULL,
    "screening_cd" text,
    "status_cd" text NOT NULL,
    "update_timestamp" text,
    "source_system_cd" text,
    "tenant_cd" text,
    "matched_count" integer DEFAULT 0 NOT NULL,
    "details_json" text
);

CREATE TABLE IF NOT EXISTS dbacd."job_items" (
    "job_id" text NOT NULL,
    "item_key" text NOT NULL,
    "request_json" text NOT NULL,
    "response_json" text,
    "status" text NOT NULL,
    "error_text" text,
    "updated_at" text NOT NULL
);

CREATE TABLE IF NOT EXISTS dbacd."job_metadata" (
    "job_id" text NOT NULL,
    "mode" text DEFAULT 'BATCH'::text NOT NULL,
    "screening_types_json" text DEFAULT '[]'::text NOT NULL,
    "mock_screening" boolean DEFAULT false NOT NULL,
    "batch_name" text,
    "file_name" text,
    "daily_screening" boolean DEFAULT false NOT NULL,
    "schedule_frequency" text,
    "daily_schedule_id" text,
    "query_count" integer DEFAULT 0 NOT NULL,
    "deferred_until" text,
    "business_unit_code" text
);

CREATE TABLE IF NOT EXISTS dbacd."job_schedule_notifications" (
    "job_id" text NOT NULL,
    "schedule_id" text NOT NULL,
    "created_at" text NOT NULL
);

CREATE TABLE IF NOT EXISTS dbacd."jobs" (
    "job_id" text NOT NULL,
    "status" text NOT NULL,
    "created_at" text NOT NULL,
    "updated_at" text NOT NULL,
    "total_items" integer NOT NULL,
    "source_schedule_id" text,
    "source_upload_id" text,
    "user_id" text,
    "user_name" text
);

CREATE TABLE IF NOT EXISTS dbacd."schedule_notifications" (
    "notification_id" bigint DEFAULT nextval('schedule_notifications_notification_id_seq'::regclass) NOT NULL,
    "created_at" text NOT NULL,
    "user_id" text,
    "user_name" text,
    "email" text,
    "schedule_id" text,
    "job_id" text,
    "title" text NOT NULL,
    "message" text NOT NULL,
    "summary_json" text
);

CREATE TABLE IF NOT EXISTS dbacd."schedule_record_state" (
    "schedule_id" text NOT NULL,
    "record_hash" text NOT NULL,
    "first_seen_at" text NOT NULL,
    "last_screened_at" text NOT NULL,
    "last_job_id" text
);

CREATE TABLE IF NOT EXISTS dbacd."schedule_subscriptions" (
    "subscription_id" text NOT NULL,
    "schedule_id" text NOT NULL,
    "user_id" text,
    "user_name" text,
    "email" text NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" text NOT NULL,
    "updated_at" text NOT NULL
);

CREATE TABLE IF NOT EXISTS dbacd."user_business_units" (
    "user_id" text NOT NULL,
    "user_name" text,
    "business_unit_code" text NOT NULL,
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" text NOT NULL,
    "updated_at" text NOT NULL
);

