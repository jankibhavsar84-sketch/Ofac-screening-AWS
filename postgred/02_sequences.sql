-- Sequences
-- Generated at: 2026-05-08T22:36:36.285888+00:00
-- Schema: public

CREATE SEQUENCE IF NOT EXISTS public."actimize_alert_callbacks_callback_id_seq"
    AS bigint
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 9223372036854775807
    START WITH 1
    CACHE 1
    NO CYCLE;

CREATE SEQUENCE IF NOT EXISTS public."api_access_logs_access_id_seq"
    AS bigint
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 9223372036854775807
    START WITH 1
    CACHE 1
    NO CYCLE;

CREATE SEQUENCE IF NOT EXISTS public."app_users_user_id_seq"
    AS bigint
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 9223372036854775807
    START WITH 1
    CACHE 1
    NO CYCLE;

CREATE SEQUENCE IF NOT EXISTS public."audit_events_event_id_seq"
    AS bigint
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 9223372036854775807
    START WITH 1
    CACHE 1
    NO CYCLE;

CREATE SEQUENCE IF NOT EXISTS public."external_api_errors_error_id_seq"
    AS bigint
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 9223372036854775807
    START WITH 1
    CACHE 1
    NO CYCLE;

CREATE SEQUENCE IF NOT EXISTS public."jobs_job_seq_id_seq"
    AS bigint
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 9223372036854775807
    START WITH 1
    CACHE 1
    NO CYCLE;

CREATE SEQUENCE IF NOT EXISTS public."schedule_notifications_notification_id_seq"
    AS bigint
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 9223372036854775807
    START WITH 1
    CACHE 1
    NO CYCLE;

ALTER SEQUENCE public."actimize_alert_callbacks_callback_id_seq" OWNED BY public."actimize_alert_callbacks"."callback_id";
ALTER SEQUENCE public."api_access_logs_access_id_seq" OWNED BY public."api_access_logs"."access_id";
ALTER SEQUENCE public."audit_events_event_id_seq" OWNED BY public."audit_events"."event_id";
ALTER SEQUENCE public."external_api_errors_error_id_seq" OWNED BY public."external_api_errors"."error_id";
ALTER SEQUENCE public."schedule_notifications_notification_id_seq" OWNED BY public."schedule_notifications"."notification_id";
