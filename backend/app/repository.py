from __future__ import annotations

import atexit
import calendar
import hashlib
import json
import re
import sqlite3
from threading import Lock
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import settings
from .models import JobStatus, now_iso

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool, PoolTimeout
except Exception:  # pragma: no cover - optional dependency for local sqlite mode
    psycopg = None
    dict_row = None
    ConnectionPool = None
    PoolTimeout = None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
    return bool(value)


_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE)

DEFAULT_BUSINESS_UNITS: list[tuple[str, str]] = [
    ("US_PRU_OSGLI", "OSGLI"),
    ("US_PRU_VM", "Vendor Management"),
    ("US_PRU_HR", "Human Resources"),
    ("US_PRU_OPES", "Operation/Enabling Solutions"),
    ("US_PRU_PGIM", "PGIM"),
    ("US_PRU_PGIM_RE_TENANT", "PGIM Real Estate tenant"),
    ("US_PRU_PGIM_RE", "PGIM Real Estate"),
    ("US_PRU_PGIM_FI", "PGIM Fixed Income"),
    ("US_PRU_PGIM_PP_FI", "PGIMPublic and Private Fixed Income"),
    ("US_PRU_PGIM_MA", "PGIM Multi Asset Solutions"),
    ("US_PRU_PGIM_CIO", "PGIM CIO"),
    ("US_PRU_PGIM_JAPAN", "PGIM Japan"),
    ("US_PRU_PGIM_JK_ASC", "PGIM Jenkins Associates"),
    ("US_PRU_PGIM_NE_FI", "PGIM Netherlands"),
    ("US_PRU_PGIM_QUANT", "PGIM Quant Compliance"),
    ("US_PRU_PGIM_RE_APAC", "PGIM Real Estate APAC"),
    ("US_PRU_PGIM_LATAM", "PGIM LATAM"),
]
DEFAULT_FALLBACK_BUSINESS_UNIT_CODE = "US_PRU_OPES"
DEFAULT_ACTIMIZE_SCREENING_TYPE_MAPPINGS: tuple[tuple[str, str, int, str], ...] = (
    ("SAN", "SD_US_Customers_Sanctions", 1, "Customer Sanctions"),
    ("314a", "SD_US_Customers_314(a)", 2, "Customer FinCEN 314(a)"),
    ("AME", "SD_US_Customers_AME", 3, "Customer AME"),
    ("PEP", "SD_US_Customers_PEP_RCA_International", 4, "Political Exposed Person - Non-US"),
    ("MARJ", "SD_US_Marijuana_DJ_External", 5, "Marijuana Screening"),
    ("PEP-G", "SD_Customers_PEP_RCA_International", 6, "Global Political Exposed Person"),
    ("PAPC", "SD_US_Customers_Sanctions_PGIM_APAC", 7, "Customer Sanctions PGIM Real Estate (APAC) & PGIM Private Capital (Australia)"),
    ("PCIO", "SD_US_Customers_Sanctions_PGIM_CIO", 8, "Customer Sanctions PGIM CIO"),
    ("PFIC", "SD_US_Customers_Sanctions_PGIM_FI", 9, "Customer Sanctions PGIM Fixed Income"),
    ("PJAC", "SD_US_Customers_Sanctions_PGIM_JK_ASC", 10, "Customer Sanctions Jennison Associates"),
    ("PPLA", "SD_US_Customers_Sanctions_PGIM_LATAM", 11, "Customer Sanctions PGIM LATAM"),
    ("PSCG", "SD_US_Customers_Sanctions_PGIM_MA", 12, "Customer Sanctions PGIM Multi-Asset Solutions / PGIM Strategic Capital Group"),
    ("PUPV", "SD_US_Customers_Sanctions_PGIM_NE_FI", 13, "Customer Sanctions Public & Private Fixed Income, PGIM Netherlands B.V."),
    ("PGHK", "SD_Customers_Sanctions_PGIM_HK", 14, "Customer Sanctions PGIM HongKong"),
    ("PGJP", "SD_Customers_Sanctions_PGIM_JAPAN", 15, "Customer Sanctions PGIM Japan"),
    ("PPFI", "SD_US_Customers_Sanctions_PGIM_PP_FI", 16, "Customer Sanctions PGIM Public and Private Fixed Income"),
    ("PPQS", "SD_US_Customers_Sanctions_PGIM_QUANT", 17, "Customer Sanctions PGIM Quant"),
    ("PLUX", "SD_US_Customers_Sanctions_PGIM_RE", 18, "Customer Sanctions PGIM Real Estate"),
)

REQUIRED_TABLES: tuple[str, ...] = (
    "app_users",
    "jobs",
    "job_items",
    "job_metadata",
    "daily_schedules",
    "batch_file_uploads",
    "schedule_record_state",
    "schedule_subscriptions",
    "job_schedule_notifications",
    "audit_events",
    "api_access_logs",
    "external_api_errors",
    "actimize_alert_callbacks",
    "schedule_notifications",
    "business_units",
    "user_business_units",
    "actimize_screening_type_mappings",
)

REQUIRED_INDEXES: tuple[str, ...] = (
    "idx_app_users_old_id",
    "idx_app_users_email",
    "idx_schedule_subscriptions_unique",
    "idx_daily_schedules_next_run",
    "idx_daily_schedules_active_created",
    "idx_notifications_user",
    "idx_notifications_email",
    "idx_jobs_user_ref",
    "idx_daily_schedules_user_ref",
    "idx_batch_file_uploads_user_ref",
    "idx_schedule_subscriptions_user_ref",
    "idx_schedule_notifications_user_ref",
    "idx_user_business_units_user_ref",
    "idx_audit_events_user_ref_event",
    "idx_external_api_errors_user_ref_created_at",
    "idx_api_access_logs_user_ref_created_at",
    "idx_user_business_units_user",
    "idx_user_business_units_code",
    "idx_audit_events_event_id",
    "idx_audit_events_user_event",
    "idx_external_api_errors_created_at",
    "idx_external_api_errors_job_item",
    "idx_actimize_callbacks_unique_key_created_at",
    "idx_actimize_callbacks_alert_id",
    "idx_api_access_logs_created_at",
    "idx_api_access_logs_correlation",
    "idx_api_access_logs_user",
    "idx_api_access_logs_path",
)

REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "app_users": ("user_id", "is_active", "name", "email", "old_id", "created_at", "updated_at"),
    "jobs": ("source_schedule_id", "source_upload_id", "user_ref_id", "user_id", "user_name"),
    "job_metadata": (
        "mode",
        "screening_types_json",
        "mock_screening",
        "batch_name",
        "file_name",
        "daily_screening",
        "schedule_frequency",
        "daily_schedule_id",
        "query_count",
        "deferred_until",
        "business_unit_code",
    ),
    "daily_schedules": (
        "user_ref_id",
        "user_id",
        "user_name",
        "schedule_frequency",
        "source_upload_id",
        "source_file_name",
        "source_s3_uri",
        "business_unit_code",
    ),
    "batch_file_uploads": ("user_ref_id", "queries_s3_bucket", "queries_s3_key", "queries_s3_uri"),
    "schedule_subscriptions": ("user_ref_id",),
    "schedule_notifications": ("user_ref_id",),
    "audit_events": ("user_ref_id",),
    "external_api_errors": ("user_ref_id",),
    "api_access_logs": ("user_ref_id",),
    "user_business_units": ("user_ref_id",),
    "actimize_screening_type_mappings": (
        "Screening_Type",
        "Search_Definition_ID",
        "search_definition_name",
        "display_order",
        "is_active",
        "created_at",
        "updated_at",
    ),
}


def _is_technical_identifier(value: str | None) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return True
    if raw.isdigit():
        return True
    if _UUID_RE.match(raw):
        return True
    return False


_TRANSIENT_POSTGRES_CONNECT_MARKERS: tuple[str, ...] = (
    "connection timeout expired",
    "could not connect",
    "server closed the connection unexpectedly",
    "connection has been closed unexpectedly",
    "ssl syscall error",
    "ssl connection has been closed unexpectedly",
    "remaining connection slots are reserved",
    "too many clients already",
    "connection refused",
    "timeout expired",
    "eof detected",
)


