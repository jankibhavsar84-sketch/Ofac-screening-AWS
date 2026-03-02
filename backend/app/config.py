from __future__ import annotations

import os
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


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    app_db_path: str
    app_db_url: str
    cors_allow_origins: str

    aws_region: str
    aws_sqs_queue_name: str
    aws_endpoint_url: str
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_s3_upload_bucket: str
    aws_s3_upload_prefix: str

    actimize_base_url: str
    actimize_api_key: str
    actimize_timeout_s: float
    actimize_mock: bool

    screening_tps: int
    screening_poll_interval_ms: int
    screening_sync_timeout_s: int
    screening_result_limit: int
    daily_screening_timezone: str
    daily_screening_hour: int
    daily_screening_minute: int
    daily_screening_check_interval_s: int
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
        cors_allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*"),
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        aws_sqs_queue_name=os.getenv("AWS_SQS_QUEUE_NAME", "screening-requests"),
        aws_endpoint_url=os.getenv("AWS_ENDPOINT_URL", "").strip(),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "").strip(),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "").strip(),
        aws_s3_upload_bucket=os.getenv("AWS_S3_UPLOAD_BUCKET", "").strip(),
        aws_s3_upload_prefix=os.getenv("AWS_S3_UPLOAD_PREFIX", "screening-input").strip() or "screening-input",
        actimize_base_url=os.getenv("ACTIMIZE_BASE_URL", "").strip(),
        actimize_api_key=os.getenv("ACTIMIZE_API_KEY", "").strip(),
        actimize_timeout_s=_to_float(os.getenv("ACTIMIZE_TIMEOUT_S"), 10.0),
        actimize_mock=_to_bool(os.getenv("ACTIMIZE_MOCK"), True),
        screening_tps=_to_int(os.getenv("SCREENING_TPS"), 32),
        screening_poll_interval_ms=_to_int(os.getenv("SCREENING_POLL_INTERVAL_MS"), 750),
        screening_sync_timeout_s=_to_int(os.getenv("SCREENING_SYNC_TIMEOUT_S"), 60),
        screening_result_limit=_to_int(os.getenv("SCREENING_RESULT_LIMIT"), 5),
        daily_screening_timezone=os.getenv("DAILY_SCREENING_TIMEZONE", "America/New_York").strip() or "America/New_York",
        daily_screening_hour=_to_int(os.getenv("DAILY_SCREENING_HOUR"), 0),
        daily_screening_minute=_to_int(os.getenv("DAILY_SCREENING_MINUTE"), 5),
        daily_screening_check_interval_s=_to_int(os.getenv("DAILY_SCREENING_CHECK_INTERVAL_S"), 30),
        auth_enabled=_to_bool(os.getenv("AUTH_ENABLED"), False),
        auth_issuer=os.getenv("AUTH_ISSUER", "").strip(),
        auth_jwks_url=os.getenv("AUTH_JWKS_URL", "").strip(),
        auth_audience=os.getenv("AUTH_AUDIENCE", "").strip(),
        auth_algorithms=os.getenv("AUTH_ALGORITHMS", "RS256").strip() or "RS256",
    )


settings = load_settings()
