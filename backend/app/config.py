from __future__ import annotations

import os
import re
from dataclasses import dataclass


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _to_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_bytes(value: str | None, default: int) -> int:
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        pass

    m = re.match(r"^(?P<n>\\d+)(?P<unit>[kmg]b?|b)?$", raw)
    if not m:
        return default
    n = int(m.group("n"))
    unit = (m.group("unit") or "b").lower()
    if unit in {"b"}:
        return n
    if unit in {"k", "kb"}:
        return n * 1024
    if unit in {"m", "mb"}:
        return n * 1024 * 1024
    if unit in {"g", "gb"}:
        return n * 1024 * 1024 * 1024
    return default


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    app_db_path: str
    app_db_url: str
    db_pool_min_size: int
    db_pool_max_size: int
    db_pool_timeout_s: float
    db_connect_max_attempts: int
    db_connect_backoff_initial_ms: int
    db_connect_backoff_max_ms: int
    cors_allow_origins: str
    multipart_max_part_size_bytes: int

    aws_region: str
    aws_sqs_queue_name: str
    aws_endpoint_url: str
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_s3_upload_bucket: str
    aws_s3_upload_prefix: str
    aws_sns_notifications_enabled: bool
    aws_sns_schedule_topic_prefix: str
    aws_notification_delivery_mode: str
    aws_ses_sender_email: str

    actimize_base_url: str
    actimize_provider: str
    actimize_api_key: str
    actimize_bearer_token: str
    actimize_token_url: str
    actimize_client_id: str
    actimize_client_secret: str
    actimize_client_assertion_type: str
    actimize_client_assertion_algorithm: str
    actimize_client_assertion_audience: str
    actimize_client_assertion_kid: str
    actimize_client_assertion_private_key: str
    actimize_client_assertion_private_key_b64: str
    actimize_client_assertion_private_key_path: str
    actimize_scope: str
    actimize_source_system: str
    actimize_requester_name: str
    actimize_alert_review_url: str
    actimize_timeout_s: float
    actimize_mock: bool
    actimize_log_raw_api_io: bool
    actimize_raw_api_log_max_chars: int

    screening_tps: int
    screening_parallel_messages: int
    screening_poll_interval_ms: int
    screening_sync_timeout_s: int
    screening_result_limit: int
    screening_item_retry_max_attempts: int
    screening_item_retry_initial_delay_s: int
    screening_item_retry_max_delay_s: int
    daily_screening_timezone: str
    daily_screening_hour: int
    daily_screening_minute: int
    daily_screening_check_interval_s: int
    audit_access_log_enabled: bool
    audit_event_retention_days: int
    api_access_log_retention_days: int
    external_api_error_retention_days: int
    operational_cleanup_interval_s: int
    high_risk_external_api_error_window_minutes: int
    high_risk_external_api_error_threshold: int
    auth_enabled: bool
    auth_issuer: str
    auth_jwks_url: str
    auth_audience: str
    auth_algorithms: str