class JobRepository:
    def __init__(self, db_path: str, db_url: str = "") -> None:
        self.db_path = db_path
        self.db_url = (db_url or "").strip()
        self.is_postgres = self.db_url.startswith("postgres://") or self.db_url.startswith("postgresql://")
        self._pool: Any | None = None
        self._connect_attempts = max(int(settings.db_connect_max_attempts), 1)
        self._connect_backoff_initial_s = max(int(settings.db_connect_backoff_initial_ms), 0) / 1000.0
        self._connect_backoff_max_s = max(int(settings.db_connect_backoff_max_ms), 0) / 1000.0

        if self.is_postgres and (psycopg is None or ConnectionPool is None):
            raise RuntimeError("PostgreSQL driver/pool not installed. Add psycopg[binary] and psycopg-pool to requirements.")

        if self.is_postgres:
            self._pool = self._build_postgres_pool()
            atexit.register(self.close)

        self.validate_schema()
        self._job_items_has_parsed_status = self._runtime_column_exists("job_items", "parsed_status")
        self._jobs_has_created_at_ts = self._runtime_column_exists("jobs", "created_at_ts")
        self._jobs_has_updated_at_ts = self._runtime_column_exists("jobs", "updated_at_ts")
        self._job_items_has_updated_at_ts = self._runtime_column_exists("job_items", "updated_at_ts")
        self._job_items_has_user_id = self._runtime_column_exists("job_items", "user_id")
        self._jobs_has_user_ref_id = self._runtime_column_exists("jobs", "user_ref_id")
        self._daily_schedules_has_user_ref_id = self._runtime_column_exists("daily_schedules", "user_ref_id")
        self._batch_file_uploads_has_user_ref_id = self._runtime_column_exists("batch_file_uploads", "user_ref_id")
        self._schedule_subscriptions_has_user_ref_id = self._runtime_column_exists("schedule_subscriptions", "user_ref_id")
        self._schedule_notifications_has_user_ref_id = self._runtime_column_exists("schedule_notifications", "user_ref_id")
        self._audit_events_has_user_ref_id = self._runtime_column_exists("audit_events", "user_ref_id")
        self._external_api_errors_has_user_ref_id = self._runtime_column_exists("external_api_errors", "user_ref_id")
        self._api_access_logs_has_user_ref_id = self._runtime_column_exists("api_access_logs", "user_ref_id")
        self._user_business_units_has_user_ref_id = self._runtime_column_exists("user_business_units", "user_ref_id")
        self._jobs_has_job_seq_id = self._runtime_column_exists("jobs", "job_seq_id")
        self._job_items_has_job_seq_id = self._runtime_column_exists("job_items", "job_seq_id")
        self._pg_mv_refresh_lock = Lock()
        self._last_pg_mv_refresh_at = 0.0

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()

    def _build_postgres_pool(self) -> Any:
        min_size = max(int(settings.db_pool_min_size), 1)
        max_size = max(int(settings.db_pool_max_size), min_size)
        timeout_s = max(float(settings.db_pool_timeout_s), 1.0)
        return ConnectionPool(
            conninfo=self.db_url,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout_s,
            kwargs={"row_factory": dict_row},
        )

    def _is_retryable_postgres_connect_error(self, exc: Exception) -> bool:
        if PoolTimeout is not None and isinstance(exc, PoolTimeout):
            return True
        if psycopg is not None and isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
            return True
        message = str(exc or "").strip().lower()
        return any(marker in message for marker in _TRANSIENT_POSTGRES_CONNECT_MARKERS)

    def _sleep_before_retry(self, attempt: int) -> None:
        if attempt >= self._connect_attempts:
            return
        delay = self._connect_backoff_initial_s * (2 ** max(attempt - 1, 0))
        delay = min(delay, self._connect_backoff_max_s or delay)
        if delay > 0:
            time.sleep(delay)

    @contextmanager
    def _sqlite_connection(self) -> Any:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:  # noqa: BLE001
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _postgres_connection(self) -> Any:
        if self._pool is None:
            raise RuntimeError("PostgreSQL connection pool is not initialized")

        last_exc: Exception | None = None
        conn_ctx: Any | None = None
        conn: Any | None = None
        for attempt in range(1, self._connect_attempts + 1):
            try:
                conn_ctx = cast(Any, self._pool.connection())
                conn = conn_ctx.__enter__()  # pylint: disable=no-member
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not self._is_retryable_postgres_connect_error(exc) or attempt >= self._connect_attempts:
                    raise
                self._sleep_before_retry(attempt)
        if conn_ctx is None or conn is None:
            raise last_exc or RuntimeError("Failed to acquire PostgreSQL connection")

        try:
            yield conn
        finally:
            conn_ctx.__exit__(None, None, None)  # pylint: disable=no-member

    def _connect(self) -> Any:
        if self.is_postgres:
            return self._postgres_connection()
        return self._sqlite_connection()

    def _sql(self, query: str) -> str:
        if not self.is_postgres:
            return query
        return query.replace("?", "%s")

    def _execute(self, conn: Any, query: str, params: tuple[Any, ...] = ()) -> Any:
        return conn.execute(self._sql(query), params)

    def _postgres_table_exists(self, conn: Any, table_name: str) -> bool:
        row = self._execute(
            conn,
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name = ?
            LIMIT 1
            """,
            (table_name,),
        ).fetchone()
        return bool(row)

    def _postgres_index_exists(self, conn: Any, index_name: str) -> bool:
        row = self._execute(
            conn,
            """
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND indexname = ?
            LIMIT 1
            """,
            (index_name,),
        ).fetchone()
        return bool(row)

    def _postgres_column_exists(self, conn: Any, table_name: str, column_name: str) -> bool:
        row = self._execute(
            conn,
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ?
              AND column_name = ?
            LIMIT 1
            """,
            (table_name, column_name),
        ).fetchone()
        return bool(row)

    def _sqlite_table_exists(self, conn: Any, table_name: str) -> bool:
        row = self._execute(
            conn,
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = ?
            LIMIT 1
            """,
            (table_name,),
        ).fetchone()
        return bool(row)

    def _sqlite_index_exists(self, conn: Any, index_name: str) -> bool:
        row = self._execute(
            conn,
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'index'
              AND name = ?
            LIMIT 1
            """,
            (index_name,),
        ).fetchone()
        return bool(row)

    def _sqlite_column_exists(self, conn: Any, table_name: str, column_name: str) -> bool:
        cols = self._execute(conn, f"PRAGMA table_info({table_name})").fetchall()
        return any(str(col["name"]) == column_name for col in cols)

    def _table_exists(self, conn: Any, table_name: str) -> bool:
        if self.is_postgres:
            return self._postgres_table_exists(conn, table_name)
        return self._sqlite_table_exists(conn, table_name)

    def _index_exists(self, conn: Any, index_name: str) -> bool:
        if self.is_postgres:
            return self._postgres_index_exists(conn, index_name)
        return self._sqlite_index_exists(conn, index_name)

    def _column_exists(self, conn: Any, table_name: str, column_name: str) -> bool:
        if self.is_postgres:
            return self._postgres_column_exists(conn, table_name, column_name)
        return self._sqlite_column_exists(conn, table_name, column_name)

    def _runtime_column_exists(self, table_name: str, column_name: str) -> bool:
        with self._connect() as conn:
            return self._column_exists(conn, table_name, column_name)

    def _job_items_jobs_join_condition(self, job_alias: str = "j", item_alias: str = "ji") -> str:
        if self.is_postgres and self._jobs_has_job_seq_id and self._job_items_has_job_seq_id:
            return f"{job_alias}.job_seq_id = {item_alias}.job_seq_id"
        return f"{job_alias}.job_id = {item_alias}.job_id"

    def _postgres_materialized_view_exists(self, conn: Any, view_name: str) -> bool:
        if not self.is_postgres:
            return False
        row = self._execute(
            conn,
            """
            SELECT 1
            FROM pg_matviews
            WHERE schemaname = current_schema()
              AND matviewname = ?
            LIMIT 1
            """,
            (view_name,),
        ).fetchone()
        return bool(row)

    def _maybe_refresh_postgres_result_materialized_views(self) -> bool:
        if not self.is_postgres:
            return False
        refresh_interval = max(int(settings.pg_result_mv_refresh_interval_s), 1)
        now_monotonic = time.monotonic()
        if now_monotonic - self._last_pg_mv_refresh_at < refresh_interval:
            return False
        with self._pg_mv_refresh_lock:
            now_monotonic = time.monotonic()
            if now_monotonic - self._last_pg_mv_refresh_at < refresh_interval:
                return False
            with self._connect() as conn:
                if not self._postgres_materialized_view_exists(conn, "mv_user_recent_results"):
                    self._last_pg_mv_refresh_at = now_monotonic
                    return False
                if not self._postgres_materialized_view_exists(conn, "mv_user_result_summary_counts"):
                    self._last_pg_mv_refresh_at = now_monotonic
                    return False
                has_daily_batch_runs_mv = self._postgres_materialized_view_exists(conn, "mv_daily_schedule_batch_runs")
                has_submission_jobs_mv = self._postgres_materialized_view_exists(conn, "mv_user_submission_jobs")
                try:
                    # Keep request paths responsive if refresh would wait on locks.
                    self._execute(conn, "SET LOCAL lock_timeout = '750ms'")
                    self._execute(conn, "SET LOCAL statement_timeout = '5000ms'")
                    self._execute(conn, "REFRESH MATERIALIZED VIEW mv_user_recent_results")
                    self._execute(conn, "REFRESH MATERIALIZED VIEW mv_user_result_summary_counts")
                    if has_daily_batch_runs_mv:
                        self._execute(conn, "REFRESH MATERIALIZED VIEW mv_daily_schedule_batch_runs")
                    if has_submission_jobs_mv:
                        self._execute(conn, "REFRESH MATERIALIZED VIEW mv_user_submission_jobs")
                    self._last_pg_mv_refresh_at = time.monotonic()
                    return True
                except Exception:  # noqa: BLE001
                    self._last_pg_mv_refresh_at = time.monotonic()
                    return False

    def _ensure_table(self, conn: Any, table_name: str, ddl: str) -> None:
        if self._table_exists(conn, table_name):
            return
        self._execute(conn, ddl)

    def _ensure_index(self, conn: Any, index_name: str, ddl: str) -> None:
        if self._index_exists(conn, index_name):
            return
        self._execute(conn, ddl)

    def validate_schema(self) -> None:
        if not self.is_postgres:
            db_file = Path(self.db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)

        missing_tables: list[str] = []
        missing_indexes: list[str] = []
        missing_columns: list[str] = []

        with self._connect() as conn:
            for table_name in REQUIRED_TABLES:
                if not self._table_exists(conn, table_name):
                    missing_tables.append(table_name)

            for index_name in REQUIRED_INDEXES:
                if not self._index_exists(conn, index_name):
                    missing_indexes.append(index_name)

            for table_name, column_names in REQUIRED_COLUMNS.items():
                for column_name in column_names:
                    if not self._column_exists(conn, table_name, column_name):
                        missing_columns.append(f"{table_name}.{column_name}")

        if missing_tables or missing_indexes or missing_columns:
            details: list[str] = []
            if missing_tables:
                details.append(f"tables={', '.join(missing_tables)}")
            if missing_columns:
                details.append(f"columns={', '.join(missing_columns)}")
            if missing_indexes:
                details.append(f"indexes={', '.join(missing_indexes)}")
            location = "APP_DB_URL" if self.is_postgres else self.db_path
            raise RuntimeError(
                "Database schema is not initialized. Run the explicit init step before starting the backend. "
                f"Target={location}. Missing {'; '.join(details)}"
            )

    def initialize_schema(self) -> None:
        raise RuntimeError(
            "Database schema management is not supported in backend/worker runtime. "
            "Run schema migrations separately before starting services."
        )

        with self._connect() as conn:
            self._ensure_table(
                conn,
                "jobs",
                """
                CREATE TABLE IF NOT EXISTS jobs (
                  job_id TEXT PRIMARY KEY,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  total_items INTEGER NOT NULL,
                  source_schedule_id TEXT,
                  source_upload_id TEXT,
                  user_id TEXT,
                  user_name TEXT
                );
                """,
            )
            self._ensure_table(
                conn,
                "job_items",
                """
                CREATE TABLE IF NOT EXISTS job_items (
                  job_id TEXT NOT NULL,
                  item_key TEXT NOT NULL,
                  request_json TEXT NOT NULL,
                  response_json TEXT,
                  status TEXT NOT NULL,
                  error_text TEXT,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY(job_id, item_key),
                  FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                );
                """,
            )
            self._ensure_table(
                conn,
                "job_metadata",
                """
                CREATE TABLE IF NOT EXISTS job_metadata (
                  job_id TEXT PRIMARY KEY,
                  mode TEXT NOT NULL DEFAULT 'BATCH',
                  screening_types_json TEXT NOT NULL DEFAULT '[]',
                  mock_screening BOOLEAN NOT NULL DEFAULT FALSE,
                  batch_name TEXT,
                  file_name TEXT,
                  daily_screening BOOLEAN NOT NULL DEFAULT FALSE,
                  schedule_frequency TEXT,
                  daily_schedule_id TEXT,
                  query_count INTEGER NOT NULL DEFAULT 0,
                  deferred_until TEXT
                );
                """,
            )
            self._ensure_table(
                conn,
                "daily_schedules",
                """
                CREATE TABLE IF NOT EXISTS daily_schedules (
                  schedule_id TEXT PRIMARY KEY,
                  batch_name TEXT NOT NULL,
                  user_id TEXT,
                  user_name TEXT,
                  queries_json TEXT NOT NULL,
                  screening_types_json TEXT NOT NULL,
                  mock_screening BOOLEAN NOT NULL DEFAULT FALSE,
                  schedule_frequency TEXT NOT NULL DEFAULT 'DAILY',
                  timezone TEXT NOT NULL,
                  run_hour INTEGER NOT NULL,
                  run_minute INTEGER NOT NULL,
                  created_at TEXT NOT NULL,
                  last_run_at TEXT,
                  next_run_at TEXT NOT NULL,
                  is_active BOOLEAN NOT NULL DEFAULT TRUE,
                  source_upload_id TEXT,
                  source_file_name TEXT,
                  source_s3_uri TEXT
                );
                """,
            )
            self._ensure_table(
                conn,
                "batch_file_uploads",
                """
                CREATE TABLE IF NOT EXISTS batch_file_uploads (
                  upload_id TEXT PRIMARY KEY,
                  schedule_id TEXT,
                  job_id TEXT,
                  user_id TEXT,
                  user_name TEXT,
                  file_name TEXT NOT NULL,
                  s3_bucket TEXT,
                  s3_key TEXT,
                  s3_uri TEXT,
                  queries_s3_bucket TEXT,
                  queries_s3_key TEXT,
                  queries_s3_uri TEXT,
                  file_hash TEXT,
                  record_count INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  is_active BOOLEAN NOT NULL DEFAULT TRUE
                );
                """,
            )
            self._ensure_table(
                conn,
                "schedule_record_state",
                """
                CREATE TABLE IF NOT EXISTS schedule_record_state (
                  schedule_id TEXT NOT NULL,
                  record_hash TEXT NOT NULL,
                  first_seen_at TEXT NOT NULL,
                  last_screened_at TEXT NOT NULL,
                  last_job_id TEXT,
                  PRIMARY KEY(schedule_id, record_hash)
                );
                """,
            )
            self._ensure_table(
                conn,
                "schedule_subscriptions",
                """
                CREATE TABLE IF NOT EXISTS schedule_subscriptions (
                  subscription_id TEXT PRIMARY KEY,
                  schedule_id TEXT NOT NULL,
                  user_id TEXT,
                  user_name TEXT,
                  email TEXT NOT NULL,
                  is_active BOOLEAN NOT NULL DEFAULT TRUE,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                """,
            )
            self._ensure_table(
                conn,
                "job_schedule_notifications",
                """
                CREATE TABLE IF NOT EXISTS job_schedule_notifications (
                  job_id TEXT PRIMARY KEY,
                  schedule_id TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                """,
            )

            if self.is_postgres:
                self._ensure_table(
                    conn,
                    "audit_events",
                    """
                    CREATE TABLE IF NOT EXISTS audit_events (
                      event_id BIGSERIAL PRIMARY KEY,
                      created_at TEXT NOT NULL,
                      user_id TEXT,
                      user_name TEXT,
                      action TEXT NOT NULL,
                      entity_type TEXT,
                      entity_id TEXT,
                      details_json TEXT
                    );
                    """,
                )
                self._ensure_table(
                    conn,
                    "api_access_logs",
                    """
                    CREATE TABLE IF NOT EXISTS api_access_logs (
                      access_id BIGSERIAL PRIMARY KEY,
                      created_at TEXT NOT NULL,
                      correlation_id TEXT,
                      request_method TEXT NOT NULL,
                      request_path TEXT NOT NULL,
                      query_string TEXT,
                      status_code INTEGER NOT NULL,
                      duration_ms INTEGER NOT NULL,
                      client_ip TEXT,
                      user_agent TEXT,
                      user_id TEXT,
                      user_name TEXT,
                      auth_state TEXT,
                      details_json TEXT
                    );
                    """,
                )
                self._ensure_table(
                    conn,
                    "external_api_errors",
                    """
                    CREATE TABLE IF NOT EXISTS external_api_errors (
                      error_id BIGSERIAL PRIMARY KEY,
                      created_at TEXT NOT NULL,
                      provider TEXT NOT NULL,
                      operation TEXT,
                      endpoint TEXT,
                      status_code INTEGER,
                      user_id TEXT,
                      user_name TEXT,
                      job_id TEXT,
                      item_key TEXT,
                      error_text TEXT NOT NULL,
                      details_json TEXT
                    );
                    """,
                )
                self._ensure_table(
                    conn,
                    "actimize_alert_callbacks",
                    """
                    CREATE TABLE IF NOT EXISTS actimize_alert_callbacks (
                      callback_id BIGSERIAL PRIMARY KEY,
                      created_at TEXT NOT NULL,
                      unique_key TEXT NOT NULL,
                      normalized_unique_key TEXT NOT NULL,
                      alert_id TEXT NOT NULL,
                      screening_cd TEXT,
                      status_cd TEXT NOT NULL,
                      update_timestamp TEXT,
                      source_system_cd TEXT,
                      tenant_cd TEXT,
                      matched_count INTEGER NOT NULL DEFAULT 0,
                      details_json TEXT
                    );
                    """,
                )
                self._ensure_table(
                    conn,
                    "schedule_notifications",
                    """
                    CREATE TABLE IF NOT EXISTS schedule_notifications (
                      notification_id BIGSERIAL PRIMARY KEY,
                      created_at TEXT NOT NULL,
                      user_id TEXT,
                      user_name TEXT,
                      email TEXT,
                      schedule_id TEXT,
                      job_id TEXT,
                      title TEXT NOT NULL,
                      message TEXT NOT NULL,
                      summary_json TEXT
                    );
                    """,
                )
            else:
                self._ensure_table(
                    conn,
                    "audit_events",
                    """
                    CREATE TABLE IF NOT EXISTS audit_events (
                      event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      created_at TEXT NOT NULL,
                      user_id TEXT,
                      user_name TEXT,
                      action TEXT NOT NULL,
                      entity_type TEXT,
                      entity_id TEXT,
                      details_json TEXT
                    );
                    """,
                )
                self._ensure_table(
                    conn,
                    "api_access_logs",
                    """
                    CREATE TABLE IF NOT EXISTS api_access_logs (
                      access_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      created_at TEXT NOT NULL,
                      correlation_id TEXT,
                      request_method TEXT NOT NULL,
                      request_path TEXT NOT NULL,
                      query_string TEXT,
                      status_code INTEGER NOT NULL,
                      duration_ms INTEGER NOT NULL,
                      client_ip TEXT,
                      user_agent TEXT,
                      user_id TEXT,
                      user_name TEXT,
                      auth_state TEXT,
                      details_json TEXT
                    );
                    """,
                )
                self._ensure_table(
                    conn,
                    "external_api_errors",
                    """
                    CREATE TABLE IF NOT EXISTS external_api_errors (
                      error_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      created_at TEXT NOT NULL,
                      provider TEXT NOT NULL,
                      operation TEXT,
                      endpoint TEXT,
                      status_code INTEGER,
                      user_id TEXT,
                      user_name TEXT,
                      job_id TEXT,
                      item_key TEXT,
                      error_text TEXT NOT NULL,
                      details_json TEXT
                    );
                    """,
                )
                self._ensure_table(
                    conn,
                    "actimize_alert_callbacks",
                    """
                    CREATE TABLE IF NOT EXISTS actimize_alert_callbacks (
                      callback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      created_at TEXT NOT NULL,
                      unique_key TEXT NOT NULL,
                      normalized_unique_key TEXT NOT NULL,
                      alert_id TEXT NOT NULL,
                      screening_cd TEXT,
                      status_cd TEXT NOT NULL,
                      update_timestamp TEXT,
                      source_system_cd TEXT,
                      tenant_cd TEXT,
                      matched_count INTEGER NOT NULL DEFAULT 0,
                      details_json TEXT
                    );
                    """,
                )
                self._ensure_table(
                    conn,
                    "schedule_notifications",
                    """
                    CREATE TABLE IF NOT EXISTS schedule_notifications (
                      notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      created_at TEXT NOT NULL,
                      user_id TEXT,
                      user_name TEXT,
                      email TEXT,
                      schedule_id TEXT,
                      job_id TEXT,
                      title TEXT NOT NULL,
                      message TEXT NOT NULL,
                      summary_json TEXT
                    );
                    """,
                )

            self._ensure_table(
                conn,
                "business_units",
                """
                CREATE TABLE IF NOT EXISTS business_units (
                  business_unit_code TEXT PRIMARY KEY,
                  business_unit_name TEXT NOT NULL,
                  is_active BOOLEAN NOT NULL DEFAULT TRUE,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                """,
            )
            self._ensure_table(
                conn,
                "user_business_units",
                """
                CREATE TABLE IF NOT EXISTS user_business_units (
                  user_id TEXT NOT NULL,
                  user_name TEXT,
                  business_unit_code TEXT NOT NULL,
                  is_active BOOLEAN NOT NULL DEFAULT TRUE,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY(user_id, business_unit_code)
                );
                """,
            )
            self._ensure_table(
                conn,
                "actimize_screening_type_mappings",
                """
                CREATE TABLE IF NOT EXISTS actimize_screening_type_mappings (
                  "Screening_Type" TEXT PRIMARY KEY,
                  "Search_Definition_ID" TEXT NOT NULL,
                  search_definition_name TEXT NOT NULL DEFAULT '',
                  display_order INTEGER NOT NULL DEFAULT 1000,
                  is_active BOOLEAN NOT NULL DEFAULT TRUE,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                """,
            )

            self._ensure_index(
                conn,
                "idx_schedule_subscriptions_unique",
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_schedule_subscriptions_unique
                ON schedule_subscriptions(schedule_id, email);
                """,
            )
            self._ensure_index(
                conn,
                "idx_daily_schedules_next_run",
                """
                CREATE INDEX IF NOT EXISTS idx_daily_schedules_next_run
                ON daily_schedules(next_run_at);
                """,
            )
            self._ensure_index(
                conn,
                "idx_daily_schedules_active_created",
                """
                CREATE INDEX IF NOT EXISTS idx_daily_schedules_active_created
                ON daily_schedules(is_active, created_at DESC, schedule_id);
                """,
            )
            self._ensure_index(
                conn,
                "idx_notifications_user",
                """
                CREATE INDEX IF NOT EXISTS idx_notifications_user
                ON schedule_notifications(user_id, created_at);
                """,
            )
            self._ensure_index(
                conn,
                "idx_notifications_email",
                """
                CREATE INDEX IF NOT EXISTS idx_notifications_email
                ON schedule_notifications(email, created_at);
                """,
            )
            self._ensure_index(
                conn,
                "idx_user_business_units_user",
                """
                CREATE INDEX IF NOT EXISTS idx_user_business_units_user
                ON user_business_units(user_id, is_active);
                """,
            )
            self._ensure_index(
                conn,
                "idx_user_business_units_code",
                """
                CREATE INDEX IF NOT EXISTS idx_user_business_units_code
                ON user_business_units(business_unit_code, is_active);
                """,
            )
            self._ensure_index(
                conn,
                "idx_audit_events_event_id",
                """
                CREATE INDEX IF NOT EXISTS idx_audit_events_event_id
                ON audit_events(event_id DESC);
                """,
            )
            self._ensure_index(
                conn,
                "idx_audit_events_user_event",
                """
                CREATE INDEX IF NOT EXISTS idx_audit_events_user_event
                ON audit_events(user_id, event_id DESC);
                """,
            )
            self._ensure_index(
                conn,
                "idx_external_api_errors_created_at",
                """
                CREATE INDEX IF NOT EXISTS idx_external_api_errors_created_at
                ON external_api_errors(created_at);
                """,
            )
            self._ensure_index(
                conn,
                "idx_external_api_errors_job_item",
                """
                CREATE INDEX IF NOT EXISTS idx_external_api_errors_job_item
                ON external_api_errors(job_id, item_key, created_at);
                """,
            )
            self._ensure_index(
                conn,
                "idx_actimize_callbacks_unique_key_created_at",
                """
                CREATE INDEX IF NOT EXISTS idx_actimize_callbacks_unique_key_created_at
                ON actimize_alert_callbacks(normalized_unique_key, created_at);
                """,
            )
            self._ensure_index(
                conn,
                "idx_actimize_callbacks_alert_id",
                """
                CREATE INDEX IF NOT EXISTS idx_actimize_callbacks_alert_id
                ON actimize_alert_callbacks(alert_id, created_at);
                """,
            )
            self._ensure_index(
                conn,
                "idx_api_access_logs_created_at",
                """
                CREATE INDEX IF NOT EXISTS idx_api_access_logs_created_at
                ON api_access_logs(created_at);
                """,
            )
            self._ensure_index(
                conn,
                "idx_api_access_logs_correlation",
                """
                CREATE INDEX IF NOT EXISTS idx_api_access_logs_correlation
                ON api_access_logs(correlation_id, created_at);
                """,
            )
            self._ensure_index(
                conn,
                "idx_api_access_logs_user",
                """
                CREATE INDEX IF NOT EXISTS idx_api_access_logs_user
                ON api_access_logs(user_id, created_at);
                """,
            )
            self._ensure_index(
                conn,
                "idx_api_access_logs_path",
                """
                CREATE INDEX IF NOT EXISTS idx_api_access_logs_path
                ON api_access_logs(request_path, created_at);
                """,
            )

            self._ensure_column(conn, "jobs", "source_schedule_id", "TEXT")
            self._ensure_column(conn, "jobs", "source_upload_id", "TEXT")
            self._ensure_column(conn, "jobs", "user_id", "TEXT")
            self._ensure_column(conn, "jobs", "user_name", "TEXT")

            self._ensure_column(conn, "job_metadata", "mode", "TEXT NOT NULL DEFAULT 'BATCH'")
            self._ensure_column(conn, "job_metadata", "screening_types_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "job_metadata", "mock_screening", "BOOLEAN NOT NULL DEFAULT FALSE")
            self._ensure_column(conn, "job_metadata", "batch_name", "TEXT")
            self._ensure_column(conn, "job_metadata", "file_name", "TEXT")
            self._ensure_column(conn, "job_metadata", "daily_screening", "BOOLEAN NOT NULL DEFAULT FALSE")
            self._ensure_column(conn, "job_metadata", "schedule_frequency", "TEXT")
            self._ensure_column(conn, "job_metadata", "daily_schedule_id", "TEXT")
            self._ensure_column(conn, "job_metadata", "query_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "job_metadata", "deferred_until", "TEXT")
            self._ensure_column(conn, "job_metadata", "business_unit_code", "TEXT")

            self._ensure_column(conn, "daily_schedules", "user_id", "TEXT")
            self._ensure_column(conn, "daily_schedules", "user_name", "TEXT")
            self._ensure_column(conn, "daily_schedules", "schedule_frequency", "TEXT NOT NULL DEFAULT 'DAILY'")
            self._ensure_column(conn, "daily_schedules", "source_upload_id", "TEXT")
            self._ensure_column(conn, "daily_schedules", "source_file_name", "TEXT")
            self._ensure_column(conn, "daily_schedules", "source_s3_uri", "TEXT")
            self._ensure_column(conn, "daily_schedules", "business_unit_code", "TEXT")

            self._ensure_column(conn, "batch_file_uploads", "queries_s3_bucket", "TEXT")
            self._ensure_column(conn, "batch_file_uploads", "queries_s3_key", "TEXT")
            self._ensure_column(conn, "batch_file_uploads", "queries_s3_uri", "TEXT")
            self._ensure_column(conn, "actimize_screening_type_mappings", "Screening_Type", "TEXT")
            self._ensure_column(conn, "actimize_screening_type_mappings", "Search_Definition_ID", "TEXT")
            self._ensure_column(conn, "actimize_screening_type_mappings", "search_definition_name", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "actimize_screening_type_mappings", "display_order", "INTEGER NOT NULL DEFAULT 1000")
            self._ensure_column(conn, "actimize_screening_type_mappings", "is_active", "BOOLEAN NOT NULL DEFAULT TRUE")
            self._ensure_column(conn, "actimize_screening_type_mappings", "created_at", "TEXT NOT NULL")
            self._ensure_column(conn, "actimize_screening_type_mappings", "updated_at", "TEXT NOT NULL")

            self._seed_default_business_units(conn)
            self._seed_default_actimize_screening_type_mappings(conn)

    def _ensure_column(self, conn: Any, table_name: str, column_name: str, column_def: str) -> None:
        if self._column_exists(conn, table_name, column_name):
            return

        if self.is_postgres:
            self._execute(conn, f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {column_def}")
            return

        self._execute(conn, f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")

    @staticmethod
    def _normalize_business_unit_code(value: str | None) -> str:
        return str(value or "").strip().upper()

    @staticmethod
    def _normalize_screening_type_key(value: str | None) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).lower()

    def _get_business_unit_row(self, business_unit_code: str, include_inactive: bool = False) -> dict[str, Any] | None:
        safe_code = self._normalize_business_unit_code(business_unit_code)
        if not safe_code:
            return None
        with self._connect() as conn:
            row = self._execute(
                conn,
                """
                SELECT business_unit_code, business_unit_name, is_active
                FROM business_units
                WHERE business_unit_code = ?
                  AND (? = TRUE OR is_active = TRUE)
                LIMIT 1
                """,
                (safe_code, include_inactive),
            ).fetchone()
        if not row:
            return None
        return {
            "business_unit_code": str(row["business_unit_code"] or "").strip(),
            "business_unit_name": str(row["business_unit_name"] or "").strip(),
            "is_active": _as_bool(row["is_active"]),
        }

    def _seed_default_business_units(self, conn: Any) -> None:
        ts = now_iso()
        for code, name in DEFAULT_BUSINESS_UNITS:
            safe_code = self._normalize_business_unit_code(code)
            safe_name = str(name or "").strip()
            if not safe_code or not safe_name:
                continue
            if self.is_postgres:
                self._execute(
                    conn,
                    """
                    INSERT INTO business_units(
                      business_unit_code, business_unit_name, is_active, created_at, updated_at
                    ) VALUES(?, ?, TRUE, ?, ?)
                    ON CONFLICT(business_unit_code) DO NOTHING
                    """,
                    (safe_code, safe_name, ts, ts),
                )
            else:
                self._execute(
                    conn,
                    """
                    INSERT OR IGNORE INTO business_units(
                      business_unit_code, business_unit_name, is_active, created_at, updated_at
                    ) VALUES(?, ?, TRUE, ?, ?)
                    """,
                    (safe_code, safe_name, ts, ts),
                )

    def _seed_default_actimize_screening_type_mappings(self, conn: Any) -> None:
        ts = now_iso()
        for (screening_type, search_definition_id, display_order, search_definition_name) in DEFAULT_ACTIMIZE_SCREENING_TYPE_MAPPINGS:
            safe_screening_type = str(screening_type or "").strip()
            safe_search_definition_id = str(search_definition_id or "").strip()
            safe_display_order = max(int(display_order), 0)
            safe_search_definition_name = str(search_definition_name or "").strip() or safe_search_definition_id
            if not safe_screening_type or not safe_search_definition_id:
                continue

            if self.is_postgres:
                self._execute(
                    conn,
                    """
                    INSERT INTO actimize_screening_type_mappings(
                      "Screening_Type",
                      "Search_Definition_ID",
                      search_definition_name,
                      display_order,
                      is_active,
                      created_at,
                      updated_at
                    ) VALUES(?, ?, ?, ?, TRUE, ?, ?)
                    ON CONFLICT("Screening_Type") DO NOTHING
                    """,
                    (
                        safe_screening_type,
                        safe_search_definition_id,
                        safe_search_definition_name,
                        safe_display_order,
                        ts,
                        ts,
                    ),
                )
            else:
                self._execute(
                    conn,
                    """
                    INSERT OR IGNORE INTO actimize_screening_type_mappings(
                      "Screening_Type",
                      "Search_Definition_ID",
                      search_definition_name,
                      display_order,
                      is_active,
                      created_at,
                      updated_at
                    ) VALUES(?, ?, ?, ?, TRUE, ?, ?)
                    """,
                    (
                        safe_screening_type,
                        safe_search_definition_id,
                        safe_search_definition_name,
                        safe_display_order,
                        ts,
                        ts,
                    ),
                )

            self._execute(
                conn,
                """
                UPDATE actimize_screening_type_mappings
                SET display_order = ?,
                    search_definition_name = CASE
                      WHEN search_definition_name IS NULL OR TRIM(search_definition_name) = ''
                      THEN ?
                      ELSE search_definition_name
                    END,
                    "Search_Definition_ID" = CASE
                      WHEN "Search_Definition_ID" IS NULL OR TRIM("Search_Definition_ID") = ''
                      THEN ?
                      ELSE "Search_Definition_ID"
                    END
                WHERE "Screening_Type" = ?
                  AND (display_order IS NULL OR display_order = 1000)
                """,
                (
                    safe_display_order,
                    safe_search_definition_name,
                    safe_search_definition_id,
                    safe_screening_type,
                ),
            )

            self._execute(
                conn,
                """
                UPDATE actimize_screening_type_mappings
                SET search_definition_name = ?
                WHERE "Screening_Type" = ?
                  AND (search_definition_name IS NULL OR TRIM(search_definition_name) = '')
                """,
                (safe_search_definition_name, safe_screening_type),
            )

    def resolve_actimize_screening_type_mapping(self, source_screening_type: str | None) -> dict[str, str]:
        safe_source = str(source_screening_type or "").strip()
        if not safe_source:
            return {"target_screening_type": "", "party_key_suffix": ""}

        row = self._resolve_active_actimize_screening_type_row(safe_source)
        if not row:
            fallback_search_definition_id = self._fallback_search_definition_id_for_legacy_screening_type(safe_source)
            if fallback_search_definition_id:
                row = self._resolve_active_actimize_screening_type_row(fallback_search_definition_id)

        if not row:
            return {"target_screening_type": "", "party_key_suffix": ""}

        mapped = str(row["search_definition_id"] or "").strip()
        suffix = str(row["screening_type"] or "").strip()
        return {"target_screening_type": mapped, "party_key_suffix": suffix}

    def resolve_actimize_screening_type(self, source_screening_type: str | None) -> str:
        mapping = self.resolve_actimize_screening_type_mapping(source_screening_type)
        mapped = str(mapping.get("target_screening_type") or "").strip()
        return mapped

    def resolve_actimize_party_key_suffix(self, source_screening_type: str | None) -> str:
        mapping = self.resolve_actimize_screening_type_mapping(source_screening_type)
        return str(mapping.get("party_key_suffix") or "").strip()

    def normalize_active_screening_types(self, requested_screening_types: list[str] | None) -> tuple[list[str], list[str]]:
        normalized: list[str] = []
        unresolved: list[str] = []
        seen: set[str] = set()

        for raw_value in requested_screening_types or []:
            safe_value = str(raw_value or "").strip()
            if not safe_value:
                continue

            mapping = self.resolve_actimize_screening_type_mapping(safe_value)
            normalized_type = str(mapping.get("party_key_suffix") or "").strip()
            if not normalized_type:
                unresolved.append(safe_value)
                continue

            dedupe_key = self._normalize_screening_type_key(normalized_type)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized.append(normalized_type)

        return normalized, unresolved

    def list_active_actimize_screening_type_mappings(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = self._execute(
                conn,
                """
                SELECT
                  "Screening_Type" AS screening_type,
                  "Search_Definition_ID" AS search_definition_id,
                  search_definition_name,
                  display_order
                FROM actimize_screening_type_mappings
                WHERE is_active = TRUE
                  AND TRIM(COALESCE("Screening_Type", '')) <> ''
                  AND TRIM(COALESCE("Search_Definition_ID", '')) <> ''
                ORDER BY display_order ASC, "Screening_Type" ASC
                """,
            ).fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            screening_type = str(row["screening_type"] or "").strip()
            search_definition_id = str(row["search_definition_id"] or "").strip()
            search_definition_name = str(row["search_definition_name"] or "").strip()
            try:
                display_order = int(row["display_order"] if row["display_order"] is not None else 1000)
            except (TypeError, ValueError):
                display_order = 1000
            if not screening_type:
                continue
            out.append(
                {
                    "screening_type": screening_type,
                    "search_definition_id": search_definition_id,
                    "search_definition_name": search_definition_name or search_definition_id or screening_type,
                    "display_order": display_order,
                }
            )
        return out

    @staticmethod
    def normalize_schedule_frequency(value: str | None) -> str:
        raw = (value or "").strip().upper()
        if raw in {"DAILY", "WEEKLY", "MONTHLY"}:
            return raw
        return "DAILY"

    @staticmethod
    def _add_months(local_dt: datetime, months: int) -> datetime:
        month_index = local_dt.month - 1 + months
        target_year = local_dt.year + month_index // 12
        target_month = month_index % 12 + 1
        max_day = calendar.monthrange(target_year, target_month)[1]
        target_day = min(local_dt.day, max_day)
        return local_dt.replace(year=target_year, month=target_month, day=target_day)

    @staticmethod
    def compute_next_run_at(
        now_utc: datetime,
        timezone_name: str,
        run_hour: int,
        run_minute: int,
        schedule_frequency: str = "DAILY",
    ) -> str:
        tz_name = timezone_name.strip() or "America/New_York"
        safe_hour = min(max(int(run_hour), 0), 23)
        safe_minute = min(max(int(run_minute), 0), 59)
        frequency = JobRepository.normalize_schedule_frequency(schedule_frequency)

        try:
            local_tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            local_tz = ZoneInfo("America/New_York")

        local_now = now_utc.astimezone(local_tz)
        local_target = local_now.replace(hour=safe_hour, minute=safe_minute, second=0, microsecond=0)

        if local_now >= local_target:
            if frequency == "WEEKLY":
                local_target = local_target + timedelta(days=7)
            elif frequency == "MONTHLY":
                local_target = JobRepository._add_months(local_target, 1)
            else:
                local_target = local_target + timedelta(days=1)

        return local_target.astimezone(timezone.utc).isoformat()

    def create_job(
        self,
        job_id: str,
        total_items: int,
        status: JobStatus | str = JobStatus.queued,
        source_schedule_id: str | None = None,
        source_upload_id: str | None = None,
        user_id: str | None = None,
        user_name: str | None = None,
    ) -> str:
        ts = now_iso()
        status_value = status.value if isinstance(status, JobStatus) else str(status)
        with self._connect() as conn:
            user_ref_id, resolved_user_id, resolved_user_name, _ = self._ensure_user_ref(
                conn,
                user_old_id=user_id,
                user_name=user_name,
            )
            columns = [
                "job_id",
                "status",
                "created_at",
                "updated_at",
                "total_items",
                "source_schedule_id",
                "source_upload_id",
            ]
            values: list[Any] = [
                job_id,
                status_value,
                ts,
                ts,
                max(int(total_items), 0),
                (source_schedule_id or "").strip() or None,
                (source_upload_id or "").strip() or None,
            ]
            if self._jobs_has_user_ref_id:
                columns.append("user_ref_id")
                values.append(user_ref_id)
            columns.extend(["user_id", "user_name"])
            values.extend([resolved_user_id, resolved_user_name])
            if self._jobs_has_created_at_ts:
                columns.append("created_at_ts")
                values.append(ts)
            if self._jobs_has_updated_at_ts:
                columns.append("updated_at_ts")
                values.append(ts)

            placeholders = ", ".join("?" for _ in columns)
            columns_sql = ", ".join(columns)
            self._execute(
                conn,
                f"INSERT INTO jobs({columns_sql}) VALUES({placeholders})",
                tuple(values),
            )
        return ts

    def get_job_metadata(self, job_id: str) -> dict[str, Any] | None:
        safe_job_id = (job_id or "").strip()
        if not safe_job_id:
            return None

        with self._connect() as conn:
            row = self._execute(
                conn,
                """
                SELECT
                  job_id, mode, screening_types_json, mock_screening, batch_name, file_name,
                  daily_screening, schedule_frequency, daily_schedule_id, query_count, deferred_until, business_unit_code
                FROM job_metadata
                WHERE job_id = ?
                """,
                (safe_job_id,),
            ).fetchone()

        if not row:
            return None

        parsed_types: list[str] = []
        try:
            decoded = json.loads(row["screening_types_json"]) if row["screening_types_json"] else []
            if isinstance(decoded, list):
                parsed_types = [str(v).strip() for v in decoded if str(v).strip()]
        except Exception:  # noqa: BLE001
            parsed_types = []

        return {
            "job_id": row["job_id"],
            "mode": str(row["mode"] or "BATCH").strip().upper() or "BATCH",
            "screening_types": parsed_types,
            "mock_screening": _as_bool(row["mock_screening"]),
            "batch_name": row["batch_name"],
            "file_name": row["file_name"],
            "daily_screening": _as_bool(row["daily_screening"]),
            "schedule_frequency": row["schedule_frequency"],
            "daily_schedule_id": row["daily_schedule_id"],
            "query_count": int(row["query_count"] or 0),
            "deferred_until": row["deferred_until"],
            "business_unit_code": row["business_unit_code"],
        }

    def upsert_job_metadata(
        self,
        job_id: str,
        mode: str | None = None,
        screening_types: list[str] | None = None,
        mock_screening: bool | None = None,
        batch_name: str | None = None,
        file_name: str | None = None,
        daily_screening: bool | None = None,
        schedule_frequency: str | None = None,
        daily_schedule_id: str | None = None,
        query_count: int | None = None,
        deferred_until: str | None = None,
        business_unit_code: str | None = None,
    ) -> None:
        safe_job_id = (job_id or "").strip()
        if not safe_job_id:
            return

        existing = self.get_job_metadata(safe_job_id) or {}

        mode_value = str(mode or existing.get("mode") or "BATCH").strip().upper() or "BATCH"
        types_value = screening_types if screening_types is not None else existing.get("screening_types", [])
        if not isinstance(types_value, list):
            types_value = []
        types_value = [str(v).strip() for v in types_value if str(v).strip()]

        mock_value = bool(mock_screening) if mock_screening is not None else bool(existing.get("mock_screening", False))
        batch_name_value = batch_name if batch_name is not None else existing.get("batch_name")
        file_name_value = file_name if file_name is not None else existing.get("file_name")
        daily_value = bool(daily_screening) if daily_screening is not None else bool(existing.get("daily_screening", False))
        freq_value = schedule_frequency if schedule_frequency is not None else existing.get("schedule_frequency")
        schedule_id_value = daily_schedule_id if daily_schedule_id is not None else existing.get("daily_schedule_id")
        query_count_value = int(query_count) if query_count is not None else int(existing.get("query_count") or 0)
        deferred_value = deferred_until if deferred_until is not None else existing.get("deferred_until")
        business_unit_value = (
            self._normalize_business_unit_code(business_unit_code)
            if business_unit_code is not None
            else self._normalize_business_unit_code(existing.get("business_unit_code"))
        )

        with self._connect() as conn:
            self._execute(
                conn,
                """
                INSERT INTO job_metadata(
                  job_id, mode, screening_types_json, mock_screening, batch_name, file_name,
                  daily_screening, schedule_frequency, daily_schedule_id, query_count, deferred_until, business_unit_code
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                  mode = excluded.mode,
                  screening_types_json = excluded.screening_types_json,
                  mock_screening = excluded.mock_screening,
                  batch_name = excluded.batch_name,
                  file_name = excluded.file_name,
                  daily_screening = excluded.daily_screening,
                  schedule_frequency = excluded.schedule_frequency,
                  daily_schedule_id = excluded.daily_schedule_id,
                  query_count = excluded.query_count,
                  deferred_until = excluded.deferred_until,
                  business_unit_code = excluded.business_unit_code
                """,
                (
                    safe_job_id,
                    mode_value,
                    json.dumps(types_value),
                    mock_value,
                    (batch_name_value or "").strip() or None,
                    (file_name_value or "").strip() or None,
                    daily_value,
                    (freq_value or "").strip() or None,
                    (schedule_id_value or "").strip() or None,
                    max(query_count_value, 0),
                    (deferred_value or "").strip() or None,
                    business_unit_value or None,
                ),
            )

    def list_jobs_for_history(
        self,
        user_id: str | None,
        user_name: str | None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        safe_limit = max(min(int(limit), 1000), 1)
        safe_user_id = self._normalize_user_old_id(user_id)
        safe_user_name = (user_name or "").strip()

        with self._connect() as conn:
            user_ref_id = self._lookup_user_ref_id(conn, safe_user_id) if safe_user_id else None
            has_submission_jobs_mv = (
                self.is_postgres and self._postgres_materialized_view_exists(conn, "mv_user_submission_jobs")
            )
            if has_submission_jobs_mv:
                if safe_user_id and user_ref_id is None:
                    rows = []
                elif safe_user_id:
                    rows = self._execute(
                        conn,
                        """
                        SELECT
                          job_id,
                          created_at,
                          total_items,
                          source_schedule_id,
                          source_upload_id,
                          user_id,
                          user_name,
                          mode,
                          screening_types_json,
                          mock_screening,
                          batch_name,
                          file_name,
                          daily_screening,
                          schedule_frequency,
                          daily_schedule_id,
                          business_unit_code,
                          upload_file_name,
                          upload_s3_uri
                        FROM mv_user_submission_jobs
                        WHERE user_ref_id = ?
                        ORDER BY created_at DESC, job_id DESC
                        LIMIT ?
                        """,
                        (user_ref_id, safe_limit),
                    ).fetchall()
                elif safe_user_name:
                    rows = self._execute(
                        conn,
                        """
                        SELECT
                          job_id,
                          created_at,
                          total_items,
                          source_schedule_id,
                          source_upload_id,
                          user_id,
                          user_name,
                          mode,
                          screening_types_json,
                          mock_screening,
                          batch_name,
                          file_name,
                          daily_screening,
                          schedule_frequency,
                          daily_schedule_id,
                          business_unit_code,
                          upload_file_name,
                          upload_s3_uri
                        FROM mv_user_submission_jobs
                        WHERE LOWER(COALESCE(NULLIF(user_name, ''), user_id, '')) = LOWER(?)
                        ORDER BY created_at DESC, job_id DESC
                        LIMIT ?
                        """,
                        (safe_user_name, safe_limit),
                    ).fetchall()
                else:
                    rows = self._execute(
                        conn,
                        """
                        SELECT
                          job_id,
                          created_at,
                          total_items,
                          source_schedule_id,
                          source_upload_id,
                          user_id,
                          user_name,
                          mode,
                          screening_types_json,
                          mock_screening,
                          batch_name,
                          file_name,
                          daily_screening,
                          schedule_frequency,
                          daily_schedule_id,
                          business_unit_code,
                          upload_file_name,
                          upload_s3_uri
                        FROM mv_user_submission_jobs
                        ORDER BY created_at DESC, job_id DESC
                        LIMIT ?
                        """,
                        (safe_limit,),
                    ).fetchall()
            else:
                if safe_user_id and self._jobs_has_user_ref_id and user_ref_id is None:
                    rows = []
                elif safe_user_id:
                    user_filter_sql = "j.user_ref_id = ?" if self._jobs_has_user_ref_id else "j.user_id = ?"
                    user_filter_param = user_ref_id if self._jobs_has_user_ref_id else safe_user_id
                    rows = self._execute(
                        conn,
                        f"""
                        SELECT
                          j.job_id, j.created_at, j.total_items,
                          j.source_schedule_id, j.source_upload_id,
                          COALESCE(NULLIF(j.user_id, ''), au.old_id) AS user_id,
                          COALESCE(NULLIF(j.user_name, ''), au.name, au.old_id) AS user_name,
                          jm.mode, jm.screening_types_json, jm.mock_screening, jm.batch_name, jm.file_name,
                          jm.daily_screening, jm.schedule_frequency, jm.daily_schedule_id, jm.business_unit_code,
                          bu.file_name AS upload_file_name, bu.s3_uri AS upload_s3_uri
                        FROM jobs j
                        LEFT JOIN app_users au ON au.user_id = j.user_ref_id
                        LEFT JOIN job_metadata jm ON jm.job_id = j.job_id
                        LEFT JOIN batch_file_uploads bu ON bu.upload_id = j.source_upload_id
                        WHERE {user_filter_sql}
                        ORDER BY j.created_at DESC
                        LIMIT ?
                        """,
                        (user_filter_param, safe_limit),
                    ).fetchall()
                elif safe_user_name:
                    rows = self._execute(
                        conn,
                        """
                        SELECT
                          j.job_id, j.created_at, j.total_items,
                          j.source_schedule_id, j.source_upload_id,
                          COALESCE(NULLIF(j.user_id, ''), au.old_id) AS user_id,
                          COALESCE(NULLIF(j.user_name, ''), au.name, au.old_id) AS user_name,
                          jm.mode, jm.screening_types_json, jm.mock_screening, jm.batch_name, jm.file_name,
                          jm.daily_screening, jm.schedule_frequency, jm.daily_schedule_id, jm.business_unit_code,
                          bu.file_name AS upload_file_name, bu.s3_uri AS upload_s3_uri
                        FROM jobs j
                        LEFT JOIN app_users au ON au.user_id = j.user_ref_id
                        LEFT JOIN job_metadata jm ON jm.job_id = j.job_id
                        LEFT JOIN batch_file_uploads bu ON bu.upload_id = j.source_upload_id
                        WHERE LOWER(COALESCE(NULLIF(j.user_name, ''), au.name, au.old_id, '')) = LOWER(?)
                        ORDER BY j.created_at DESC
                        LIMIT ?
                        """,
                        (safe_user_name, safe_limit),
                    ).fetchall()
                else:
                    rows = self._execute(
                        conn,
                        """
                        SELECT
                          j.job_id, j.created_at, j.total_items,
                          j.source_schedule_id, j.source_upload_id,
                          COALESCE(NULLIF(j.user_id, ''), au.old_id) AS user_id,
                          COALESCE(NULLIF(j.user_name, ''), au.name, au.old_id) AS user_name,
                          jm.mode, jm.screening_types_json, jm.mock_screening, jm.batch_name, jm.file_name,
                          jm.daily_screening, jm.schedule_frequency, jm.daily_schedule_id, jm.business_unit_code,
                          bu.file_name AS upload_file_name, bu.s3_uri AS upload_s3_uri
                        FROM jobs j
                        LEFT JOIN app_users au ON au.user_id = j.user_ref_id
                        LEFT JOIN job_metadata jm ON jm.job_id = j.job_id
                        LEFT JOIN batch_file_uploads bu ON bu.upload_id = j.source_upload_id
                        ORDER BY j.created_at DESC
                        LIMIT ?
                        """,
                        (safe_limit,),
                    ).fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "job_id": row["job_id"],
                    "created_at": JobRepository._to_iso_text(row["created_at"]) or "",
                    "total_items": int(row["total_items"] or 0),
                    "source_schedule_id": row["source_schedule_id"],
                    "source_upload_id": row["source_upload_id"],
                    "user_id": row["user_id"],
                    "user_name": row["user_name"],
                    "mode": row["mode"],
                    "screening_types_json": row["screening_types_json"],
                    "mock_screening": row["mock_screening"],
                    "batch_name": row["batch_name"],
                    "file_name": row["file_name"],
                    "daily_screening": row["daily_screening"],
                    "schedule_frequency": row["schedule_frequency"],
                    "daily_schedule_id": row["daily_schedule_id"],
                    "business_unit_code": row["business_unit_code"],
                    "upload_file_name": row["upload_file_name"],
                    "upload_s3_uri": row["upload_s3_uri"],
                }
            )
        return out

    def list_daily_schedule_batch_runs(self, limit: int = 200) -> list[dict[str, Any]]:
        safe_limit = max(min(int(limit), 1000), 1)
        if self.is_postgres:
            with self._connect() as conn:
                if self._postgres_materialized_view_exists(conn, "mv_daily_schedule_batch_runs"):
                    rows = self._execute(
                        conn,
                        """
                        SELECT
                          job_id,
                          schedule_id,
                          job_status,
                          created_at,
                          updated_at,
                          total_items,
                          source_upload_id,
                          user_id,
                          user_name,
                          batch_name,
                          schedule_frequency,
                          source_file_name,
                          completed_items,
                          failed_items,
                          pending_items,
                          processing_items
                        FROM mv_daily_schedule_batch_runs
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (safe_limit,),
                    ).fetchall()
                else:
                    rows = self._execute(
                        conn,
                        """
                        SELECT
                          j.job_id,
                          COALESCE(NULLIF(jm.daily_schedule_id, ''), NULLIF(j.source_schedule_id, '')) AS schedule_id,
                          UPPER(COALESCE(j.status, '')) AS job_status,
                          j.created_at,
                          j.updated_at,
                          j.total_items,
                          j.source_upload_id,
                          j.user_id,
                          j.user_name,
                          COALESCE(
                            NULLIF(jm.batch_name, ''),
                            NULLIF(ds.batch_name, ''),
                            NULLIF(jm.file_name, ''),
                            NULLIF(bu.file_name, ''),
                            'Scheduled Batch'
                          ) AS batch_name,
                          NULLIF(COALESCE(NULLIF(jm.schedule_frequency, ''), NULLIF(ds.schedule_frequency, '')), '') AS schedule_frequency,
                          NULLIF(COALESCE(NULLIF(bu.file_name, ''), NULLIF(ds.source_file_name, ''), NULLIF(jm.file_name, '')), '') AS source_file_name,
                          COALESCE(js.completed_items, 0) AS completed_items,
                          COALESCE(js.failed_items, 0) AS failed_items,
                          COALESCE(js.pending_items, 0) AS pending_items,
                          COALESCE(js.processing_items, 0) AS processing_items
                        FROM jobs j
                        LEFT JOIN job_metadata jm ON jm.job_id = j.job_id
                        LEFT JOIN daily_schedules ds
                          ON ds.schedule_id = COALESCE(NULLIF(jm.daily_schedule_id, ''), NULLIF(j.source_schedule_id, ''))
                        LEFT JOIN batch_file_uploads bu ON bu.upload_id = j.source_upload_id
                        LEFT JOIN (
                          SELECT
                            job_id,
                            SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed_items,
                            SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_items,
                            SUM(CASE WHEN status = 'QUEUED' THEN 1 ELSE 0 END) AS pending_items,
                            SUM(CASE WHEN status = 'PROCESSING' THEN 1 ELSE 0 END) AS processing_items
                          FROM job_items
                          GROUP BY job_id
                        ) js ON js.job_id = j.job_id
                        WHERE COALESCE(NULLIF(jm.daily_schedule_id, ''), NULLIF(j.source_schedule_id, '')) IS NOT NULL
                          AND UPPER(COALESCE(jm.mode, 'BATCH')) = 'BATCH'
                        ORDER BY j.created_at DESC
                        LIMIT ?
                        """,
                        (safe_limit,),
                    ).fetchall()
        else:
            with self._connect() as conn:
                rows = self._execute(
                    conn,
                    """
                    SELECT
                      j.job_id,
                      COALESCE(NULLIF(jm.daily_schedule_id, ''), NULLIF(j.source_schedule_id, '')) AS schedule_id,
                      UPPER(COALESCE(j.status, '')) AS job_status,
                      j.created_at,
                      j.updated_at,
                      j.total_items,
                      j.source_upload_id,
                      j.user_id,
                      j.user_name,
                      COALESCE(
                        NULLIF(jm.batch_name, ''),
                        NULLIF(ds.batch_name, ''),
                        NULLIF(jm.file_name, ''),
                        NULLIF(bu.file_name, ''),
                        'Scheduled Batch'
                      ) AS batch_name,
                      NULLIF(COALESCE(NULLIF(jm.schedule_frequency, ''), NULLIF(ds.schedule_frequency, '')), '') AS schedule_frequency,
                      NULLIF(COALESCE(NULLIF(bu.file_name, ''), NULLIF(ds.source_file_name, ''), NULLIF(jm.file_name, '')), '') AS source_file_name,
                      COALESCE(js.completed_items, 0) AS completed_items,
                      COALESCE(js.failed_items, 0) AS failed_items,
                      COALESCE(js.pending_items, 0) AS pending_items,
                      COALESCE(js.processing_items, 0) AS processing_items
                    FROM jobs j
                    LEFT JOIN job_metadata jm ON jm.job_id = j.job_id
                    LEFT JOIN daily_schedules ds
                      ON ds.schedule_id = COALESCE(NULLIF(jm.daily_schedule_id, ''), NULLIF(j.source_schedule_id, ''))
                    LEFT JOIN batch_file_uploads bu ON bu.upload_id = j.source_upload_id
                    LEFT JOIN (
                      SELECT
                        job_id,
                        SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed_items,
                        SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_items,
                        SUM(CASE WHEN status = 'QUEUED' THEN 1 ELSE 0 END) AS pending_items,
                        SUM(CASE WHEN status = 'PROCESSING' THEN 1 ELSE 0 END) AS processing_items
                      FROM job_items
                      GROUP BY job_id
                    ) js ON js.job_id = j.job_id
                    WHERE COALESCE(NULLIF(jm.daily_schedule_id, ''), NULLIF(j.source_schedule_id, '')) IS NOT NULL
                      AND UPPER(COALESCE(jm.mode, 'BATCH')) = 'BATCH'
                    ORDER BY j.created_at DESC
                    LIMIT ?
                    """,
                    (safe_limit,),
                ).fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "job_id": str(row["job_id"] or "").strip(),
                    "job_status": str(row["job_status"] or "").strip().upper(),
                    "created_at": JobRepository._to_iso_text(row["created_at"]) or "",
                    "updated_at": JobRepository._to_iso_text(row["updated_at"]) or "",
                    "total_items": int(row["total_items"] or 0),
                    "schedule_id": str(row["schedule_id"] or "").strip(),
                    "source_upload_id": row["source_upload_id"],
                    "user_id": row["user_id"],
                    "user_name": row["user_name"],
                    "batch_name": str(row["batch_name"] or "").strip() or "Scheduled Batch",
                    "schedule_frequency": str(row["schedule_frequency"] or "").strip() or None,
                    "source_file_name": str(row["source_file_name"] or "").strip() or None,
                    "completed_items": int(row["completed_items"] or 0),
                    "failed_items": int(row["failed_items"] or 0),
                    "pending_items": int(row["pending_items"] or 0),
                    "processing_items": int(row["processing_items"] or 0),
                }
            )
        return out

    def list_job_items_for_jobs(self, job_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        normalized_job_ids = [str(job_id).strip() for job_id in job_ids if str(job_id).strip()]
        if not normalized_job_ids:
            return {}

        placeholders = ", ".join("?" for _ in normalized_job_ids)
        with self._connect() as conn:
            rows = self._execute(
                conn,
                f"""
                SELECT job_id, item_key, request_json, response_json, status, error_text
                FROM job_items
                WHERE job_id IN ({placeholders})
                ORDER BY job_id ASC, item_key ASC
                """,
                tuple(normalized_job_ids),
            ).fetchall()

        items_by_job: dict[str, list[dict[str, Any]]] = {job_id: [] for job_id in normalized_job_ids}
        for row in rows:
            job_id = str(row["job_id"] or "").strip()
            if not job_id:
                continue
            try:
                request_payload = json.loads(row["request_json"]) if row["request_json"] else None
            except Exception:
                request_payload = None
            try:
                response_payload = json.loads(row["response_json"]) if row["response_json"] else None
            except Exception:
                response_payload = None

            items_by_job.setdefault(job_id, []).append(
                {
                    "item_key": row["item_key"],
                    "request": request_payload,
                    "response": response_payload,
                    "status": row["status"],
                    "error_text": row["error_text"],
                }
            )

        return items_by_job

    def list_recent_result_items(
        self,
        user_id: str | None,
        user_name: str | None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit or 1000), 5000))
        safe_user_id = self._normalize_user_old_id(user_id)
        safe_user_name = str(user_name or "").strip()
        join_condition = self._job_items_jobs_join_condition()

        rows: list[Any] = []
        if self.is_postgres:
            with self._connect() as conn:
                if not self._postgres_materialized_view_exists(conn, "mv_user_recent_results"):
                    raise RuntimeError("Required materialized view mv_user_recent_results is missing.")

                if safe_user_id:
                    user_ref_id = self._lookup_user_ref_id(conn, safe_user_id)
                    if user_ref_id is None:
                        return []
                    recent_cte = """
                    WITH recent AS (
                      SELECT job_id, item_key, sort_ts
                      FROM mv_user_recent_results
                      WHERE user_ref_id = ?
                      ORDER BY sort_ts DESC, job_id DESC, item_key ASC
                      LIMIT ?
                    )
                    """
                    params: tuple[Any, ...] = (user_ref_id, safe_limit)
                elif safe_user_name:
                    recent_cte = """
                    WITH recent AS (
                      SELECT r.job_id, r.item_key, r.sort_ts
                      FROM mv_user_recent_results r
                      LEFT JOIN app_users au ON au.user_id = r.user_ref_id
                      WHERE LOWER(COALESCE(NULLIF(r.user_name, ''), au.name, r.user_id, '')) = LOWER(?)
                      ORDER BY r.sort_ts DESC, r.job_id DESC, r.item_key ASC
                      LIMIT ?
                    )
                    """
                    params = (safe_user_name, safe_limit)
                else:
                    recent_cte = """
                    WITH recent AS (
                      SELECT job_id, item_key, sort_ts
                      FROM mv_user_recent_results
                      ORDER BY sort_ts DESC, job_id DESC, item_key ASC
                      LIMIT ?
                    )
                    """
                    params = (safe_limit,)

                rows = self._execute(
                    conn,
                    f"""
                    {recent_cte}
                    SELECT
                      j.job_id, j.created_at, j.updated_at AS job_updated_at, j.total_items,
                      j.source_schedule_id, j.source_upload_id,
                      COALESCE(NULLIF(j.user_id, ''), au.old_id) AS user_id,
                      COALESCE(NULLIF(j.user_name, ''), au.name, au.old_id) AS user_name,
                      jm.mode, jm.screening_types_json, jm.batch_name, jm.file_name,
                      jm.daily_schedule_id, jm.business_unit_code,
                      bu.file_name AS upload_file_name,
                      ji.item_key, ji.request_json, ji.response_json, ji.status AS item_status, ji.error_text AS item_error_text, ji.updated_at AS item_updated_at
                    FROM recent r
                    INNER JOIN job_items ji ON ji.job_id = r.job_id AND ji.item_key = r.item_key
                    INNER JOIN jobs j ON j.job_id = r.job_id
                    LEFT JOIN app_users au ON au.user_id = j.user_ref_id
                    LEFT JOIN job_metadata jm ON jm.job_id = j.job_id
                    LEFT JOIN batch_file_uploads bu ON bu.upload_id = j.source_upload_id
                    ORDER BY r.sort_ts DESC, r.job_id DESC, r.item_key ASC
                    """,
                    params,
                ).fetchall()
        else:
            filters: list[str] = []
            params: list[Any] = []
            if safe_user_id:
                with self._connect() as conn:
                    user_ref_id = self._lookup_user_ref_id(conn, safe_user_id) if self._jobs_has_user_ref_id else None
                    if self._jobs_has_user_ref_id and user_ref_id is None:
                        return []
                if self._jobs_has_user_ref_id:
                    filters.append("j.user_ref_id = ?")
                    params.append(user_ref_id)
                else:
                    filters.append("j.user_id = ?")
                    params.append(safe_user_id)
            elif safe_user_name:
                filters.append("LOWER(COALESCE(NULLIF(j.user_name, ''), au.name, au.old_id, '')) = LOWER(?)")
                params.append(safe_user_name)

            where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
            with self._connect() as conn:
                rows = self._execute(
                    conn,
                    f"""
                    SELECT
                      j.job_id, j.created_at, j.updated_at AS job_updated_at, j.total_items,
                      j.source_schedule_id, j.source_upload_id,
                      COALESCE(NULLIF(j.user_id, ''), au.old_id) AS user_id,
                      COALESCE(NULLIF(j.user_name, ''), au.name, au.old_id) AS user_name,
                      jm.mode, jm.screening_types_json, jm.batch_name, jm.file_name,
                      jm.daily_schedule_id, jm.business_unit_code,
                      bu.file_name AS upload_file_name,
                      ji.item_key, ji.request_json, ji.response_json, ji.status AS item_status, ji.error_text AS item_error_text, ji.updated_at AS item_updated_at
                    FROM job_items ji
                    INNER JOIN jobs j ON {join_condition}
                    LEFT JOIN app_users au ON au.user_id = j.user_ref_id
                    LEFT JOIN job_metadata jm ON jm.job_id = j.job_id
                    LEFT JOIN batch_file_uploads bu ON bu.upload_id = j.source_upload_id
                    {where_sql}
                    ORDER BY COALESCE(ji.updated_at, j.updated_at, j.created_at) DESC, j.created_at DESC, ji.item_key ASC
                    LIMIT ?
                    """,
                    tuple([*params, safe_limit]),
                ).fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "job_id": row["job_id"],
                    "created_at": JobRepository._to_iso_text(row["created_at"]) or "",
                    "job_updated_at": JobRepository._to_iso_text(row["job_updated_at"]),
                    "total_items": int(row["total_items"] or 0),
                    "source_schedule_id": row["source_schedule_id"],
                    "source_upload_id": row["source_upload_id"],
                    "user_id": row["user_id"],
                    "user_name": row["user_name"],
                    "mode": row["mode"],
                    "screening_types_json": row["screening_types_json"],
                    "batch_name": row["batch_name"],
                    "file_name": row["file_name"],
                    "daily_schedule_id": row["daily_schedule_id"],
                    "business_unit_code": row["business_unit_code"],
                    "upload_file_name": row["upload_file_name"],
                    "item_key": row["item_key"],
                    "item_status": row["item_status"],
                    "item_error_text": row["item_error_text"],
                    "item_updated_at": JobRepository._to_iso_text(row["item_updated_at"]),
                    "request_json": row["request_json"],
                    "response_json": row["response_json"],
                }
            )
        return out

    def get_user_result_summary_counts(self, user_id: str | None, user_name: str | None) -> dict[str, int]:
        safe_user_id = self._normalize_user_old_id(user_id)
        safe_user_name = str(user_name or "").strip()
        join_condition = self._job_items_jobs_join_condition()

        if self.is_postgres:
            with self._connect() as conn:
                if not self._postgres_materialized_view_exists(conn, "mv_user_recent_results"):
                    raise RuntimeError("Required materialized view mv_user_recent_results is missing.")
                if not self._postgres_materialized_view_exists(conn, "mv_user_result_summary_counts"):
                    raise RuntimeError("Required materialized view mv_user_result_summary_counts is missing.")

                if safe_user_id:
                    user_ref_id = self._lookup_user_ref_id(conn, safe_user_id)
                    if user_ref_id is None:
                        return {"total": 0, "clear": 0, "potential": 0, "pending": 0, "failed": 0, "match": 0}
                    row = self._execute(
                        conn,
                        """
                        SELECT total, clear, potential, pending, failed
                        FROM mv_user_result_summary_counts
                        WHERE user_ref_id = ?
                        LIMIT 1
                        """,
                        (user_ref_id,),
                    ).fetchone()
                    if not row:
                        return {"total": 0, "clear": 0, "potential": 0, "pending": 0, "failed": 0, "match": 0}
                    return {
                        "total": int(row["total"] or 0),
                        "clear": int(row["clear"] or 0),
                        "potential": int(row["potential"] or 0),
                        "pending": int(row["pending"] or 0),
                        "failed": int(row["failed"] or 0),
                        "match": 0,
                    }

                if safe_user_name:
                    row = self._execute(
                        conn,
                        """
                        SELECT
                          COUNT(*)::BIGINT AS total,
                          SUM(CASE WHEN r.parsed_status = 'CLEAR' THEN 1 ELSE 0 END)::BIGINT AS clear,
                          SUM(CASE WHEN r.parsed_status = 'POTENTIAL' THEN 1 ELSE 0 END)::BIGINT AS potential,
                          SUM(CASE WHEN r.parsed_status = 'PENDING' THEN 1 ELSE 0 END)::BIGINT AS pending,
                          SUM(CASE WHEN r.parsed_status = 'FAILED' THEN 1 ELSE 0 END)::BIGINT AS failed
                        FROM mv_user_recent_results r
                        LEFT JOIN app_users au ON au.user_id = r.user_ref_id
                        WHERE LOWER(COALESCE(NULLIF(r.user_name, ''), au.name, r.user_id, '')) = LOWER(?)
                        """,
                        (safe_user_name,),
                    ).fetchone()
                    return {
                        "total": int((row or {}).get("total") or 0),
                        "clear": int((row or {}).get("clear") or 0),
                        "potential": int((row or {}).get("potential") or 0),
                        "pending": int((row or {}).get("pending") or 0),
                        "failed": int((row or {}).get("failed") or 0),
                        "match": 0,
                    }

                row = self._execute(
                    conn,
                    """
                    SELECT
                      COUNT(*)::BIGINT AS total,
                      SUM(CASE WHEN parsed_status = 'CLEAR' THEN 1 ELSE 0 END)::BIGINT AS clear,
                      SUM(CASE WHEN parsed_status = 'POTENTIAL' THEN 1 ELSE 0 END)::BIGINT AS potential,
                      SUM(CASE WHEN parsed_status = 'PENDING' THEN 1 ELSE 0 END)::BIGINT AS pending,
                      SUM(CASE WHEN parsed_status = 'FAILED' THEN 1 ELSE 0 END)::BIGINT AS failed
                    FROM mv_user_recent_results
                    """,
                ).fetchone()
                return {
                    "total": int((row or {}).get("total") or 0),
                    "clear": int((row or {}).get("clear") or 0),
                    "potential": int((row or {}).get("potential") or 0),
                    "pending": int((row or {}).get("pending") or 0),
                    "failed": int((row or {}).get("failed") or 0),
                    "match": 0,
                }

        filters: list[str] = []
        params: list[Any] = []
        if safe_user_id:
            with self._connect() as conn:
                user_ref_id = self._lookup_user_ref_id(conn, safe_user_id) if self._jobs_has_user_ref_id else None
                if self._jobs_has_user_ref_id and user_ref_id is None:
                    return {"total": 0, "clear": 0, "potential": 0, "pending": 0, "failed": 0, "match": 0}
            if self._jobs_has_user_ref_id:
                filters.append("j.user_ref_id = ?")
                params.append(user_ref_id)
            else:
                filters.append("j.user_id = ?")
                params.append(safe_user_id)
        elif safe_user_name:
            filters.append("LOWER(COALESCE(NULLIF(j.user_name, ''), au.name, au.old_id, '')) = LOWER(?)")
            params.append(safe_user_name)

        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self._connect() as conn:
            rows = self._execute(
                conn,
                f"""
                SELECT ji.status, ji.response_json{", ji.parsed_status" if self._job_items_has_parsed_status else ""}
                FROM job_items ji
                INNER JOIN jobs j ON {join_condition}
                LEFT JOIN app_users au ON au.user_id = j.user_ref_id
                {where_sql}
                """,
                tuple(params),
            ).fetchall()

        total = 0
        clear = 0
        potential = 0
        pending = 0
        failed = 0
        for item in rows:
            total += 1
            if self._job_items_has_parsed_status:
                parsed_status = str(item["parsed_status"] or "").strip().upper() or "FAILED"
            else:
                item_status = str(item["status"] or "").strip().upper()
                if item_status in {JobStatus.queued.value, JobStatus.processing.value}:
                    parsed_status = "PENDING"
                elif item_status == JobStatus.failed.value:
                    parsed_status = "FAILED"
                else:
                    try:
                        response_payload = json.loads(item["response_json"]) if item["response_json"] else {}
                    except Exception:
                        response_payload = {}
                    parsed_status = self._derive_parsed_status_from_response_payload(response_payload)

            if parsed_status == "CLEAR":
                clear += 1
            elif parsed_status == "POTENTIAL":
                potential += 1
            elif parsed_status == "PENDING":
                pending += 1
            else:
                failed += 1

        return {
            "total": total,
            "clear": clear,
            "potential": potential,
            "pending": pending,
            "failed": failed,
            "match": 0,
        }

    @staticmethod
    def _derive_parsed_status_from_response_payload(response_payload: dict[str, Any] | None) -> str:
        if not isinstance(response_payload, dict):
            return "FAILED"
        response_status = response_payload.get("status")
        response_error = str(response_payload.get("error_text") or response_payload.get("error") or "").strip()
        if (isinstance(response_status, int) and response_status != 200) or response_error:
            return "FAILED"
        engine_message = str(response_payload.get("engine_message") or "").strip().upper()
        if engine_message == "PM":
            return "POTENTIAL"
        if engine_message == "NM":
            return "CLEAR"
        results = response_payload.get("results", [])
        if isinstance(results, list) and any(isinstance(result, dict) and bool(result.get("match")) for result in results):
            return "POTENTIAL"
        return "CLEAR"

    def add_job_item(self, job_id: str, item_key: str, request_payload: dict[str, Any]) -> None:
        ts = now_iso()
        parsed_status = "PENDING"
        with self._connect() as conn:
            if self._job_items_has_parsed_status:
                extra_col = ", updated_at_ts" if self._job_items_has_updated_at_ts else ""
                extra_placeholder = ", ?" if self._job_items_has_updated_at_ts else ""
                self._execute(
                    conn,
                    f"""
                    INSERT INTO job_items(job_id, item_key, request_json, response_json, status, parsed_status, error_text, updated_at{extra_col})
                    VALUES(?, ?, ?, NULL, ?, ?, NULL, ?{extra_placeholder})
                    """,
                    (
                        job_id,
                        item_key,
                        json.dumps(request_payload),
                        JobStatus.queued.value,
                        parsed_status,
                        ts,
                        *([ts] if self._job_items_has_updated_at_ts else []),
                    ),
                )
            else:
                extra_col = ", updated_at_ts" if self._job_items_has_updated_at_ts else ""
                extra_placeholder = ", ?" if self._job_items_has_updated_at_ts else ""
                self._execute(
                    conn,
                    f"""
                    INSERT INTO job_items(job_id, item_key, request_json, response_json, status, error_text, updated_at{extra_col})
                    VALUES(?, ?, ?, NULL, ?, NULL, ?{extra_placeholder})
                    """,
                    (
                        job_id,
                        item_key,
                        json.dumps(request_payload),
                        JobStatus.queued.value,
                        ts,
                        *([ts] if self._job_items_has_updated_at_ts else []),
                    ),
                )
        self._maybe_refresh_postgres_result_materialized_views()

    def mark_item_processing(self, job_id: str, item_key: str) -> None:
        ts = now_iso()
        with self._connect() as conn:
            if self._job_items_has_parsed_status:
                self._execute(
                    conn,
                    f"UPDATE job_items SET status = ?, parsed_status = ?, updated_at = ?{', updated_at_ts = ?' if self._job_items_has_updated_at_ts else ''} WHERE job_id = ? AND item_key = ?",
                    (
                        JobStatus.processing.value,
                        "PENDING",
                        ts,
                        *([ts] if self._job_items_has_updated_at_ts else []),
                        job_id,
                        item_key,
                    ),
                )
            else:
                self._execute(
                    conn,
                    f"UPDATE job_items SET status = ?, updated_at = ?{', updated_at_ts = ?' if self._job_items_has_updated_at_ts else ''} WHERE job_id = ? AND item_key = ?",
                    (
                        JobStatus.processing.value,
                        ts,
                        *([ts] if self._job_items_has_updated_at_ts else []),
                        job_id,
                        item_key,
                    ),
                )
            self._execute(
                conn,
                f"UPDATE jobs SET status = ?, updated_at = ?{', updated_at_ts = ?' if self._jobs_has_updated_at_ts else ''} WHERE job_id = ? AND status <> ?",
                (
                    JobStatus.processing.value,
                    ts,
                    *([ts] if self._jobs_has_updated_at_ts else []),
                    job_id,
                    JobStatus.completed.value,
                ),
            )
        self._maybe_refresh_postgres_result_materialized_views()

    def mark_item_completed(self, job_id: str, item_key: str, response_payload: dict[str, Any]) -> None:
        ts = now_iso()
        parsed_status = self._derive_parsed_status_from_response_payload(response_payload)
        with self._connect() as conn:
            if self._job_items_has_parsed_status:
                extra_set = ", updated_at_ts = ?" if self._job_items_has_updated_at_ts else ""
                self._execute(
                    conn,
                    f"""
                    UPDATE job_items
                    SET status = ?, parsed_status = ?, response_json = ?, error_text = NULL, updated_at = ?{extra_set}
                    WHERE job_id = ? AND item_key = ?
                    """,
                    (
                        JobStatus.completed.value,
                        parsed_status,
                        json.dumps(response_payload),
                        ts,
                        *([ts] if self._job_items_has_updated_at_ts else []),
                        job_id,
                        item_key,
                    ),
                )
            else:
                extra_set = ", updated_at_ts = ?" if self._job_items_has_updated_at_ts else ""
                self._execute(
                    conn,
                    f"""
                    UPDATE job_items
                    SET status = ?, response_json = ?, error_text = NULL, updated_at = ?{extra_set}
                    WHERE job_id = ? AND item_key = ?
                    """,
                    (
                        JobStatus.completed.value,
                        json.dumps(response_payload),
                        ts,
                        *([ts] if self._job_items_has_updated_at_ts else []),
                        job_id,
                        item_key,
                    ),
                )
        self._refresh_job_status(job_id)
        self._maybe_refresh_postgres_result_materialized_views()

    def mark_item_failed(self, job_id: str, item_key: str, error_text: str) -> None:
        ts = now_iso()
        with self._connect() as conn:
            if self._job_items_has_parsed_status:
                extra_set = ", updated_at_ts = ?" if self._job_items_has_updated_at_ts else ""
                self._execute(
                    conn,
                    f"""
                    UPDATE job_items
                    SET status = ?, parsed_status = ?, response_json = NULL, error_text = ?, updated_at = ?{extra_set}
                    WHERE job_id = ? AND item_key = ?
                    """,
                    (
                        JobStatus.failed.value,
                        "FAILED",
                        error_text[:2000],
                        ts,
                        *([ts] if self._job_items_has_updated_at_ts else []),
                        job_id,
                        item_key,
                    ),
                )
            else:
                extra_set = ", updated_at_ts = ?" if self._job_items_has_updated_at_ts else ""
                self._execute(
                    conn,
                    f"""
                    UPDATE job_items
                    SET status = ?, response_json = NULL, error_text = ?, updated_at = ?{extra_set}
                    WHERE job_id = ? AND item_key = ?
                    """,
                    (
                        JobStatus.failed.value,
                        error_text[:2000],
                        ts,
                        *([ts] if self._job_items_has_updated_at_ts else []),
                        job_id,
                        item_key,
                    ),
                )
        self._refresh_job_status(job_id)
        self._maybe_refresh_postgres_result_materialized_views()

    @staticmethod
    def _normalize_actimize_party_key(party_key: str | None) -> str:
        safe_key = str(party_key or "").strip()
        if not safe_key:
            return ""
        canonical_prefix = "AMLP_"
        upper_key = safe_key.upper()
        if upper_key.startswith("AMLP"):
            remainder = safe_key[4:].lstrip(" _-")
            return f"{canonical_prefix}{remainder}" if remainder else canonical_prefix
        return f"{canonical_prefix}{safe_key}"

    @staticmethod
    def _extract_party_keys_from_request_payload(request_payload: dict[str, Any] | None, fallback: str = "") -> list[str]:
        keys: list[str] = []

        def _append_values(raw_value: Any) -> None:
            if isinstance(raw_value, list):
                for list_item in raw_value:
                    safe_item = str(list_item or "").strip()
                    if safe_item:
                        keys.append(safe_item)
                return
            if isinstance(raw_value, str):
                safe_value = raw_value.strip()
                if safe_value:
                    keys.append(safe_value)

        props = (request_payload or {}).get("properties")
        if isinstance(props, dict):
            for key in ("partyKey", "party_key", "party key", "PartyKey"):
                _append_values(props.get(key))
            raw_mapping = props.get("partyKeysByScreeningType")
            if not isinstance(raw_mapping, dict):
                raw_mapping = props.get("party_keys_by_screening_type")
            if isinstance(raw_mapping, dict):
                for mapping_value in raw_mapping.values():
                    _append_values(mapping_value)
        safe_fallback = str(fallback or "").strip()
        if safe_fallback:
            keys.append(safe_fallback)
        deduped: list[str] = []
        seen: set[str] = set()
        for key in keys:
            normalized = key.upper()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(key)
        return deduped

    @classmethod
    def _extract_party_key_from_request_payload(cls, request_payload: dict[str, Any] | None, fallback: str = "") -> str:
        keys = cls._extract_party_keys_from_request_payload(request_payload, fallback=fallback)
        return keys[0] if keys else str(fallback or "").strip()

    @staticmethod
    def _parse_json_object(raw: Any) -> dict[str, Any] | None:
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            return None
        safe_raw = raw.strip()
        if not safe_raw:
            return None
        try:
            parsed = json.loads(safe_raw)
        except Exception:  # noqa: BLE001
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _normalize_user_old_id(value: str | None) -> str:
        return str(value or "").strip()

    @staticmethod
    def _normalize_user_name(value: str | None) -> str | None:
        safe = str(value or "").strip()
        return safe or None

    @staticmethod
    def _normalize_user_email(value: str | None) -> str | None:
        safe = str(value or "").strip().lower()
        return safe or None

    def _lookup_user_ref_id(self, conn: Any, user_old_id: str | None) -> int | None:
        safe_old_id = self._normalize_user_old_id(user_old_id)
        if not safe_old_id:
            return None
        row = self._execute(
            conn,
            """
            SELECT user_id
            FROM app_users
            WHERE old_id = ?
            LIMIT 1
            """,
            (safe_old_id,),
        ).fetchone()
        if not row:
            return None
        try:
            return int(row["user_id"])
        except Exception:  # noqa: BLE001
            return None

    def _ensure_user_ref(
        self,
        conn: Any,
        user_old_id: str | None,
        user_name: str | None = None,
        user_email: str | None = None,
    ) -> tuple[int | None, str | None, str | None, str | None]:
        safe_old_id = self._normalize_user_old_id(user_old_id)
        safe_name = self._normalize_user_name(user_name)
        safe_email = self._normalize_user_email(user_email)
        if not safe_old_id:
            return None, None, safe_name, safe_email

        ts = now_iso()
        if self.is_postgres:
            row = self._execute(
                conn,
                """
                INSERT INTO app_users(
                  old_id, is_active, name, email, created_at, updated_at
                ) VALUES(?, TRUE, ?, ?, ?, ?)
                ON CONFLICT(old_id)
                DO UPDATE SET
                  is_active = TRUE,
                  name = COALESCE(NULLIF(excluded.name, ''), app_users.name),
                  email = COALESCE(NULLIF(excluded.email, ''), app_users.email),
                  updated_at = excluded.updated_at
                RETURNING user_id, old_id, name, email
                """,
                (
                    safe_old_id,
                    safe_name,
                    safe_email,
                    ts,
                    ts,
                ),
            ).fetchone()
        else:
            self._execute(
                conn,
                """
                INSERT OR IGNORE INTO app_users(
                  old_id, is_active, name, email, created_at, updated_at
                ) VALUES(?, TRUE, ?, ?, ?, ?)
                """,
                (safe_old_id, safe_name, safe_email, ts, ts),
            )
            self._execute(
                conn,
                """
                UPDATE app_users
                SET
                  is_active = TRUE,
                  name = COALESCE(NULLIF(?, ''), name),
                  email = COALESCE(NULLIF(?, ''), email),
                  updated_at = ?
                WHERE old_id = ?
                """,
                (safe_name, safe_email, ts, safe_old_id),
            )
            row = self._execute(
                conn,
                """
                SELECT user_id, old_id, name, email
                FROM app_users
                WHERE old_id = ?
                LIMIT 1
                """,
                (safe_old_id,),
            ).fetchone()

        if not row:
            return None, safe_old_id, safe_name or safe_old_id, safe_email

        resolved_old_id = self._normalize_user_old_id(row["old_id"]) or safe_old_id
        resolved_name = self._normalize_user_name(row["name"]) or safe_name or resolved_old_id
        resolved_email = self._normalize_user_email(row["email"]) or safe_email
        try:
            user_ref_id = int(row["user_id"])
        except Exception:  # noqa: BLE001
            user_ref_id = None
        return user_ref_id, resolved_old_id, resolved_name, resolved_email

    @staticmethod
    def _fallback_search_definition_id_for_legacy_screening_type(source_value: str | None) -> str:
        normalized_source = JobRepository._normalize_screening_type_key(source_value)
        if not normalized_source:
            return ""

        explicit_aliases: dict[str, str] = {
            "sanction": "SD_US_Customers_Sanctions",
            "sanctions": "SD_US_Customers_Sanctions",
            "fincen 314(a)": "SD_US_Customers_314(a)",
            "fincen 314a": "SD_US_Customers_314(a)",
            "marijuana": "SD_US_Marijuana_DJ_External",
        }
        alias_value = explicit_aliases.get(normalized_source)
        if alias_value:
            return alias_value

        for screening_type, search_definition_id, _display_order, _name in DEFAULT_ACTIMIZE_SCREENING_TYPE_MAPPINGS:
            safe_search_definition_id = str(search_definition_id or "").strip()
            if not safe_search_definition_id:
                continue
            if normalized_source == JobRepository._normalize_screening_type_key(screening_type):
                return safe_search_definition_id
            if normalized_source == JobRepository._normalize_screening_type_key(safe_search_definition_id):
                return safe_search_definition_id
        return ""

    def _resolve_active_actimize_screening_type_row(self, source_value: str | None) -> Any | None:
        safe_source = str(source_value or "").strip()
        if not safe_source:
            return None

        with self._connect() as conn:
            return self._execute(
                conn,
                """
                SELECT "Search_Definition_ID" AS search_definition_id,
                       "Screening_Type" AS screening_type
                FROM actimize_screening_type_mappings
                WHERE is_active = TRUE
                  AND TRIM(COALESCE("Search_Definition_ID", '')) <> ''
                  AND (
                    LOWER("Screening_Type") = LOWER(?)
                    OR LOWER("Search_Definition_ID") = LOWER(?)
                    OR LOWER(COALESCE(search_definition_name, '')) = LOWER(?)
                  )
                ORDER BY CASE
                    WHEN LOWER("Screening_Type") = LOWER(?) THEN 0
                    WHEN LOWER("Search_Definition_ID") = LOWER(?) THEN 1
                    ELSE 2
                  END
                LIMIT 1
                """,
                (
                    safe_source,
                    safe_source,
                    safe_source,
                    safe_source,
                    safe_source,
                ),
            ).fetchone()

    @staticmethod
    def _apply_actimize_alert_to_response_payload(
        response_payload: dict[str, Any],
        *,
        unique_key: str,
        normalized_unique_key: str,
        alert_id: str,
        status_cd: str,
        screening_cd: str | None,
        update_timestamp: str | None,
        source_system_cd: str | None,
        tenant_cd: str | None,
        processed_at: str,
    ) -> None:
        existing_alert = response_payload.get("actimize_alert")
        merged_alert = dict(existing_alert) if isinstance(existing_alert, dict) else {}
        merged_alert.update(
            {
                "unique_key": unique_key,
                "normalized_unique_key": normalized_unique_key,
                "alert_id": alert_id,
                "screening_cd": screening_cd,
                "status_cd": status_cd,
                "update_timestamp": update_timestamp,
                "source_system_cd": source_system_cd,
                "tenant_cd": tenant_cd,
                "received_at": processed_at,
            }
        )
        response_payload["actimize_alert"] = merged_alert
        response_payload["actimize_alert_id"] = alert_id
        response_payload["actimize_alert_status_cd"] = status_cd
        response_payload["actimize_alert_status"] = "FALSE_POSITIVE" if status_cd == "F" else "TRUE_POSITIVE"
        response_payload["manual_status_cd"] = status_cd
        response_payload["manual_match"] = status_cd == "T"
        response_payload["engine_message"] = "NM" if status_cd == "F" else "PM"
        if screening_cd:
            response_payload["actimize_alert_screening_cd"] = screening_cd
        if update_timestamp:
            response_payload["actimize_alert_update_timestamp"] = update_timestamp
        if source_system_cd:
            response_payload["actimize_alert_source_system_cd"] = source_system_cd
        if tenant_cd:
            response_payload["actimize_alert_tenant_cd"] = tenant_cd

    def apply_actimize_alert_callback(
        self,
        *,
        unique_key: str,
        alert_id: str,
        screening_cd: str | None = None,
        status_cd: str,
        update_timestamp: str | None = None,
        source_system_cd: str | None = None,
        tenant_cd: str | None = None,
        correlation_id: str | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_unique_key = str(unique_key or "").strip()
        if not safe_unique_key:
            raise ValueError("unique_key is required")

        normalized_unique_key = self._normalize_actimize_party_key(safe_unique_key)
        if not normalized_unique_key:
            raise ValueError("unique_key is required")

        safe_alert_id = str(alert_id or "").strip()
        if not safe_alert_id:
            raise ValueError("alert_id is required")

        safe_status_cd = str(status_cd or "").strip().upper()
        if safe_status_cd not in {"F", "T"}:
            raise ValueError("status_cd must be F or T")

        safe_screening_cd = str(screening_cd or "").strip() or None
        safe_update_timestamp = str(update_timestamp or "").strip() or None
        safe_source_system_cd = str(source_system_cd or "").strip() or None
        safe_tenant_cd = str(tenant_cd or "").strip() or None
        safe_correlation_id = str(correlation_id or "").strip() or None
        safe_raw_payload = raw_payload if isinstance(raw_payload, dict) else {}

        candidate_tokens: set[str] = set()
        for token in (safe_unique_key, normalized_unique_key):
            safe_token = str(token or "").strip()
            if safe_token:
                candidate_tokens.add(safe_token)
        if normalized_unique_key.upper().startswith("AMLP_"):
            suffix = normalized_unique_key[5:].strip()
            if suffix:
                candidate_tokens.add(suffix)

        where_clauses: list[str] = []
        where_params: list[Any] = []
        for token in sorted(candidate_tokens):
            where_clauses.append("ji.request_json LIKE ?")
            where_params.append(f"%{token}%")
            where_clauses.append("ji.item_key = ?")
            where_params.append(token)
        where_sql = " OR ".join(where_clauses) if where_clauses else "1 = 0"

        processed_at = now_iso()
        matched_items: list[dict[str, str]] = []
        callback_id = 0

        with self._connect() as conn:
            candidate_rows = self._execute(
                conn,
                f"""
                SELECT ji.job_id, ji.item_key, ji.request_json, ji.response_json
                FROM job_items ji
                WHERE {where_sql}
                ORDER BY ji.updated_at DESC
                """,
                tuple(where_params),
            ).fetchall()

            for row in candidate_rows:
                request_payload = self._parse_json_object(row["request_json"]) or {}
                item_key = str(row["item_key"] or "").strip()
                resolved_party_keys = self._extract_party_keys_from_request_payload(request_payload, fallback=item_key)
                normalized_resolved_party_keys = {
                    self._normalize_actimize_party_key(resolved_party_key)
                    for resolved_party_key in resolved_party_keys
                    if str(resolved_party_key or "").strip()
                }
                if normalized_unique_key not in normalized_resolved_party_keys:
                    continue

                response_payload = self._parse_json_object(row["response_json"]) or {
                    "results": [],
                    "total": {"value": 0, "relation": "eq"},
                    "query": request_payload,
                    "status": 200,
                }
                self._apply_actimize_alert_to_response_payload(
                    response_payload,
                    unique_key=safe_unique_key,
                    normalized_unique_key=normalized_unique_key,
                    alert_id=safe_alert_id,
                    status_cd=safe_status_cd,
                    screening_cd=safe_screening_cd,
                    update_timestamp=safe_update_timestamp,
                    source_system_cd=safe_source_system_cd,
                    tenant_cd=safe_tenant_cd,
                    processed_at=processed_at,
                )

                responses_by_type = response_payload.get("responses_by_screening_type")
                if isinstance(responses_by_type, dict) and responses_by_type:
                    normalized_screening_cd = self._normalize_screening_type_key(safe_screening_cd)
                    matching_entries: list[dict[str, Any]] = []
                    for raw_type_key, raw_type_response in responses_by_type.items():
                        if not isinstance(raw_type_response, dict):
                            continue
                        if not normalized_screening_cd:
                            matching_entries.append(raw_type_response)
                            continue
                        candidates = (
                            str(raw_type_key or "").strip(),
                            str(raw_type_response.get("requested_screening_type") or "").strip(),
                            str(raw_type_response.get("actimize_screening_type") or "").strip(),
                        )
                        if any(self._normalize_screening_type_key(candidate) == normalized_screening_cd for candidate in candidates):
                            matching_entries.append(raw_type_response)

                    if not matching_entries and len(responses_by_type) == 1:
                        first_value = next(iter(responses_by_type.values()))
                        if isinstance(first_value, dict):
                            matching_entries.append(first_value)

                    for matched_response in matching_entries:
                        self._apply_actimize_alert_to_response_payload(
                            matched_response,
                            unique_key=safe_unique_key,
                            normalized_unique_key=normalized_unique_key,
                            alert_id=safe_alert_id,
                            status_cd=safe_status_cd,
                            screening_cd=safe_screening_cd,
                            update_timestamp=safe_update_timestamp,
                            source_system_cd=safe_source_system_cd,
                            tenant_cd=safe_tenant_cd,
                            processed_at=processed_at,
                        )

                if self._job_items_has_parsed_status:
                    self._execute(
                        conn,
                        f"""
                        UPDATE job_items
                        SET response_json = ?, parsed_status = ?, updated_at = ?{', updated_at_ts = ?' if self._job_items_has_updated_at_ts else ''}
                        WHERE job_id = ? AND item_key = ?
                        """,
                        (
                            json.dumps(response_payload),
                            self._derive_parsed_status_from_response_payload(response_payload),
                            processed_at,
                            *([processed_at] if self._job_items_has_updated_at_ts else []),
                            row["job_id"],
                            row["item_key"],
                        ),
                    )
                else:
                    self._execute(
                        conn,
                        f"""
                        UPDATE job_items
                        SET response_json = ?, updated_at = ?{', updated_at_ts = ?' if self._job_items_has_updated_at_ts else ''}
                        WHERE job_id = ? AND item_key = ?
                        """,
                        (
                            json.dumps(response_payload),
                            processed_at,
                            *([processed_at] if self._job_items_has_updated_at_ts else []),
                            row["job_id"],
                            row["item_key"],
                        ),
                    )
                matched_items.append({"job_id": str(row["job_id"]), "item_key": item_key})

            callback_details = {
                "correlation_id": safe_correlation_id,
                "normalized_unique_key": normalized_unique_key,
                "matched_items": matched_items[:200],
                "matched_count": len(matched_items),
                "raw_payload": safe_raw_payload,
            }

            if self.is_postgres:
                cur = self._execute(
                    conn,
                    """
                    INSERT INTO actimize_alert_callbacks(
                      created_at, unique_key, normalized_unique_key, alert_id, screening_cd,
                      status_cd, update_timestamp, source_system_cd, tenant_cd, matched_count, details_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING callback_id
                    """,
                    (
                        processed_at,
                        safe_unique_key,
                        normalized_unique_key,
                        safe_alert_id,
                        safe_screening_cd,
                        safe_status_cd,
                        safe_update_timestamp,
                        safe_source_system_cd,
                        safe_tenant_cd,
                        len(matched_items),
                        json.dumps(callback_details),
                    ),
                )
                row = cur.fetchone()
                callback_id = int(row["callback_id"]) if row else 0
            else:
                cur = self._execute(
                    conn,
                    """
                    INSERT INTO actimize_alert_callbacks(
                      created_at, unique_key, normalized_unique_key, alert_id, screening_cd,
                      status_cd, update_timestamp, source_system_cd, tenant_cd, matched_count, details_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        processed_at,
                        safe_unique_key,
                        normalized_unique_key,
                        safe_alert_id,
                        safe_screening_cd,
                        safe_status_cd,
                        safe_update_timestamp,
                        safe_source_system_cd,
                        safe_tenant_cd,
                        len(matched_items),
                        json.dumps(callback_details),
                    ),
                )
                callback_id = int(cur.lastrowid)

        self._maybe_refresh_postgres_result_materialized_views()
        return {
            "callback_id": callback_id,
            "unique_key": safe_unique_key,
            "normalized_unique_key": normalized_unique_key,
            "alert_id": safe_alert_id,
            "status_cd": safe_status_cd,
            "matched_items": len(matched_items),
            "processed_at": processed_at,
        }

    def _refresh_job_status(self, job_id: str) -> None:
        snapshot = self.get_job_snapshot(job_id)
        if not snapshot:
            return

        pending = snapshot["counts"]["pending"]
        processing = snapshot["counts"]["processing"]
        completed = snapshot["counts"]["completed"]
        failed = snapshot["counts"]["failed"]
        total_items = int(snapshot.get("total_items") or 0)

        if pending > 0 or processing > 0:
            status = JobStatus.processing.value
        elif total_items == 0:
            status = JobStatus.completed.value
        elif completed > 0:
            status = JobStatus.completed.value
        elif failed > 0:
            status = JobStatus.failed.value
        else:
            status = JobStatus.queued.value

        ts = now_iso()
        with self._connect() as conn:
            self._execute(
                conn,
                f"UPDATE jobs SET status = ?, updated_at = ?{', updated_at_ts = ?' if self._jobs_has_updated_at_ts else ''} WHERE job_id = ?",
                (
                    status,
                    ts,
                    *( [ts] if self._jobs_has_updated_at_ts else [] ),
                    job_id,
                ),
            )

    def get_job_snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            job = self._execute(
                conn,
                """
                SELECT
                  job_id, status, created_at, updated_at, total_items,
                  source_schedule_id, source_upload_id, user_id, user_name
                FROM jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            if not job:
                return None

            items = self._execute(
                conn,
                """
                SELECT item_key, request_json, response_json, status, error_text
                FROM job_items
                WHERE job_id = ?
                ORDER BY item_key ASC
                """,
                (job_id,),
            ).fetchall()

        parsed_items: list[dict[str, Any]] = []
        counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}

        for row in items:
            row_status = row["status"]
            if row_status == JobStatus.queued.value:
                counts["pending"] += 1
            elif row_status == JobStatus.processing.value:
                counts["processing"] += 1
            elif row_status == JobStatus.completed.value:
                counts["completed"] += 1
            elif row_status == JobStatus.failed.value:
                counts["failed"] += 1

            parsed_items.append(
                {
                    "item_key": row["item_key"],
                    "request": json.loads(row["request_json"]) if row["request_json"] else None,
                    "response": json.loads(row["response_json"]) if row["response_json"] else None,
                    "status": row_status,
                    "error_text": row["error_text"],
                }
            )

        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "created_at": JobRepository._to_iso_text(job["created_at"]) or "",
            "updated_at": JobRepository._to_iso_text(job["updated_at"]) or "",
            "total_items": int(job["total_items"] or 0),
            "source_schedule_id": job["source_schedule_id"],
            "source_upload_id": job["source_upload_id"],
            "user_id": job["user_id"],
            "user_name": job["user_name"],
            "counts": counts,
            "items": parsed_items,
        }

    @staticmethod
    def hash_query_payload(query_payload: dict[str, Any]) -> str:
        canonical = json.dumps(query_payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def filter_unscreened_schedule_queries(
        self,
        schedule_id: str,
        queries: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str], int]:
        safe_schedule_id = (schedule_id or "").strip()
        if not safe_schedule_id:
            hashes = {item_key: self.hash_query_payload(payload) for item_key, payload in queries.items()}
            return queries, hashes, 0

        with self._connect() as conn:
            rows = self._execute(
                conn,
                """
                SELECT record_hash
                FROM schedule_record_state
                WHERE schedule_id = ?
                """,
                (safe_schedule_id,),
            ).fetchall()
        already_screened = {str(row["record_hash"]).strip() for row in rows if row["record_hash"]}

        filtered: dict[str, dict[str, Any]] = {}
        hashes: dict[str, str] = {}
        skipped = 0
        for item_key, payload in queries.items():
            record_hash = self.hash_query_payload(payload)
            hashes[item_key] = record_hash
            if record_hash in already_screened:
                skipped += 1
                continue
            filtered[item_key] = payload
        return filtered, hashes, skipped

    def mark_schedule_record_screened(self, schedule_id: str, record_hash: str, job_id: str) -> None:
        safe_schedule_id = (schedule_id or "").strip()
        safe_hash = (record_hash or "").strip()
        safe_job_id = (job_id or "").strip() or None
        if not safe_schedule_id or not safe_hash:
            return

        ts = now_iso()
        with self._connect() as conn:
            self._execute(
                conn,
                """
                INSERT INTO schedule_record_state(
                  schedule_id, record_hash, first_seen_at, last_screened_at, last_job_id
                ) VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(schedule_id, record_hash)
                DO UPDATE SET
                  last_screened_at = excluded.last_screened_at,
                  last_job_id = excluded.last_job_id
                """,
                (safe_schedule_id, safe_hash, ts, ts, safe_job_id),
            )

    def create_or_update_daily_schedule(
        self,
        schedule_id: str,
        batch_name: str,
        user_id: str | None,
        user_name: str | None,
        business_unit_code: str | None,
        queries: dict[str, Any],
        screening_types: list[str],
        mock_screening: bool,
        timezone_name: str,
        run_hour: int,
        run_minute: int,
        schedule_frequency: str = "DAILY",
        schedule_run_at: str | None = None,
        source_upload_id: str | None = None,
        source_file_name: str | None = None,
        source_s3_uri: str | None = None,
    ) -> tuple[str, bool]:
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        safe_schedule_id = (schedule_id or "").strip()
        if not safe_schedule_id:
            safe_schedule_id = str(uuid4())
        safe_business_unit_code = self._normalize_business_unit_code(business_unit_code)

        safe_frequency = self.normalize_schedule_frequency(schedule_frequency)
        safe_timezone = timezone_name.strip() or "America/New_York"
        safe_hour = min(max(int(run_hour), 0), 23)
        safe_minute = min(max(int(run_minute), 0), 59)

        schedule_run_at_dt: datetime | None = None
        raw_schedule_run_at = (schedule_run_at or "").strip()
        if raw_schedule_run_at:
            iso_value = raw_schedule_run_at.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(iso_value)
            except ValueError as exc:
                raise ValueError("schedule_run_at must be a valid ISO-8601 datetime") from exc
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            schedule_run_at_dt = parsed.astimezone(timezone.utc)

            try:
                local_tz = ZoneInfo(safe_timezone)
            except ZoneInfoNotFoundError:
                local_tz = ZoneInfo("America/New_York")
            local_run = schedule_run_at_dt.astimezone(local_tz)
            safe_hour = min(max(int(local_run.hour), 0), 23)
            safe_minute = min(max(int(local_run.minute), 0), 59)

        if schedule_run_at_dt and schedule_run_at_dt > now:
            next_run_at = schedule_run_at_dt.isoformat()
        else:
            next_run_at = self.compute_next_run_at(
                now_utc=now,
                timezone_name=safe_timezone,
                run_hour=safe_hour,
                run_minute=safe_minute,
                schedule_frequency=safe_frequency,
            )

        with self._connect() as conn:
            user_ref_id, resolved_user_id, resolved_user_name, _ = self._ensure_user_ref(
                conn,
                user_old_id=user_id,
                user_name=user_name,
            )
            user_ref_set_sql = "user_ref_id = ?," if self._daily_schedules_has_user_ref_id else ""
            user_ref_set_params: tuple[Any, ...] = (user_ref_id,) if self._daily_schedules_has_user_ref_id else tuple()
            user_ref_insert_col_sql = "user_ref_id, " if self._daily_schedules_has_user_ref_id else ""
            user_ref_insert_val_sql = "?, " if self._daily_schedules_has_user_ref_id else ""
            user_ref_insert_params: tuple[Any, ...] = (user_ref_id,) if self._daily_schedules_has_user_ref_id else tuple()
            cur = self._execute(
                conn,
                f"""
                UPDATE daily_schedules
                SET
                  batch_name = ?,
                  {user_ref_set_sql}
                  user_id = ?,
                  user_name = ?,
                  queries_json = ?,
                  screening_types_json = ?,
                  mock_screening = ?,
                  schedule_frequency = ?,
                  timezone = ?,
                  run_hour = ?,
                  run_minute = ?,
                  next_run_at = ?,
                  source_upload_id = ?,
                  source_file_name = ?,
                  source_s3_uri = ?,
                  business_unit_code = ?,
                  is_active = TRUE
                WHERE schedule_id = ?
                """,
                (
                    batch_name.strip(),
                    *user_ref_set_params,
                    resolved_user_id,
                    resolved_user_name,
                    json.dumps(queries),
                    json.dumps(screening_types),
                    bool(mock_screening),
                    safe_frequency,
                    safe_timezone,
                    safe_hour,
                    safe_minute,
                    next_run_at,
                    (source_upload_id or "").strip() or None,
                    (source_file_name or "").strip() or None,
                    (source_s3_uri or "").strip() or None,
                    safe_business_unit_code or None,
                    safe_schedule_id,
                ),
            )
            if cur.rowcount > 0:
                return safe_schedule_id, False

            self._execute(
                conn,
                f"""
                INSERT INTO daily_schedules(
                  schedule_id, batch_name, {user_ref_insert_col_sql}user_id, user_name, queries_json, screening_types_json, mock_screening,
                  schedule_frequency, timezone, run_hour, run_minute, created_at, last_run_at, next_run_at, is_active,
                  source_upload_id, source_file_name, source_s3_uri, business_unit_code
                ) VALUES(?, ?, {user_ref_insert_val_sql}?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, TRUE, ?, ?, ?, ?)
                """,
                (
                    safe_schedule_id,
                    batch_name.strip(),
                    *user_ref_insert_params,
                    resolved_user_id,
                    resolved_user_name,
                    json.dumps(queries),
                    json.dumps(screening_types),
                    bool(mock_screening),
                    safe_frequency,
                    safe_timezone,
                    safe_hour,
                    safe_minute,
                    created_at,
                    next_run_at,
                    (source_upload_id or "").strip() or None,
                    (source_file_name or "").strip() or None,
                    (source_s3_uri or "").strip() or None,
                    safe_business_unit_code or None,
                ),
            )
        return safe_schedule_id, True

    def update_daily_schedule_source(
        self,
        schedule_id: str,
        queries: dict[str, Any],
        screening_types: list[str],
        mock_screening: bool,
        source_upload_id: str | None,
        source_file_name: str | None,
        source_s3_uri: str | None,
        business_unit_code: str | None = None,
        schedule_frequency: str | None = None,
        batch_name: str | None = None,
    ) -> bool:
        safe_schedule_id = (schedule_id or "").strip()
        if not safe_schedule_id:
            return False

        safe_frequency = self.normalize_schedule_frequency(schedule_frequency) if schedule_frequency else None
        safe_business_unit_code = self._normalize_business_unit_code(business_unit_code) if business_unit_code is not None else None

        with self._connect() as conn:
            if safe_frequency:
                cur = self._execute(
                    conn,
                    """
                    UPDATE daily_schedules
                    SET
                      queries_json = ?,
                      screening_types_json = ?,
                      mock_screening = ?,
                      source_upload_id = ?,
                      source_file_name = ?,
                      source_s3_uri = ?,
                      schedule_frequency = ?,
                      business_unit_code = COALESCE(?, business_unit_code),
                      batch_name = COALESCE(?, batch_name),
                      is_active = TRUE
                    WHERE schedule_id = ?
                    """,
                    (
                        json.dumps(queries),
                        json.dumps(screening_types),
                        bool(mock_screening),
                        (source_upload_id or "").strip() or None,
                        (source_file_name or "").strip() or None,
                        (source_s3_uri or "").strip() or None,
                        safe_frequency,
                        safe_business_unit_code,
                        (batch_name or "").strip() or None,
                        safe_schedule_id,
                    ),
                )
            else:
                cur = self._execute(
                    conn,
                    """
                    UPDATE daily_schedules
                    SET
                      queries_json = ?,
                      screening_types_json = ?,
                      mock_screening = ?,
                      source_upload_id = ?,
                      source_file_name = ?,
                      source_s3_uri = ?,
                      business_unit_code = COALESCE(?, business_unit_code),
                      batch_name = COALESCE(?, batch_name),
                      is_active = TRUE
                    WHERE schedule_id = ?
                    """,
                    (
                        json.dumps(queries),
                        json.dumps(screening_types),
                        bool(mock_screening),
                        (source_upload_id or "").strip() or None,
                        (source_file_name or "").strip() or None,
                        (source_s3_uri or "").strip() or None,
                        safe_business_unit_code,
                        (batch_name or "").strip() or None,
                        safe_schedule_id,
                    ),
                )
            return cur.rowcount > 0

    def get_daily_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        safe_schedule_id = (schedule_id or "").strip()
        if not safe_schedule_id:
            return None
        with self._connect() as conn:
            row = self._execute(
                conn,
                """
                SELECT
                  schedule_id, batch_name, user_id, user_name, queries_json, screening_types_json, mock_screening,
                  schedule_frequency, timezone, run_hour, run_minute, created_at, last_run_at, next_run_at, is_active,
                  source_upload_id, source_file_name, source_s3_uri, business_unit_code
                FROM daily_schedules
                WHERE schedule_id = ?
                """,
                (safe_schedule_id,),
            ).fetchone()
        if not row:
            return None
        return self._parse_daily_schedule_row(row)

    def list_due_daily_schedules(self, now_iso_utc: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = self._execute(
                conn,
                """
                SELECT
                  schedule_id, batch_name, user_id, user_name, queries_json, screening_types_json, mock_screening,
                  schedule_frequency, timezone, run_hour, run_minute, created_at, last_run_at, next_run_at, is_active,
                  source_upload_id, source_file_name, source_s3_uri, business_unit_code
                FROM daily_schedules
                WHERE is_active = TRUE
                  AND next_run_at <= ?
                ORDER BY next_run_at ASC
                """,
                (now_iso_utc,),
            ).fetchall()

        return [self._parse_daily_schedule_row(row) for row in rows]

    @staticmethod
    def _to_iso_text(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        safe = str(value).strip()
        return safe or None

    @staticmethod
    def _parse_daily_schedule_row(row: Any) -> dict[str, Any]:
        business_unit_code = ""
        source_upload_record_count: int | None = None
        try:
            business_unit_code = str(row["business_unit_code"] or "").strip()
        except Exception:  # noqa: BLE001
            business_unit_code = ""
        try:
            source_upload_record_count = int(row["source_upload_record_count"])
        except Exception:  # noqa: BLE001
            source_upload_record_count = None
        return {
            "schedule_id": row["schedule_id"],
            "batch_name": row["batch_name"],
            "user_id": row["user_id"],
            "user_name": row["user_name"],
            "queries": json.loads(row["queries_json"]) if row["queries_json"] else {},
            "screening_types": json.loads(row["screening_types_json"]) if row["screening_types_json"] else [],
            "mock_screening": _as_bool(row["mock_screening"]),
            "schedule_frequency": JobRepository.normalize_schedule_frequency(row["schedule_frequency"]),
            "timezone": row["timezone"],
            "run_hour": int(row["run_hour"]),
            "run_minute": int(row["run_minute"]),
            "created_at": JobRepository._to_iso_text(row["created_at"]) or "",
            "last_run_at": JobRepository._to_iso_text(row["last_run_at"]),
            "next_run_at": JobRepository._to_iso_text(row["next_run_at"]) or "",
            "is_active": _as_bool(row["is_active"]),
            "source_upload_id": row["source_upload_id"],
            "source_file_name": row["source_file_name"],
            "source_s3_uri": row["source_s3_uri"],
            "source_upload_record_count": source_upload_record_count,
            "business_unit_code": business_unit_code,
        }

    def list_active_daily_schedules(self, user_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            safe_user_old_id = self._normalize_user_old_id(user_id)
            user_ref_id = self._lookup_user_ref_id(conn, safe_user_old_id) if safe_user_old_id else None
            if safe_user_old_id and self._daily_schedules_has_user_ref_id and user_ref_id is None:
                rows = []
            elif safe_user_old_id:
                user_filter_sql = "ds.user_ref_id = ?" if self._daily_schedules_has_user_ref_id else "ds.user_id = ?"
                user_filter_param = user_ref_id if self._daily_schedules_has_user_ref_id else safe_user_old_id
                rows = self._execute(
                    conn,
                    f"""
                    SELECT
                      ds.schedule_id, ds.batch_name, ds.user_id, ds.user_name, ds.queries_json, ds.screening_types_json, ds.mock_screening,
                      ds.schedule_frequency, ds.timezone, ds.run_hour, ds.run_minute, ds.created_at, ds.last_run_at, ds.next_run_at, ds.is_active,
                      ds.source_upload_id, ds.source_file_name, ds.source_s3_uri, ds.business_unit_code,
                      bu.record_count AS source_upload_record_count
                    FROM daily_schedules ds
                    LEFT JOIN batch_file_uploads bu
                      ON bu.upload_id = ds.source_upload_id
                    WHERE ds.is_active = TRUE
                      AND {user_filter_sql}
                    ORDER BY ds.created_at DESC
                    """,
                    (user_filter_param,),
                ).fetchall()
            else:
                rows = self._execute(
                    conn,
                    """
                    SELECT
                      ds.schedule_id, ds.batch_name, ds.user_id, ds.user_name, ds.queries_json, ds.screening_types_json, ds.mock_screening,
                      ds.schedule_frequency, ds.timezone, ds.run_hour, ds.run_minute, ds.created_at, ds.last_run_at, ds.next_run_at, ds.is_active,
                      ds.source_upload_id, ds.source_file_name, ds.source_s3_uri, ds.business_unit_code,
                      bu.record_count AS source_upload_record_count
                    FROM daily_schedules ds
                    LEFT JOIN batch_file_uploads bu
                      ON bu.upload_id = ds.source_upload_id
                    WHERE ds.is_active = TRUE
                    ORDER BY ds.created_at DESC
                    """,
                ).fetchall()

        return [self._parse_daily_schedule_row(row) for row in rows]

    def list_active_daily_schedule_ids(self, user_id: str | None = None) -> set[str]:
        with self._connect() as conn:
            safe_user_old_id = self._normalize_user_old_id(user_id)
            user_ref_id = self._lookup_user_ref_id(conn, safe_user_old_id) if safe_user_old_id else None
            if safe_user_old_id and self._daily_schedules_has_user_ref_id and user_ref_id is None:
                rows = []
            elif safe_user_old_id:
                user_filter_sql = "user_ref_id = ?" if self._daily_schedules_has_user_ref_id else "user_id = ?"
                user_filter_param = user_ref_id if self._daily_schedules_has_user_ref_id else safe_user_old_id
                rows = self._execute(
                    conn,
                    f"""
                    SELECT schedule_id
                    FROM daily_schedules
                    WHERE is_active = TRUE
                      AND {user_filter_sql}
                    """,
                    (user_filter_param,),
                ).fetchall()
            else:
                rows = self._execute(
                    conn,
                    """
                    SELECT schedule_id
                    FROM daily_schedules
                    WHERE is_active = TRUE
                    """,
                ).fetchall()

        return {
            str(row["schedule_id"] or "").strip()
            for row in rows
            if str(row["schedule_id"] or "").strip()
        }

    def deactivate_daily_schedule(self, schedule_id: str) -> bool:
        with self._connect() as conn:
            cur = self._execute(
                conn,
                """
                UPDATE daily_schedules
                SET is_active = FALSE
                WHERE schedule_id = ?
                  AND is_active = TRUE
                """,
                (schedule_id,),
            )
            return cur.rowcount > 0

    def register_batch_file_upload(
        self,
        upload_id: str,
        file_name: str,
        user_id: str | None,
        user_name: str | None,
        record_count: int,
        file_hash: str | None = None,
        s3_bucket: str | None = None,
        s3_key: str | None = None,
        s3_uri: str | None = None,
        queries_s3_bucket: str | None = None,
        queries_s3_key: str | None = None,
        queries_s3_uri: str | None = None,
        schedule_id: str | None = None,
        job_id: str | None = None,
    ) -> str:
        created_at = now_iso()
        with self._connect() as conn:
            user_ref_id, resolved_user_id, resolved_user_name, _ = self._ensure_user_ref(
                conn,
                user_old_id=user_id,
                user_name=user_name,
            )
            user_ref_col_sql = "user_ref_id, " if self._batch_file_uploads_has_user_ref_id else ""
            user_ref_val_sql = "?, " if self._batch_file_uploads_has_user_ref_id else ""
            user_ref_params: tuple[Any, ...] = (user_ref_id,) if self._batch_file_uploads_has_user_ref_id else tuple()
            self._execute(
                conn,
                f"""
                INSERT INTO batch_file_uploads(
                  upload_id, schedule_id, job_id, {user_ref_col_sql}user_id, user_name, file_name, s3_bucket, s3_key,
                  s3_uri, queries_s3_bucket, queries_s3_key, queries_s3_uri, file_hash, record_count, created_at, is_active
                ) VALUES(?, ?, ?, {user_ref_val_sql}?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE)
                """,
                (
                    upload_id,
                    (schedule_id or "").strip() or None,
                    (job_id or "").strip() or None,
                    *user_ref_params,
                    resolved_user_id,
                    resolved_user_name,
                    file_name.strip(),
                    (s3_bucket or "").strip() or None,
                    (s3_key or "").strip() or None,
                    (s3_uri or "").strip() or None,
                    (queries_s3_bucket or "").strip() or None,
                    (queries_s3_key or "").strip() or None,
                    (queries_s3_uri or "").strip() or None,
                    (file_hash or "").strip() or None,
                    max(int(record_count), 0),
                    created_at,
                ),
            )
        return upload_id

    def get_batch_file_upload(self, upload_id: str) -> dict[str, Any] | None:
        safe_upload_id = (upload_id or "").strip()
        if not safe_upload_id:
            return None
        with self._connect() as conn:
            row = self._execute(
                conn,
                """
                SELECT
                  upload_id, schedule_id, job_id, user_id, user_name, file_name,
                  s3_bucket, s3_key, s3_uri,
                  queries_s3_bucket, queries_s3_key, queries_s3_uri,
                  file_hash, record_count, created_at, is_active
                FROM batch_file_uploads
                WHERE upload_id = ?
                LIMIT 1
                """,
                (safe_upload_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_batch_file_upload_record_count(self, upload_id: str, record_count: int) -> bool:
        safe_upload_id = (upload_id or "").strip()
        if not safe_upload_id:
            return False
        with self._connect() as conn:
            cur = self._execute(
                conn,
                """
                UPDATE batch_file_uploads
                SET record_count = ?
                WHERE upload_id = ?
                """,
                (max(int(record_count), 0), safe_upload_id),
            )
            return cur.rowcount > 0

    def update_job_total_items(self, job_id: str, total_items: int) -> None:
        safe_job_id = (job_id or "").strip()
        if not safe_job_id:
            return
        ts = now_iso()
        with self._connect() as conn:
            self._execute(
                conn,
                f"UPDATE jobs SET total_items = ?, updated_at = ?{', updated_at_ts = ?' if self._jobs_has_updated_at_ts else ''} WHERE job_id = ?",
                (max(int(total_items), 0), ts, *([ts] if self._jobs_has_updated_at_ts else []), safe_job_id),
            )

    def refresh_job_status(self, job_id: str) -> None:
        safe_job_id = (job_id or "").strip()
        if not safe_job_id:
            return
        self._refresh_job_status(safe_job_id)

    def mark_job_failed(self, job_id: str, error_text: str) -> None:
        safe_job_id = (job_id or "").strip()
        if not safe_job_id:
            return
        # Persist a terminal job-level failure without needing to create per-item rows.
        # Set total_items=0 to avoid "pending inferred" counts on the UI.
        ts = now_iso()
        with self._connect() as conn:
            self._execute(
                conn,
                f"UPDATE jobs SET status = ?, total_items = 0, updated_at = ?{', updated_at_ts = ?' if self._jobs_has_updated_at_ts else ''} WHERE job_id = ?",
                (JobStatus.failed.value, ts, *([ts] if self._jobs_has_updated_at_ts else []), safe_job_id),
            )
            self.add_audit_event(
                action="SCREENING_JOB_FAILED",
                entity_type="screening_job",
                entity_id=safe_job_id,
                details={"error": (error_text or "")[:2000]},
            )

    def add_job_items_bulk(self, job_id: str, items: list[tuple[str, dict[str, Any]]]) -> None:
        safe_job_id = (job_id or "").strip()
        if not safe_job_id or not items:
            return
        ts = now_iso()
        extra_col = ", updated_at_ts" if self._job_items_has_updated_at_ts else ""
        extra_placeholder_pg = ", %s" if self._job_items_has_updated_at_ts else ""
        extra_placeholder_sqlite = ", ?" if self._job_items_has_updated_at_ts else ""
        if self._job_items_has_parsed_status and self.is_postgres:
            query = """
                INSERT INTO job_items(job_id, item_key, request_json, response_json, status, parsed_status, error_text, updated_at{extra_col})
                VALUES(%s, %s, %s, NULL, %s, %s, NULL, %s{extra_placeholder_pg})
                ON CONFLICT (job_id, item_key) DO NOTHING
                """.format(extra_col=extra_col, extra_placeholder_pg=extra_placeholder_pg)
        elif self._job_items_has_parsed_status:
            query = """
                INSERT OR IGNORE INTO job_items(job_id, item_key, request_json, response_json, status, parsed_status, error_text, updated_at{extra_col})
                VALUES(?, ?, ?, NULL, ?, ?, NULL, ?{extra_placeholder_sqlite})
                """.format(extra_col=extra_col, extra_placeholder_sqlite=extra_placeholder_sqlite)
        elif self.is_postgres:
            query = """
                INSERT INTO job_items(job_id, item_key, request_json, response_json, status, error_text, updated_at{extra_col})
                VALUES(%s, %s, %s, NULL, %s, NULL, %s{extra_placeholder_pg})
                ON CONFLICT (job_id, item_key) DO NOTHING
                """.format(extra_col=extra_col, extra_placeholder_pg=extra_placeholder_pg)
        else:
            query = """
                INSERT OR IGNORE INTO job_items(job_id, item_key, request_json, response_json, status, error_text, updated_at{extra_col})
                VALUES(?, ?, ?, NULL, ?, NULL, ?{extra_placeholder_sqlite})
                """.format(extra_col=extra_col, extra_placeholder_sqlite=extra_placeholder_sqlite)

        if self._job_items_has_parsed_status:
            params = [
                (
                    safe_job_id,
                    (item_key or "").strip(),
                    json.dumps(request_payload),
                    JobStatus.queued.value,
                    "PENDING",
                    ts,
                    *([ts] if self._job_items_has_updated_at_ts else []),
                )
                for item_key, request_payload in items
                if (item_key or "").strip()
            ]
        else:
            params = [
                (
                    safe_job_id,
                    (item_key or "").strip(),
                    json.dumps(request_payload),
                    JobStatus.queued.value,
                    ts,
                    *([ts] if self._job_items_has_updated_at_ts else []),
                )
                for item_key, request_payload in items
                if (item_key or "").strip()
            ]
        if not params:
            return
        with self._connect() as conn:
            cur = conn.cursor()
            cur.executemany(self._sql(query), params)
        self._maybe_refresh_postgres_result_materialized_views()

    def attach_upload_to_job(self, upload_id: str, job_id: str) -> bool:
        with self._connect() as conn:
            cur = self._execute(
                conn,
                """
                UPDATE batch_file_uploads
                SET job_id = ?
                WHERE upload_id = ?
                """,
                ((job_id or "").strip() or None, (upload_id or "").strip()),
            )
            return cur.rowcount > 0

    def attach_upload_to_schedule(
        self,
        schedule_id: str,
        upload_id: str,
        file_name: str | None,
        s3_uri: str | None,
    ) -> bool:
        with self._connect() as conn:
            cur = self._execute(
                conn,
                """
                UPDATE daily_schedules
                SET source_upload_id = ?, source_file_name = ?, source_s3_uri = ?
                WHERE schedule_id = ?
                """,
                (
                    (upload_id or "").strip() or None,
                    (file_name or "").strip() or None,
                    (s3_uri or "").strip() or None,
                    (schedule_id or "").strip(),
                ),
            )
            return cur.rowcount > 0

    def upsert_schedule_subscription(
        self,
        schedule_id: str,
        user_id: str | None,
        user_name: str | None,
        email: str,
    ) -> str:
        safe_email = (email or "").strip().lower()
        if not safe_email:
            raise ValueError("Subscription email is required")
        safe_schedule_id = (schedule_id or "").strip()
        if not safe_schedule_id:
            raise ValueError("schedule_id is required")

        subscription_id = str(uuid4())
        ts = now_iso()
        with self._connect() as conn:
            user_ref_id, resolved_user_id, resolved_user_name, resolved_email = self._ensure_user_ref(
                conn,
                user_old_id=user_id,
                user_name=user_name,
                user_email=safe_email,
            )
            user_ref_col_sql = "user_ref_id, " if self._schedule_subscriptions_has_user_ref_id else ""
            user_ref_val_sql = "?, " if self._schedule_subscriptions_has_user_ref_id else ""
            user_ref_params: tuple[Any, ...] = (user_ref_id,) if self._schedule_subscriptions_has_user_ref_id else tuple()
            user_ref_update_sql = "user_ref_id = excluded.user_ref_id," if self._schedule_subscriptions_has_user_ref_id else ""
            self._execute(
                conn,
                f"""
                INSERT INTO schedule_subscriptions(
                  subscription_id, schedule_id, {user_ref_col_sql}user_id, user_name, email, is_active, created_at, updated_at
                ) VALUES(?, ?, {user_ref_val_sql}?, ?, ?, TRUE, ?, ?)
                ON CONFLICT(schedule_id, email)
                DO UPDATE SET
                  {user_ref_update_sql}
                  user_id = excluded.user_id,
                  user_name = excluded.user_name,
                  is_active = TRUE,
                  updated_at = excluded.updated_at
                """,
                (
                    subscription_id,
                    safe_schedule_id,
                    *user_ref_params,
                    resolved_user_id,
                    resolved_user_name,
                    resolved_email or safe_email,
                    ts,
                    ts,
                ),
            )
            row = self._execute(
                conn,
                """
                SELECT subscription_id
                FROM schedule_subscriptions
                WHERE schedule_id = ? AND email = ?
                """,
                (safe_schedule_id, safe_email),
            ).fetchone()
            return str(row["subscription_id"]) if row else subscription_id

    def deactivate_schedule_subscription(self, schedule_id: str, email: str) -> bool:
        safe_schedule_id = (schedule_id or "").strip()
        safe_email = (email or "").strip().lower()
        if not safe_schedule_id or not safe_email:
            return False

        with self._connect() as conn:
            cur = self._execute(
                conn,
                """
                UPDATE schedule_subscriptions
                SET is_active = FALSE, updated_at = ?
                WHERE schedule_id = ?
                  AND email = ?
                  AND is_active = TRUE
                """,
                (now_iso(), safe_schedule_id, safe_email),
            )
            return cur.rowcount > 0

    def list_schedule_subscriptions(self, schedule_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
        safe_schedule_id = (schedule_id or "").strip()
        if not safe_schedule_id:
            return []

        with self._connect() as conn:
            safe_user_old_id = self._normalize_user_old_id(user_id)
            user_ref_id = self._lookup_user_ref_id(conn, safe_user_old_id) if safe_user_old_id else None
            if safe_user_old_id and user_ref_id is None and self._schedule_subscriptions_has_user_ref_id:
                rows = []
            elif safe_user_old_id:
                user_filter_sql = "user_ref_id = ?" if self._schedule_subscriptions_has_user_ref_id else "user_id = ?"
                user_filter_param = user_ref_id if self._schedule_subscriptions_has_user_ref_id else safe_user_old_id
                rows = self._execute(
                    conn,
                    f"""
                    SELECT subscription_id, schedule_id, user_ref_id, user_id, user_name, email, is_active, created_at
                    FROM schedule_subscriptions
                    WHERE schedule_id = ?
                      AND {user_filter_sql}
                      AND is_active = TRUE
                    ORDER BY created_at DESC
                    """,
                    (safe_schedule_id, user_filter_param),
                ).fetchall()
            else:
                rows = self._execute(
                    conn,
                    """
                    SELECT subscription_id, schedule_id, user_ref_id, user_id, user_name, email, is_active, created_at
                    FROM schedule_subscriptions
                    WHERE schedule_id = ?
                      AND is_active = TRUE
                    ORDER BY created_at DESC
                    """,
                    (safe_schedule_id,),
                ).fetchall()

        return [
            {
                "subscription_id": row["subscription_id"],
                "schedule_id": row["schedule_id"],
                "user_ref_id": int(row["user_ref_id"]) if row["user_ref_id"] is not None else None,
                "user_id": row["user_id"],
                "user_name": row["user_name"],
                "email": row["email"],
                "is_active": _as_bool(row["is_active"]),
                "created_at": JobRepository._to_iso_text(row["created_at"]) or "",
            }
            for row in rows
        ]

    def count_active_schedule_subscriptions_for_email(self, email: str) -> int:
        safe_email = (email or "").strip().lower()
        if not safe_email:
            return 0

        with self._connect() as conn:
            row = self._execute(
                conn,
                """
                SELECT COUNT(*) AS total
                FROM schedule_subscriptions
                WHERE email = ?
                  AND is_active = TRUE
                """,
                (safe_email,),
            ).fetchone()
        return int(row["total"] or 0) if row else 0

    def claim_job_notification(self, job_id: str, schedule_id: str) -> bool:
        safe_job_id = (job_id or "").strip()
        safe_schedule_id = (schedule_id or "").strip()
        if not safe_job_id or not safe_schedule_id:
            return False

        ts = now_iso()
        with self._connect() as conn:
            if self.is_postgres:
                row = self._execute(
                    conn,
                    """
                    INSERT INTO job_schedule_notifications(job_id, schedule_id, created_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(job_id) DO NOTHING
                    RETURNING job_id
                    """,
                    (safe_job_id, safe_schedule_id, ts),
                ).fetchone()
                return bool(row)

            cur = self._execute(
                conn,
                """
                INSERT OR IGNORE INTO job_schedule_notifications(job_id, schedule_id, created_at)
                VALUES(?, ?, ?)
                """,
                (safe_job_id, safe_schedule_id, ts),
            )
            return cur.rowcount > 0

    def build_job_completion_summary(self, job_id: str) -> dict[str, Any] | None:
        snapshot = self.get_job_snapshot(job_id)
        if not snapshot:
            return None

        matched_items = 0
        for item in snapshot["items"]:
            response = item.get("response") or {}
            results = response.get("results")
            if isinstance(results, list) and any(bool(r.get("match")) for r in results if isinstance(r, dict)):
                matched_items += 1

        created_raw = str(snapshot.get("created_at") or "").strip()
        updated_raw = str(snapshot.get("updated_at") or "").strip()
        execution_seconds: int | None = None
        if created_raw and updated_raw:
            try:
                created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                updated_at = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
                delta = (updated_at - created_at).total_seconds()
                execution_seconds = max(int(delta), 0)
            except Exception:
                execution_seconds = None

        completed_items = int(snapshot["counts"]["completed"] or 0)
        failed_items = int(snapshot["counts"]["failed"] or 0)
        records_screened = completed_items + failed_items

        return {
            "job_id": snapshot["job_id"],
            "status": snapshot["status"],
            "total_items": snapshot["total_items"],
            "completed_items": completed_items,
            "failed_items": failed_items,
            "pending_items": snapshot["counts"]["pending"],
            "processing_items": snapshot["counts"]["processing"],
            "matched_items": matched_items,
            "clear_items": max(completed_items - matched_items, 0),
            "records_screened": records_screened,
            "execution_seconds": execution_seconds,
            "started_at": created_raw,
            "completed_at": updated_raw,
        }

    def create_schedule_notifications(
        self,
        schedule_id: str,
        job_id: str,
        title: str,
        message: str,
        summary: dict[str, Any],
    ) -> int:
        subs = self.list_schedule_subscriptions(schedule_id)
        if not subs:
            return 0

        created_at = now_iso()
        created = 0
        with self._connect() as conn:
            user_ref_col_sql = "user_ref_id, " if self._schedule_notifications_has_user_ref_id else ""
            user_ref_val_sql = "?, " if self._schedule_notifications_has_user_ref_id else ""
            for sub in subs:
                raw_sub_user_ref = sub.get("user_ref_id")
                sub_user_ref_id = int(raw_sub_user_ref) if isinstance(raw_sub_user_ref, int) or str(raw_sub_user_ref or "").isdigit() else None
                if self._schedule_notifications_has_user_ref_id and sub_user_ref_id is None:
                    sub_user_ref_id, _, _, _ = self._ensure_user_ref(
                        conn,
                        user_old_id=sub.get("user_id"),
                        user_name=sub.get("user_name"),
                        user_email=sub.get("email"),
                    )
                self._execute(
                    conn,
                    f"""
                    INSERT INTO schedule_notifications(
                      created_at, {user_ref_col_sql}user_id, user_name, email, schedule_id, job_id, title, message, summary_json
                    ) VALUES(?, {user_ref_val_sql}?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        created_at,
                        *([sub_user_ref_id] if self._schedule_notifications_has_user_ref_id else []),
                        sub.get("user_id"),
                        sub.get("user_name"),
                        sub.get("email"),
                        schedule_id,
                        job_id,
                        title.strip(),
                        message.strip(),
                        json.dumps(summary or {}),
                    ),
                )
                created += 1
        return created

    def maybe_publish_schedule_job_notification(self, job_id: str, schedule_id: str) -> int:
        summary = self.build_job_completion_summary(job_id)
        if not summary:
            return 0
        if summary["pending_items"] > 0 or summary["processing_items"] > 0:
            return 0
        if not self.claim_job_notification(job_id, schedule_id):
            return 0

        schedule = self.get_daily_schedule(schedule_id)
        batch_name = (schedule or {}).get("batch_name") or schedule_id
        total_items = int(summary.get("total_items") or 0)
        completed_items = int(summary.get("completed_items") or 0)
        failed_items = int(summary.get("failed_items") or 0)
        if total_items <= 0 or failed_items <= 0:
            completion_outcome = "Fully Completed"
        elif completed_items <= 0 and failed_items >= total_items:
            completion_outcome = "Fully Failed"
        else:
            completion_outcome = "Partially Completed"
        title = f"Scheduled screening {completion_outcome}: {batch_name}"
        message = (
            f"Job {job_id} is {completion_outcome}. "
            f"Total {summary['total_items']}, matches {summary['matched_items']}, "
            f"clear {summary['clear_items']}, failed {summary['failed_items']}, "
            f"completed {summary['completed_items']}."
        )
        return self.create_schedule_notifications(schedule_id, job_id, title, message, summary)

    def list_user_notifications(self, limit: int = 100, user_id: str | None = None, email: str | None = None) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 1000)
        safe_user_old_id = self._normalize_user_old_id(user_id) or None
        safe_email = (email or "").strip().lower() or None

        with self._connect() as conn:
            user_ref_id = self._lookup_user_ref_id(conn, safe_user_old_id) if safe_user_old_id else None
            if self._schedule_notifications_has_user_ref_id and safe_user_old_id and user_ref_id is not None and safe_email:
                rows = self._execute(
                    conn,
                    """
                    SELECT notification_id, created_at, user_id, user_name, email, schedule_id, job_id, title, message, summary_json
                    FROM schedule_notifications
                    WHERE user_ref_id = ? OR email = ?
                    ORDER BY notification_id DESC
                    LIMIT ?
                    """,
                    (user_ref_id, safe_email, safe_limit),
                ).fetchall()
            elif self._schedule_notifications_has_user_ref_id and safe_user_old_id and user_ref_id is not None:
                rows = self._execute(
                    conn,
                    """
                    SELECT notification_id, created_at, user_id, user_name, email, schedule_id, job_id, title, message, summary_json
                    FROM schedule_notifications
                    WHERE user_ref_id = ?
                    ORDER BY notification_id DESC
                    LIMIT ?
                    """,
                    (user_ref_id, safe_limit),
                ).fetchall()
            elif self._schedule_notifications_has_user_ref_id and safe_user_old_id and user_ref_id is None and safe_email:
                rows = self._execute(
                    conn,
                    """
                    SELECT notification_id, created_at, user_id, user_name, email, schedule_id, job_id, title, message, summary_json
                    FROM schedule_notifications
                    WHERE email = ?
                    ORDER BY notification_id DESC
                    LIMIT ?
                    """,
                    (safe_email, safe_limit),
                ).fetchall()
            elif self._schedule_notifications_has_user_ref_id and safe_user_old_id and user_ref_id is None:
                rows = []
            elif safe_user_old_id and safe_email:
                rows = self._execute(
                    conn,
                    """
                    SELECT notification_id, created_at, user_id, user_name, email, schedule_id, job_id, title, message, summary_json
                    FROM schedule_notifications
                    WHERE user_id = ? OR email = ?
                    ORDER BY notification_id DESC
                    LIMIT ?
                    """,
                    (safe_user_old_id, safe_email, safe_limit),
                ).fetchall()
            elif safe_user_old_id:
                rows = self._execute(
                    conn,
                    """
                    SELECT notification_id, created_at, user_id, user_name, email, schedule_id, job_id, title, message, summary_json
                    FROM schedule_notifications
                    WHERE user_id = ?
                    ORDER BY notification_id DESC
                    LIMIT ?
                    """,
                    (safe_user_old_id, safe_limit),
                ).fetchall()
            elif safe_email:
                rows = self._execute(
                    conn,
                    """
                    SELECT notification_id, created_at, user_id, user_name, email, schedule_id, job_id, title, message, summary_json
                    FROM schedule_notifications
                    WHERE email = ?
                    ORDER BY notification_id DESC
                    LIMIT ?
                    """,
                    (safe_email, safe_limit),
                ).fetchall()
            else:
                rows = self._execute(
                    conn,
                    """
                    SELECT notification_id, created_at, user_id, user_name, email, schedule_id, job_id, title, message, summary_json
                    FROM schedule_notifications
                    ORDER BY notification_id DESC
                    LIMIT ?
                    """,
                    (safe_limit,),
                ).fetchall()

        notifications: list[dict[str, Any]] = []
        for row in rows:
            notifications.append(
                {
                    "notification_id": int(row["notification_id"]),
                    "created_at": JobRepository._to_iso_text(row["created_at"]) or "",
                    "user_id": row["user_id"],
                    "user_name": row["user_name"],
                    "email": row["email"],
                    "schedule_id": row["schedule_id"],
                    "job_id": row["job_id"],
                    "title": row["title"],
                    "message": row["message"],
                    "summary": json.loads(row["summary_json"]) if row["summary_json"] else {},
                }
            )
        return notifications

    def list_business_units(self, user_id: str | None = None, include_inactive: bool = False) -> list[dict[str, Any]]:
        safe_user_old_id = self._normalize_user_old_id(user_id)
        with self._connect() as conn:
            user_ref_id = self._lookup_user_ref_id(conn, safe_user_old_id) if safe_user_old_id else None
            if safe_user_old_id and self._user_business_units_has_user_ref_id and user_ref_id is None:
                rows = []
            elif safe_user_old_id:
                user_filter_sql = "ubu.user_ref_id = ?" if self._user_business_units_has_user_ref_id else "ubu.user_id = ?"
                user_filter_param = user_ref_id if self._user_business_units_has_user_ref_id else safe_user_old_id
                rows = self._execute(
                    conn,
                    f"""
                    SELECT bu.business_unit_code, bu.business_unit_name, bu.is_active
                    FROM business_units bu
                    JOIN user_business_units ubu
                      ON ubu.business_unit_code = bu.business_unit_code
                     AND {user_filter_sql}
                     AND ubu.is_active = TRUE
                    WHERE (? = TRUE OR bu.is_active = TRUE)
                    ORDER BY bu.business_unit_name ASC, bu.business_unit_code ASC
                    """,
                    (user_filter_param, include_inactive),
                ).fetchall()
            else:
                rows = self._execute(
                    conn,
                    """
                    SELECT business_unit_code, business_unit_name, is_active
                    FROM business_units
                    WHERE (? = TRUE OR is_active = TRUE)
                    ORDER BY business_unit_name ASC, business_unit_code ASC
                    """,
                    (include_inactive,),
                ).fetchall()

        results = [
            {
                "business_unit_code": str(row["business_unit_code"] or "").strip(),
                "business_unit_name": str(row["business_unit_name"] or "").strip(),
                "is_active": _as_bool(row["is_active"]),
            }
            for row in rows
            if str(row["business_unit_code"] or "").strip()
        ]
        if safe_user_old_id and not results:
            fallback = self._get_business_unit_row(DEFAULT_FALLBACK_BUSINESS_UNIT_CODE, include_inactive=False)
            if fallback:
                return [fallback]
        return results

    def list_user_business_unit_codes(self, user_id: str) -> list[str]:
        safe_user_old_id = self._normalize_user_old_id(user_id)
        if not safe_user_old_id:
            return []
        rows = self.list_business_units(user_id=safe_user_old_id, include_inactive=False)
        return [str(row["business_unit_code"]).strip() for row in rows if str(row.get("business_unit_code") or "").strip()]

    def user_has_business_unit(self, user_id: str | None, business_unit_code: str | None) -> bool:
        safe_user_old_id = self._normalize_user_old_id(user_id)
        safe_code = self._normalize_business_unit_code(business_unit_code)
        if not safe_user_old_id or not safe_code:
            return False
        with self._connect() as conn:
            user_ref_id = self._lookup_user_ref_id(conn, safe_user_old_id) if self._user_business_units_has_user_ref_id else None
            if self._user_business_units_has_user_ref_id and user_ref_id is None:
                return False
            user_filter_sql = "ubu.user_ref_id = ?" if self._user_business_units_has_user_ref_id else "ubu.user_id = ?"
            user_filter_param = user_ref_id if self._user_business_units_has_user_ref_id else safe_user_old_id
            row = self._execute(
                conn,
                f"""
                SELECT 1
                FROM user_business_units ubu
                JOIN business_units bu
                  ON bu.business_unit_code = ubu.business_unit_code
                WHERE {user_filter_sql}
                  AND ubu.business_unit_code = ?
                  AND ubu.is_active = TRUE
                  AND bu.is_active = TRUE
                LIMIT 1
                """,
                (user_filter_param, safe_code),
            ).fetchone()
            if row:
                return True

            has_user_mapping = self._execute(
                conn,
                f"""
                SELECT 1
                FROM user_business_units ubu
                JOIN business_units bu
                  ON bu.business_unit_code = ubu.business_unit_code
                WHERE {user_filter_sql}
                  AND ubu.is_active = TRUE
                  AND bu.is_active = TRUE
                LIMIT 1
                """,
                (user_filter_param,),
            ).fetchone()
            if has_user_mapping:
                return False

            if safe_code != DEFAULT_FALLBACK_BUSINESS_UNIT_CODE:
                return False

            fallback = self._execute(
                conn,
                """
                SELECT 1
                FROM business_units
                WHERE business_unit_code = ?
                  AND is_active = TRUE
                LIMIT 1
                """,
                (DEFAULT_FALLBACK_BUSINESS_UNIT_CODE,),
            ).fetchone()
        return bool(fallback)

    def upsert_business_unit(self, business_unit_code: str, business_unit_name: str) -> dict[str, Any]:
        safe_code = self._normalize_business_unit_code(business_unit_code)
        safe_name = str(business_unit_name or "").strip()
        if not safe_code:
            raise ValueError("Business Unit code is required")
        if not safe_name:
            raise ValueError("Business Unit name is required")

        ts = now_iso()
        with self._connect() as conn:
            if self.is_postgres:
                self._execute(
                    conn,
                    """
                    INSERT INTO business_units(
                      business_unit_code, business_unit_name, is_active, created_at, updated_at
                    ) VALUES(?, ?, TRUE, ?, ?)
                    ON CONFLICT(business_unit_code)
                    DO UPDATE SET
                      business_unit_name = excluded.business_unit_name,
                      is_active = TRUE,
                      updated_at = excluded.updated_at
                    """,
                    (safe_code, safe_name, ts, ts),
                )
            else:
                self._execute(
                    conn,
                    """
                    INSERT INTO business_units(
                      business_unit_code, business_unit_name, is_active, created_at, updated_at
                    ) VALUES(?, ?, TRUE, ?, ?)
                    ON CONFLICT(business_unit_code)
                    DO UPDATE SET
                      business_unit_name = excluded.business_unit_name,
                      is_active = TRUE,
                      updated_at = excluded.updated_at
                    """,
                    (safe_code, safe_name, ts, ts),
                )

        matches = [row for row in self.list_business_units(include_inactive=True) if row["business_unit_code"] == safe_code]
        if not matches:
            raise ValueError("Failed to save Business Unit")
        return matches[0]

    def update_business_unit(
        self,
        business_unit_code: str,
        next_business_unit_code: str | None,
        next_business_unit_name: str | None,
    ) -> dict[str, Any] | None:
        safe_code = self._normalize_business_unit_code(business_unit_code)
        if not safe_code:
            return None
        desired_code = self._normalize_business_unit_code(next_business_unit_code) or safe_code
        desired_name = str(next_business_unit_name or "").strip()
        if not desired_name:
            raise ValueError("Business Unit name is required")

        ts = now_iso()
        with self._connect() as conn:
            existing = self._execute(
                conn,
                """
                SELECT business_unit_code
                FROM business_units
                WHERE business_unit_code = ?
                """,
                (safe_code,),
            ).fetchone()
            if not existing:
                return None

            if desired_code != safe_code:
                duplicate = self._execute(
                    conn,
                    """
                    SELECT business_unit_code
                    FROM business_units
                    WHERE business_unit_code = ?
                    """,
                    (desired_code,),
                ).fetchone()
                if duplicate:
                    raise ValueError(f"Business Unit code {desired_code} already exists")

            self._execute(
                conn,
                """
                UPDATE business_units
                SET business_unit_code = ?, business_unit_name = ?, is_active = TRUE, updated_at = ?
                WHERE business_unit_code = ?
                """,
                (desired_code, desired_name, ts, safe_code),
            )
            if desired_code != safe_code:
                self._execute(
                    conn,
                    """
                    UPDATE user_business_units
                    SET business_unit_code = ?, updated_at = ?
                    WHERE business_unit_code = ?
                    """,
                    (desired_code, ts, safe_code),
                )
                self._execute(
                    conn,
                    """
                    UPDATE job_metadata
                    SET business_unit_code = ?
                    WHERE business_unit_code = ?
                    """,
                    (desired_code, safe_code),
                )
                self._execute(
                    conn,
                    """
                    UPDATE daily_schedules
                    SET business_unit_code = ?
                    WHERE business_unit_code = ?
                    """,
                    (desired_code, safe_code),
                )

        matches = [row for row in self.list_business_units(include_inactive=True) if row["business_unit_code"] == desired_code]
        if not matches:
            return None
        return matches[0]

    def delete_business_unit(self, business_unit_code: str) -> bool:
        safe_code = self._normalize_business_unit_code(business_unit_code)
        if not safe_code:
            return False
        with self._connect() as conn:
            self._execute(
                conn,
                """
                DELETE FROM user_business_units
                WHERE business_unit_code = ?
                """,
                (safe_code,),
            )
            cur = self._execute(
                conn,
                """
                DELETE FROM business_units
                WHERE business_unit_code = ?
                """,
                (safe_code,),
            )
            return cur.rowcount > 0

    def set_user_business_units(
        self,
        user_id: str,
        user_name: str | None,
        business_unit_codes: list[str],
    ) -> list[str]:
        safe_user_old_id = self._normalize_user_old_id(user_id)
        if not safe_user_old_id:
            raise ValueError("user_id is required")

        seen: set[str] = set()
        normalized_codes: list[str] = []
        for raw in business_unit_codes:
            code = self._normalize_business_unit_code(raw)
            if not code or code in seen:
                continue
            seen.add(code)
            normalized_codes.append(code)

        ts = now_iso()
        with self._connect() as conn:
            user_ref_id, resolved_user_id, resolved_user_name, _ = self._ensure_user_ref(
                conn,
                user_old_id=safe_user_old_id,
                user_name=user_name,
            )
            if self._user_business_units_has_user_ref_id and user_ref_id is None:
                raise ValueError("Unable to resolve user for business-unit mapping")
            valid_codes: set[str] = set()
            if normalized_codes:
                placeholders = ", ".join("?" for _ in normalized_codes)
                rows = self._execute(
                    conn,
                    f"""
                    SELECT business_unit_code
                    FROM business_units
                    WHERE business_unit_code IN ({placeholders})
                      AND is_active = TRUE
                    """,
                    tuple(normalized_codes),
                ).fetchall()
                valid_codes = {self._normalize_business_unit_code(row["business_unit_code"]) for row in rows}

            self._execute(
                conn,
                f"""
                DELETE FROM user_business_units
                WHERE {"user_ref_id = ?" if self._user_business_units_has_user_ref_id else "user_id = ?"}
                """,
                ((user_ref_id if self._user_business_units_has_user_ref_id else safe_user_old_id),),
            )

            for code in normalized_codes:
                if code not in valid_codes:
                    continue
                user_ref_col_sql = "user_ref_id, " if self._user_business_units_has_user_ref_id else ""
                user_ref_val_sql = "?, " if self._user_business_units_has_user_ref_id else ""
                self._execute(
                    conn,
                    f"""
                    INSERT INTO user_business_units(
                      {user_ref_col_sql}user_id, user_name, business_unit_code, is_active, created_at, updated_at
                    ) VALUES({user_ref_val_sql}?, ?, ?, TRUE, ?, ?)
                    """,
                    (
                        *([user_ref_id] if self._user_business_units_has_user_ref_id else []),
                        resolved_user_id,
                        resolved_user_name,
                        code,
                        ts,
                        ts,
                    ),
                )

        return [code for code in normalized_codes if code in valid_codes]

    def list_user_business_unit_mappings(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = self._execute(
                conn,
                """
                SELECT
                  COALESCE(NULLIF(ubu.user_id, ''), au.old_id) AS user_id,
                  COALESCE(NULLIF(ubu.user_name, ''), au.name, au.old_id) AS user_name,
                  ubu.business_unit_code
                FROM user_business_units ubu
                LEFT JOIN app_users au
                  ON au.user_id = ubu.user_ref_id
                JOIN business_units bu
                  ON bu.business_unit_code = ubu.business_unit_code
                WHERE ubu.is_active = TRUE
                  AND bu.is_active = TRUE
                ORDER BY
                  LOWER(COALESCE(NULLIF(ubu.user_name, ''), au.name, au.old_id, NULLIF(ubu.user_id, ''))),
                  COALESCE(NULLIF(ubu.user_id, ''), au.old_id),
                  ubu.business_unit_code
                """,
            ).fetchall()

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            user_id = str(row["user_id"] or "").strip()
            if not user_id:
                continue
            code = self._normalize_business_unit_code(row["business_unit_code"])
            if not code:
                continue
            current = grouped.setdefault(
                user_id,
                {
                    "user_id": user_id,
                    "user_name": str(row["user_name"] or "").strip() or user_id,
                    "business_unit_codes": [],
                },
            )
            codes = current["business_unit_codes"]
            if code not in codes:
                codes.append(code)

        return list(grouped.values())

    def list_known_users(self) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = self._execute(
                conn,
                """
                SELECT old_id AS user_id, COALESCE(NULLIF(name, ''), old_id) AS user_name
                FROM app_users
                WHERE is_active = TRUE
                  AND TRIM(COALESCE(old_id, '')) <> ''
                """,
            ).fetchall()

        return [
            {
                "user_id": str(row["user_id"]).strip(),
                "display_name": str(row["user_name"] or row["user_id"]).strip() or str(row["user_id"]).strip(),
            }
            for row in sorted(
                rows,
                key=lambda item: (
                    str(item["user_name"] or item["user_id"]).strip().lower(),
                    str(item["user_id"]).strip().lower(),
                ),
            )
            if str(row["user_id"] or "").strip()
        ]

    def add_audit_event(
        self,
        action: str,
        user_id: str | None = None,
        user_name: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        created_at = now_iso()
        with self._connect() as conn:
            user_ref_id, resolved_user_id, resolved_user_name, _ = self._ensure_user_ref(
                conn,
                user_old_id=user_id,
                user_name=user_name,
            )
            user_ref_col_sql = "user_ref_id, " if self._audit_events_has_user_ref_id else ""
            user_ref_val_sql = "?, " if self._audit_events_has_user_ref_id else ""
            user_ref_params: tuple[Any, ...] = (user_ref_id,) if self._audit_events_has_user_ref_id else tuple()
            if self.is_postgres:
                cur = self._execute(
                    conn,
                    f"""
                    INSERT INTO audit_events(
                      created_at, {user_ref_col_sql}user_id, user_name, action, entity_type, entity_id, details_json
                    ) VALUES(?, {user_ref_val_sql}?, ?, ?, ?, ?, ?)
                    RETURNING event_id
                    """,
                    (
                        created_at,
                        *user_ref_params,
                        resolved_user_id,
                        resolved_user_name,
                        action.strip() or "UNKNOWN",
                        (entity_type or "").strip() or None,
                        (entity_id or "").strip() or None,
                        json.dumps(details or {}),
                    ),
                )
                row = cur.fetchone()
                return int(row["event_id"]) if row else 0

            cur = self._execute(
                conn,
                f"""
                INSERT INTO audit_events(
                  created_at, {user_ref_col_sql}user_id, user_name, action, entity_type, entity_id, details_json
                ) VALUES(?, {user_ref_val_sql}?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    *user_ref_params,
                    resolved_user_id,
                    resolved_user_name,
                    action.strip() or "UNKNOWN",
                    (entity_type or "").strip() or None,
                    (entity_id or "").strip() or None,
                    json.dumps(details or {}),
                ),
            )
            return int(cur.lastrowid)

    def add_external_api_error(
        self,
        provider: str,
        error_text: str,
        operation: str | None = None,
        endpoint: str | None = None,
        status_code: int | None = None,
        user_id: str | None = None,
        user_name: str | None = None,
        job_id: str | None = None,
        item_key: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        created_at = now_iso()
        safe_provider = str(provider or "").strip().lower() or "unknown"
        safe_error = str(error_text or "").strip() or "Unknown external API error"
        safe_status = int(status_code) if isinstance(status_code, int) else None
        with self._connect() as conn:
            user_ref_id, resolved_user_id, resolved_user_name, _ = self._ensure_user_ref(
                conn,
                user_old_id=user_id,
                user_name=user_name,
            )
            user_ref_col_sql = "user_ref_id, " if self._external_api_errors_has_user_ref_id else ""
            user_ref_val_sql = "?, " if self._external_api_errors_has_user_ref_id else ""
            user_ref_params: tuple[Any, ...] = (user_ref_id,) if self._external_api_errors_has_user_ref_id else tuple()
            if self.is_postgres:
                cur = self._execute(
                    conn,
                    f"""
                    INSERT INTO external_api_errors(
                      created_at, provider, operation, endpoint, status_code,
                      {user_ref_col_sql}user_id, user_name, job_id, item_key, error_text, details_json
                    ) VALUES(?, ?, ?, ?, ?, {user_ref_val_sql}?, ?, ?, ?, ?, ?)
                    RETURNING error_id
                    """,
                    (
                        created_at,
                        safe_provider,
                        (operation or "").strip() or None,
                        (endpoint or "").strip() or None,
                        safe_status,
                        *user_ref_params,
                        resolved_user_id,
                        resolved_user_name,
                        (job_id or "").strip() or None,
                        (item_key or "").strip() or None,
                        safe_error,
                        json.dumps(details or {}),
                    ),
                )
                row = cur.fetchone()
                return int(row["error_id"]) if row else 0

            cur = self._execute(
                conn,
                f"""
                INSERT INTO external_api_errors(
                  created_at, provider, operation, endpoint, status_code,
                  {user_ref_col_sql}user_id, user_name, job_id, item_key, error_text, details_json
                ) VALUES(?, ?, ?, ?, ?, {user_ref_val_sql}?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    safe_provider,
                    (operation or "").strip() or None,
                    (endpoint or "").strip() or None,
                    safe_status,
                    *user_ref_params,
                    resolved_user_id,
                    resolved_user_name,
                    (job_id or "").strip() or None,
                    (item_key or "").strip() or None,
                    safe_error,
                    json.dumps(details or {}),
                ),
            )
            return int(cur.lastrowid)

    def add_api_access_log(
        self,
        request_method: str,
        request_path: str,
        status_code: int,
        duration_ms: int,
        correlation_id: str | None = None,
        query_string: str | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
        user_id: str | None = None,
        user_name: str | None = None,
        auth_state: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        created_at = now_iso()
        safe_status = int(status_code) if isinstance(status_code, int) else 0
        safe_duration = max(int(duration_ms), 0)
        with self._connect() as conn:
            user_ref_id, resolved_user_id, resolved_user_name, _ = self._ensure_user_ref(
                conn,
                user_old_id=user_id,
                user_name=user_name,
            )
            user_ref_col_sql = "user_ref_id, " if self._api_access_logs_has_user_ref_id else ""
            user_ref_val_sql = "?, " if self._api_access_logs_has_user_ref_id else ""
            user_ref_params: tuple[Any, ...] = (user_ref_id,) if self._api_access_logs_has_user_ref_id else tuple()
            if self.is_postgres:
                cur = self._execute(
                    conn,
                    f"""
                    INSERT INTO api_access_logs(
                      created_at, correlation_id, request_method, request_path, query_string,
                      status_code, duration_ms, client_ip, user_agent, {user_ref_col_sql}user_id, user_name, auth_state, details_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, {user_ref_val_sql}?, ?, ?, ?)
                    RETURNING access_id
                    """,
                    (
                        created_at,
                        (correlation_id or "").strip() or None,
                        str(request_method or "").strip().upper() or "GET",
                        str(request_path or "").strip() or "/",
                        (query_string or "").strip() or None,
                        safe_status,
                        safe_duration,
                        (client_ip or "").strip() or None,
                        (user_agent or "").strip() or None,
                        *user_ref_params,
                        resolved_user_id,
                        resolved_user_name,
                        (auth_state or "").strip() or None,
                        json.dumps(details or {}),
                    ),
                )
                row = cur.fetchone()
                return int(row["access_id"]) if row else 0

            cur = self._execute(
                conn,
                f"""
                INSERT INTO api_access_logs(
                  created_at, correlation_id, request_method, request_path, query_string,
                  status_code, duration_ms, client_ip, user_agent, {user_ref_col_sql}user_id, user_name, auth_state, details_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, {user_ref_val_sql}?, ?, ?, ?)
                """,
                (
                    created_at,
                    (correlation_id or "").strip() or None,
                    str(request_method or "").strip().upper() or "GET",
                    str(request_path or "").strip() or "/",
                    (query_string or "").strip() or None,
                    safe_status,
                    safe_duration,
                    (client_ip or "").strip() or None,
                    (user_agent or "").strip() or None,
                    *user_ref_params,
                    resolved_user_id,
                    resolved_user_name,
                    (auth_state or "").strip() or None,
                    json.dumps(details or {}),
                ),
            )
            return int(cur.lastrowid)

    def purge_old_operational_data(
        self,
        audit_event_retention_days: int | None = None,
        api_access_log_retention_days: int | None = None,
        external_api_error_retention_days: int | None = None,
    ) -> dict[str, int]:
        deleted = {"audit_events": 0, "api_access_logs": 0, "external_api_errors": 0}
        now_utc = datetime.now(timezone.utc)

        with self._connect() as conn:
            if isinstance(audit_event_retention_days, int) and audit_event_retention_days > 0:
                cutoff = (now_utc - timedelta(days=audit_event_retention_days)).isoformat()
                cur = self._execute(
                    conn,
                    """
                    DELETE FROM audit_events
                    WHERE created_at < ?
                    """,
                    (cutoff,),
                )
                deleted["audit_events"] = max(int(cur.rowcount or 0), 0)

            if isinstance(api_access_log_retention_days, int) and api_access_log_retention_days > 0:
                cutoff = (now_utc - timedelta(days=api_access_log_retention_days)).isoformat()
                cur = self._execute(
                    conn,
                    """
                    DELETE FROM api_access_logs
                    WHERE created_at < ?
                    """,
                    (cutoff,),
                )
                deleted["api_access_logs"] = max(int(cur.rowcount or 0), 0)

            if isinstance(external_api_error_retention_days, int) and external_api_error_retention_days > 0:
                cutoff = (now_utc - timedelta(days=external_api_error_retention_days)).isoformat()
                cur = self._execute(
                    conn,
                    """
                    DELETE FROM external_api_errors
                    WHERE created_at < ?
                    """,
                    (cutoff,),
                )
                deleted["external_api_errors"] = max(int(cur.rowcount or 0), 0)

        return deleted

    def maybe_emit_high_risk_external_api_failure_alert(
        self,
        provider: str,
        operation: str | None = None,
        threshold: int = 10,
        window_minutes: int = 15,
        correlation_id: str | None = None,
    ) -> dict[str, Any] | None:
        safe_threshold = max(int(threshold or 0), 1)
        safe_window = max(int(window_minutes or 0), 1)
        safe_provider = str(provider or "").strip().lower() or "unknown"
        safe_operation = str(operation or "").strip() or None
        window_start = (datetime.now(timezone.utc) - timedelta(minutes=safe_window)).isoformat()

        with self._connect() as conn:
            if safe_operation:
                count_row = self._execute(
                    conn,
                    """
                    SELECT COUNT(*) AS total
                    FROM external_api_errors
                    WHERE provider = ?
                      AND operation = ?
                      AND created_at >= ?
                    """,
                    (safe_provider, safe_operation, window_start),
                ).fetchone()
            else:
                count_row = self._execute(
                    conn,
                    """
                    SELECT COUNT(*) AS total
                    FROM external_api_errors
                    WHERE provider = ?
                      AND created_at >= ?
                    """,
                    (safe_provider, window_start),
                ).fetchone()
            total_errors = 0
            if count_row is not None:
                try:
                    total_errors = int(count_row["total"] or 0)
                except Exception:  # pragma: no cover - defensive fallback
                    total_errors = int(dict(count_row).get("total", 0))
            if total_errors < safe_threshold:
                return None

            provider_pattern = f'%\"provider\": \"{safe_provider}\"%'
            if safe_operation:
                operation_pattern = f'%\"operation\": \"{safe_operation}\"%'
                existing = self._execute(
                    conn,
                    """
                    SELECT event_id
                    FROM audit_events
                    WHERE action = 'HIGH_RISK_EXTERNAL_API_FAILURE_ALERT'
                      AND created_at >= ?
                      AND details_json LIKE ?
                      AND details_json LIKE ?
                    ORDER BY event_id DESC
                    LIMIT 1
                    """,
                    (window_start, provider_pattern, operation_pattern),
                ).fetchone()
            else:
                existing = self._execute(
                    conn,
                    """
                    SELECT event_id
                    FROM audit_events
                    WHERE action = 'HIGH_RISK_EXTERNAL_API_FAILURE_ALERT'
                      AND created_at >= ?
                      AND details_json LIKE ?
                    ORDER BY event_id DESC
                    LIMIT 1
                    """,
                    (window_start, provider_pattern),
                ).fetchone()

            if existing:
                return {
                    "provider": safe_provider,
                    "operation": safe_operation,
                    "window_minutes": safe_window,
                    "threshold": safe_threshold,
                    "total_errors": total_errors,
                    "new_alert_created": False,
                }

        self.add_audit_event(
            action="HIGH_RISK_EXTERNAL_API_FAILURE_ALERT",
            entity_type="external_api_errors",
            entity_id=safe_provider,
            details={
                "provider": safe_provider,
                "operation": safe_operation,
                "window_minutes": safe_window,
                "threshold": safe_threshold,
                "total_errors": total_errors,
                "correlation_id": (correlation_id or "").strip() or None,
            },
        )

        return {
            "provider": safe_provider,
            "operation": safe_operation,
            "window_minutes": safe_window,
            "threshold": safe_threshold,
            "total_errors": total_errors,
            "new_alert_created": True,
        }

    def _build_audit_events_where_clause(
        self,
        conn: Any,
        user_id: str | None = None,
        errors_only: bool = False,
    ) -> tuple[str, tuple[Any, ...]]:
        clauses: list[str] = []
        params: list[Any] = []
        safe_user_id = self._normalize_user_old_id(user_id)
        if safe_user_id:
            if self._audit_events_has_user_ref_id:
                user_ref_id = self._lookup_user_ref_id(conn, safe_user_id)
                if user_ref_id is None:
                    return "WHERE 1=0", tuple()
                clauses.append("e.user_ref_id = ?")
                params.append(user_ref_id)
            else:
                clauses.append("e.user_id = ?")
                params.append(safe_user_id)
        if errors_only:
            clauses.append(
                """(
                    UPPER(e.action) LIKE ?
                    OR e.details_json LIKE ?
                    OR e.details_json LIKE ?
                    OR e.details_json LIKE ?
                )"""
            )
            params.extend(["%FAILED%", '%"error"%', '%"error_text"%', '%"detail"%'])
        if not clauses:
            return "", tuple()
        return f"WHERE {' AND '.join(clauses)}", tuple(params)

    def list_audit_events_page(
        self,
        limit: int = 200,
        user_id: str | None = None,
        offset: int = 0,
        errors_only: bool = False,
    ) -> dict[str, Any]:
        safe_limit = min(max(int(limit), 1), 1000)
        safe_offset = max(int(offset), 0)
        with self._connect() as conn:
            where_sql, where_params = self._build_audit_events_where_clause(
                conn,
                user_id=user_id,
                errors_only=errors_only,
            )
            total_row = self._execute(
                conn,
                f"""
                SELECT COUNT(1) AS total
                FROM audit_events e
                {where_sql}
                """,
                where_params,
            ).fetchone()
            total = int(total_row["total"] or 0) if total_row else 0

            rows = self._execute(
                conn,
                f"""
                SELECT
                  e.event_id,
                  e.created_at,
                  COALESCE(NULLIF(e.user_id, ''), au.old_id) AS user_id,
                  COALESCE(NULLIF(e.user_name, ''), au.name, au.old_id) AS user_name,
                  e.action,
                  e.entity_type,
                  e.entity_id,
                  e.details_json
                FROM audit_events e
                LEFT JOIN app_users au
                  ON au.user_id = e.user_ref_id
                {where_sql}
                ORDER BY e.event_id DESC
                LIMIT ?
                OFFSET ?
                """,
                (*where_params, safe_limit, safe_offset),
            ).fetchall()

        events: list[dict[str, Any]] = []
        for row in rows:
            resolved_user_id = row["user_id"]
            resolved_user_name = row["user_name"]
            details_payload: dict[str, Any] = {}
            raw_details = row["details_json"]
            if raw_details:
                try:
                    parsed = json.loads(raw_details)
                    if isinstance(parsed, dict):
                        details_payload = parsed
                except Exception:  # noqa: BLE001
                    details_payload = {}
            events.append(
                {
                    "event_id": int(row["event_id"]),
                    "created_at": JobRepository._to_iso_text(row["created_at"]) or "",
                    "user_id": resolved_user_id,
                    "user_name": resolved_user_name,
                    "action": row["action"],
                    "entity_type": row["entity_type"],
                    "entity_id": row["entity_id"],
                    "details": details_payload,
                }
            )
        return {
            "items": events,
            "total": total,
            "limit": safe_limit,
            "offset": safe_offset,
        }

    def list_audit_events(
        self,
        limit: int = 200,
        user_id: str | None = None,
        offset: int = 0,
        errors_only: bool = False,
    ) -> list[dict[str, Any]]:
        page = self.list_audit_events_page(limit=limit, user_id=user_id, offset=offset, errors_only=errors_only)
        return list(page["items"])

    def claim_daily_schedule_run(
        self,
        schedule_id: str,
        expected_next_run_at: str,
        last_run_at: str,
        next_run_at: str,
    ) -> bool:
        with self._connect() as conn:
            cur = self._execute(
                conn,
                """
                UPDATE daily_schedules
                SET last_run_at = ?, next_run_at = ?
                WHERE schedule_id = ?
                  AND is_active = TRUE
                  AND next_run_at = ?
                """,
                (last_run_at, next_run_at, schedule_id, expected_next_run_at),
            )
            return cur.rowcount > 0

