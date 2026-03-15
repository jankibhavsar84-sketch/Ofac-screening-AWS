-- Sequences
-- Generated at: 2026-03-14T23:19:27.975907+00:00
-- Schema: dbacd

CREATE SEQUENCE IF NOT EXISTS dbacd."api_access_logs_access_id_seq"
    AS bigint
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 9223372036854775807
    START WITH 1
    CACHE 1
    NO CYCLE;

CREATE SEQUENCE IF NOT EXISTS dbacd."audit_events_event_id_seq"
    AS bigint
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 9223372036854775807
    START WITH 1
    CACHE 1
    NO CYCLE;

CREATE SEQUENCE IF NOT EXISTS dbacd."external_api_errors_error_id_seq"
    AS bigint
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 9223372036854775807
    START WITH 1
    CACHE 1
    NO CYCLE;

CREATE SEQUENCE IF NOT EXISTS dbacd."schedule_notifications_notification_id_seq"
    AS bigint
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 9223372036854775807
    START WITH 1
    CACHE 1
    NO CYCLE;

ALTER SEQUENCE dbacd."api_access_logs_access_id_seq" OWNED BY dbacd."api_access_logs"."access_id";
ALTER SEQUENCE dbacd."audit_events_event_id_seq" OWNED BY dbacd."audit_events"."event_id";
ALTER SEQUENCE dbacd."external_api_errors_error_id_seq" OWNED BY dbacd."external_api_errors"."error_id";
ALTER SEQUENCE dbacd."schedule_notifications_notification_id_seq" OWNED BY dbacd."schedule_notifications"."notification_id";