def load_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "OFAC Screening Enterprise API"),
        app_version=os.getenv("APP_VERSION", "1.0.0"),
        app_db_path=os.getenv("APP_DB_PATH", "/tmp/screening.db"),
        app_db_url=os.getenv("APP_DB_URL", "").strip(),
        db_pool_min_size=_to_int(os.getenv("DB_POOL_MIN_SIZE"), 1),
        db_pool_max_size=_to_int(os.getenv("DB_POOL_MAX_SIZE"), 8),
        db_pool_timeout_s=_to_float(os.getenv("DB_POOL_TIMEOUT_S"), 5.0),
        db_connect_max_attempts=_to_int(os.getenv("DB_CONNECT_MAX_ATTEMPTS"), 4),
        db_connect_backoff_initial_ms=_to_int(os.getenv("DB_CONNECT_BACKOFF_INITIAL_MS"), 100),
        db_connect_backoff_max_ms=_to_int(os.getenv("DB_CONNECT_BACKOFF_MAX_MS"), 1500),
        cors_allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*"),
        multipart_max_part_size_bytes=_to_bytes(os.getenv("MULTIPART_MAX_PART_SIZE", "25m"), 25 * 1024 * 1024),
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        aws_sqs_queue_name=os.getenv("AWS_SQS_QUEUE_NAME", "screening-requests"),
        aws_endpoint_url=os.getenv("AWS_ENDPOINT_URL", "").strip(),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "").strip(),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "").strip(),
        aws_s3_upload_bucket=os.getenv("AWS_S3_UPLOAD_BUCKET", "").strip(),
        aws_s3_upload_prefix=os.getenv("AWS_S3_UPLOAD_PREFIX", "screening-input").strip() or "screening-input",
        aws_sns_notifications_enabled=_to_bool(os.getenv("AWS_SNS_NOTIFICATIONS_ENABLED"), False),
        aws_sns_schedule_topic_prefix=os.getenv("AWS_SNS_SCHEDULE_TOPIC_PREFIX", "ofac-screening-schedule").strip()
        or "ofac-screening-schedule",
        aws_notification_delivery_mode=os.getenv("AWS_NOTIFICATION_DELIVERY_MODE", "SES").strip().upper() or "SES",
        aws_ses_sender_email=os.getenv("AWS_SES_SENDER_EMAIL", "").strip(),
        actimize_base_url=os.getenv("ACTIMIZE_BASE_URL", "").strip(),
        actimize_provider=os.getenv("ACTIMIZE_PROVIDER", "prudential").strip().lower() or "prudential",
        actimize_api_key=os.getenv("ACTIMIZE_API_KEY", "").strip(),
        actimize_bearer_token=os.getenv("ACTIMIZE_BEARER_TOKEN", "").strip(),
        actimize_token_url=os.getenv("ACTIMIZE_TOKEN_URL", "").strip(),
        actimize_client_id=os.getenv("ACTIMIZE_CLIENT_ID", "").strip(),
        actimize_client_secret=os.getenv("ACTIMIZE_CLIENT_SECRET", "").strip(),
        actimize_client_assertion_type=(
            os.getenv(
                "ACTIMIZE_CLIENT_ASSERTION_TYPE",
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            ).strip()
            or "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
        ),
        actimize_client_assertion_algorithm=os.getenv("ACTIMIZE_CLIENT_ASSERTION_ALGORITHM", "RS256").strip() or "RS256",
        actimize_client_assertion_audience=os.getenv("ACTIMIZE_CLIENT_ASSERTION_AUDIENCE", "").strip(),
        actimize_client_assertion_kid=os.getenv("ACTIMIZE_CLIENT_ASSERTION_KID", "").strip(),
        actimize_client_assertion_private_key=os.getenv("ACTIMIZE_CLIENT_ASSERTION_PRIVATE_KEY", "").strip(),
        actimize_client_assertion_private_key_b64=os.getenv("ACTIMIZE_CLIENT_ASSERTION_PRIVATE_KEY_B64", "").strip(),
        actimize_client_assertion_private_key_path=os.getenv("ACTIMIZE_CLIENT_ASSERTION_PRIVATE_KEY_PATH", "").strip(),
        actimize_scope=os.getenv("ACTIMIZE_SCOPE", "").strip(),
        actimize_source_system=os.getenv("ACTIMIZE_SOURCE_SYSTEM", "AMLP").strip() or "AMLP",
        actimize_requester_name=os.getenv("ACTIMIZE_REQUESTER_NAME", "SCREENING_SYSTEM").strip() or "SCREENING_SYSTEM",
        actimize_alert_review_url=os.getenv("ACTIMIZE_ALERT_REVIEW_URL", "").strip(),
        actimize_timeout_s=_to_float(os.getenv("ACTIMIZE_TIMEOUT_S"), 10.0),
        actimize_mock=_to_bool(os.getenv("ACTIMIZE_MOCK"), False),
        actimize_log_raw_api_io=_to_bool(
            os.getenv("ACTIMIZE_LOG_RAW_API_IO"),
            _to_bool(os.getenv("ACTIMIZE_LOG_RAW_SUCCESS_RESPONSE"), False),
        ),
        actimize_raw_api_log_max_chars=_to_int(
            os.getenv("ACTIMIZE_RAW_API_LOG_MAX_CHARS"),
            _to_int(os.getenv("ACTIMIZE_RAW_SUCCESS_LOG_MAX_CHARS"), 20000),
        ),
        screening_tps=_to_int(os.getenv("SCREENING_TPS"), 32),
        screening_parallel_messages=_to_int(os.getenv("SCREENING_PARALLEL_MESSAGES"), 1),
        screening_poll_interval_ms=_to_int(os.getenv("SCREENING_POLL_INTERVAL_MS"), 750),
        screening_sync_timeout_s=_to_int(os.getenv("SCREENING_SYNC_TIMEOUT_S"), 60),
        screening_result_limit=_to_int(os.getenv("SCREENING_RESULT_LIMIT"), 5),
        screening_item_retry_max_attempts=_to_int(os.getenv("SCREENING_ITEM_RETRY_MAX_ATTEMPTS"), 2),
        screening_item_retry_initial_delay_s=_to_int(os.getenv("SCREENING_ITEM_RETRY_INITIAL_DELAY_S"), 3),
        screening_item_retry_max_delay_s=_to_int(os.getenv("SCREENING_ITEM_RETRY_MAX_DELAY_S"), 60),
        daily_screening_timezone=os.getenv("DAILY_SCREENING_TIMEZONE", "America/New_York").strip() or "America/New_York",
        daily_screening_hour=_to_int(os.getenv("DAILY_SCREENING_HOUR"), 0),
        daily_screening_minute=_to_int(os.getenv("DAILY_SCREENING_MINUTE"), 5),
        daily_screening_check_interval_s=_to_int(os.getenv("DAILY_SCREENING_CHECK_INTERVAL_S"), 30),
        audit_access_log_enabled=_to_bool(os.getenv("AUDIT_ACCESS_LOG_ENABLED"), True),
        audit_event_retention_days=_to_int(os.getenv("AUDIT_EVENT_RETENTION_DAYS"), 3650),
        api_access_log_retention_days=_to_int(os.getenv("API_ACCESS_LOG_RETENTION_DAYS"), 365),
        external_api_error_retention_days=_to_int(os.getenv("EXTERNAL_API_ERROR_RETENTION_DAYS"), 365),
        operational_cleanup_interval_s=_to_int(os.getenv("OPERATIONAL_CLEANUP_INTERVAL_S"), 3600),
        high_risk_external_api_error_window_minutes=_to_int(os.getenv("HIGH_RISK_EXTERNAL_API_ERROR_WINDOW_MINUTES"), 15),
        high_risk_external_api_error_threshold=_to_int(os.getenv("HIGH_RISK_EXTERNAL_API_ERROR_THRESHOLD"), 10),
        auth_enabled=_to_bool(os.getenv("AUTH_ENABLED"), False),
        auth_issuer=os.getenv("AUTH_ISSUER", "").strip(),
        auth_jwks_url=os.getenv("AUTH_JWKS_URL", "").strip(),
        auth_audience=os.getenv("AUTH_AUDIENCE", "").strip(),
        auth_algorithms=os.getenv("AUTH_ALGORITHMS", "RS256").strip() or "RS256",
    )


settings = load_settings()
