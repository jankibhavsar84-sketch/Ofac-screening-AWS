from __future__ import annotations

import calendar
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import JobStatus, now_iso

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - optional dependency for local sqlite mode
    psycopg = None
    dict_row = None


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


def _is_technical_identifier(value: str | None) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return True
    if raw.isdigit():
        return True
    if _UUID_RE.match(raw):
        return True
    return False


class JobRepository:
    def __init__(self, db_path: str, db_url: str = "") -> None:
        self.db_path = db_path
        self.db_url = (db_url or "").strip()
        self.is_postgres = self.db_url.startswith("postgres://") or self.db_url.startswith("postgresql://")

        if self.is_postgres and psycopg is None:
            raise RuntimeError("PostgreSQL driver not installed. Add psycopg[binary] to requirements.")

        self._ensure_db()

    def _connect(self) -> Any:
        if self.is_postgres:
            return psycopg.connect(self.db_url, row_factory=dict_row)

        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _sql(self, query: str) -> str:
        if not self.is_postgres:
            return query
        return query.replace("?", "%s")

    def _execute(self, conn: Any, query: str, params: tuple[Any, ...] = ()) -> Any:
        return conn.execute(self._sql(query), params)

    def _ensure_db(self) -> None:
        if not self.is_postgres:
            db_file = Path(self.db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as conn:
            self._execute(
                conn,
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
            self._execute(
                conn,
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
            self._execute(
                conn,
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
            self._execute(
                conn,
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
            self._execute(
                conn,
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
            self._execute(
                conn,
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
            self._execute(
                conn,
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
            self._execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS job_schedule_notifications (
                  job_id TEXT PRIMARY KEY,
                  schedule_id TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                """,
            )

            if self.is_postgres:
                self._execute(
                    conn,
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
                self._execute(
                    conn,
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
                self._execute(
                    conn,
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
                self._execute(
                    conn,
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
                self._execute(
                    conn,
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
                self._execute(
                    conn,
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
                self._execute(
                    conn,
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
                self._execute(
                    conn,
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

            self._execute(
                conn,
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
            self._execute(
                conn,
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

            self._execute(
                conn,
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_schedule_subscriptions_unique
                ON schedule_subscriptions(schedule_id, email);
                """,
            )
            self._execute(
                conn,
                """
                CREATE INDEX IF NOT EXISTS idx_daily_schedules_next_run
                ON daily_schedules(next_run_at);
                """,
            )
            self._execute(
                conn,
                """
                CREATE INDEX IF NOT EXISTS idx_notifications_user
                ON schedule_notifications(user_id, created_at);
                """,
            )
            self._execute(
                conn,
                """
                CREATE INDEX IF NOT EXISTS idx_notifications_email
                ON schedule_notifications(email, created_at);
                """,
            )
            self._execute(
                conn,
                """
                CREATE INDEX IF NOT EXISTS idx_user_business_units_user
                ON user_business_units(user_id, is_active);
                """,
            )
            self._execute(
                conn,
                """
                CREATE INDEX IF NOT EXISTS idx_user_business_units_code
                ON user_business_units(business_unit_code, is_active);
                """,
            )
            self._execute(
                conn,
                """
                CREATE INDEX IF NOT EXISTS idx_external_api_errors_created_at
                ON external_api_errors(created_at);
                """,
            )
            self._execute(
                conn,
                """
                CREATE INDEX IF NOT EXISTS idx_external_api_errors_job_item
                ON external_api_errors(job_id, item_key, created_at);
                """,
            )
            self._execute(
                conn,
                """
                CREATE INDEX IF NOT EXISTS idx_api_access_logs_created_at
                ON api_access_logs(created_at);
                """,
            )
            self._execute(
                conn,
                """
                CREATE INDEX IF NOT EXISTS idx_api_access_logs_correlation
                ON api_access_logs(correlation_id, created_at);
                """,
            )
            self._execute(
                conn,
                """
                CREATE INDEX IF NOT EXISTS idx_api_access_logs_user
                ON api_access_logs(user_id, created_at);
                """,
            )
            self._execute(
                conn,
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

            self._seed_default_business_units(conn)

    def _ensure_column(self, conn: Any, table_name: str, column_name: str, column_def: str) -> None:
        if self.is_postgres:
            self._execute(conn, f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {column_def}")
            return

        cols = self._execute(conn, f"PRAGMA table_info({table_name})").fetchall()
        exists = any(str(col["name"]) == column_name for col in cols)
        if exists:
            return
        self._execute(conn, f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")

    @staticmethod
    def _normalize_business_unit_code(value: str | None) -> str:
        return str(value or "").strip().upper()

    def _get_business_unit_row(self, business_unit_code: str, include_inactive: bool = False) -> dict[str, Any] | None:
        safe_code = self._normalize_business_unit_code(business_unit_code)
        if not safe_code:
            return None
        with self._connect() as conn:
            row = self._execute(
                conn,
                """
                SELECT business_unit_code, business_unit_name, is_active, created_at, updated_at
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
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
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
            self._execute(
                conn,
                """
                INSERT INTO jobs(
                  job_id, status, created_at, updated_at, total_items,
                  source_schedule_id, source_upload_id, user_id, user_name
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    status_value,
                    ts,
                    ts,
                    max(int(total_items), 0),
                    (source_schedule_id or "").strip() or None,
                    (source_upload_id or "").strip() or None,
                    (user_id or "").strip() or None,
                    (user_name or "").strip() or None,
                ),
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
        safe_user_id = (user_id or "").strip()
        safe_user_name = (user_name or "").strip()

        with self._connect() as conn:
            if safe_user_id:
                rows = self._execute(
                    conn,
                    """
                    SELECT
                      j.job_id, j.status, j.created_at, j.updated_at, j.total_items,
                      j.source_schedule_id, j.source_upload_id, j.user_id, j.user_name,
                      jm.mode, jm.screening_types_json, jm.mock_screening, jm.batch_name, jm.file_name,
                      jm.daily_screening, jm.schedule_frequency, jm.daily_schedule_id, jm.query_count, jm.deferred_until, jm.business_unit_code,
                      bu.file_name AS upload_file_name, bu.s3_uri AS upload_s3_uri
                    FROM jobs j
                    LEFT JOIN job_metadata jm ON jm.job_id = j.job_id
                    LEFT JOIN batch_file_uploads bu ON bu.upload_id = j.source_upload_id
                    WHERE j.user_id = ?
                    ORDER BY j.created_at DESC
                    LIMIT ?
                    """,
                    (safe_user_id, safe_limit),
                ).fetchall()
            elif safe_user_name:
                rows = self._execute(
                    conn,
                    """
                    SELECT
                      j.job_id, j.status, j.created_at, j.updated_at, j.total_items,
                      j.source_schedule_id, j.source_upload_id, j.user_id, j.user_name,
                      jm.mode, jm.screening_types_json, jm.mock_screening, jm.batch_name, jm.file_name,
                      jm.daily_screening, jm.schedule_frequency, jm.daily_schedule_id, jm.query_count, jm.deferred_until, jm.business_unit_code,
                      bu.file_name AS upload_file_name, bu.s3_uri AS upload_s3_uri
                    FROM jobs j
                    LEFT JOIN job_metadata jm ON jm.job_id = j.job_id
                    LEFT JOIN batch_file_uploads bu ON bu.upload_id = j.source_upload_id
                    WHERE LOWER(COALESCE(j.user_name, '')) = LOWER(?)
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
                      j.job_id, j.status, j.created_at, j.updated_at, j.total_items,
                      j.source_schedule_id, j.source_upload_id, j.user_id, j.user_name,
                      jm.mode, jm.screening_types_json, jm.mock_screening, jm.batch_name, jm.file_name,
                      jm.daily_screening, jm.schedule_frequency, jm.daily_schedule_id, jm.query_count, jm.deferred_until, jm.business_unit_code,
                      bu.file_name AS upload_file_name, bu.s3_uri AS upload_s3_uri
                    FROM jobs j
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
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
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
                    "query_count": int(row["query_count"] or 0) if row["query_count"] is not None else 0,
                    "deferred_until": row["deferred_until"],
                    "business_unit_code": row["business_unit_code"],
                    "upload_file_name": row["upload_file_name"],
                    "upload_s3_uri": row["upload_s3_uri"],
                }
            )
        return out

    def add_job_item(self, job_id: str, item_key: str, request_payload: dict[str, Any]) -> None:
        ts = now_iso()
        with self._connect() as conn:
            self._execute(
                conn,
                """
                INSERT INTO job_items(job_id, item_key, request_json, response_json, status, error_text, updated_at)
                VALUES(?, ?, ?, NULL, ?, NULL, ?)
                """,
                (job_id, item_key, json.dumps(request_payload), JobStatus.queued.value, ts),
            )

    def mark_item_processing(self, job_id: str, item_key: str) -> None:
        ts = now_iso()
        with self._connect() as conn:
            self._execute(
                conn,
                "UPDATE job_items SET status = ?, updated_at = ? WHERE job_id = ? AND item_key = ?",
                (JobStatus.processing.value, ts, job_id, item_key),
            )
            self._execute(
                conn,
                "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ? AND status <> ?",
                (JobStatus.processing.value, ts, job_id, JobStatus.completed.value),
            )

    def mark_item_completed(self, job_id: str, item_key: str, response_payload: dict[str, Any]) -> None:
        ts = now_iso()
        with self._connect() as conn:
            self._execute(
                conn,
                """
                UPDATE job_items
                SET status = ?, response_json = ?, error_text = NULL, updated_at = ?
                WHERE job_id = ? AND item_key = ?
                """,
                (JobStatus.completed.value, json.dumps(response_payload), ts, job_id, item_key),
            )
        self._refresh_job_status(job_id)

    def mark_item_failed(self, job_id: str, item_key: str, error_text: str) -> None:
        ts = now_iso()
        with self._connect() as conn:
            self._execute(
                conn,
                """
                UPDATE job_items
                SET status = ?, response_json = NULL, error_text = ?, updated_at = ?
                WHERE job_id = ? AND item_key = ?
                """,
                (JobStatus.failed.value, error_text[:2000], ts, job_id, item_key),
            )
        self._refresh_job_status(job_id)

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

        with self._connect() as conn:
            self._execute(
                conn,
                "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                (status, now_iso(), job_id),
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
                SELECT item_key, request_json, response_json, status, error_text, updated_at
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
                    "updated_at": row["updated_at"],
                }
            )

        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
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
            cur = self._execute(
                conn,
                """
                UPDATE daily_schedules
                SET
                  batch_name = ?,
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
                    (user_id or "").strip() or None,
                    (user_name or "").strip() or None,
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
                """
                INSERT INTO daily_schedules(
                  schedule_id, batch_name, user_id, user_name, queries_json, screening_types_json, mock_screening,
                  schedule_frequency, timezone, run_hour, run_minute, created_at, last_run_at, next_run_at, is_active,
                  source_upload_id, source_file_name, source_s3_uri, business_unit_code
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, TRUE, ?, ?, ?, ?)
                """,
                (
                    safe_schedule_id,
                    batch_name.strip(),
                    (user_id or "").strip() or None,
                    (user_name or "").strip() or None,
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
    def _parse_daily_schedule_row(row: Any) -> dict[str, Any]:
        business_unit_code = ""
        try:
            business_unit_code = str(row["business_unit_code"] or "").strip()
        except Exception:  # noqa: BLE001
            business_unit_code = ""
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
            "created_at": row["created_at"],
            "last_run_at": row["last_run_at"],
            "next_run_at": row["next_run_at"],
            "is_active": _as_bool(row["is_active"]),
            "source_upload_id": row["source_upload_id"],
            "source_file_name": row["source_file_name"],
            "source_s3_uri": row["source_s3_uri"],
            "business_unit_code": business_unit_code,
        }

    def list_active_daily_schedules(self, user_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if user_id and user_id.strip():
                rows = self._execute(
                    conn,
                    """
                    SELECT
                      schedule_id, batch_name, user_id, user_name, queries_json, screening_types_json, mock_screening,
                      schedule_frequency, timezone, run_hour, run_minute, created_at, last_run_at, next_run_at, is_active,
                      source_upload_id, source_file_name, source_s3_uri, business_unit_code
                    FROM daily_schedules
                    WHERE is_active = TRUE
                      AND user_id = ?
                    ORDER BY created_at DESC
                    """,
                    (user_id.strip(),),
                ).fetchall()
            else:
                rows = self._execute(
                    conn,
                    """
                    SELECT
                      schedule_id, batch_name, user_id, user_name, queries_json, screening_types_json, mock_screening,
                      schedule_frequency, timezone, run_hour, run_minute, created_at, last_run_at, next_run_at, is_active,
                      source_upload_id, source_file_name, source_s3_uri, business_unit_code
                    FROM daily_schedules
                    WHERE is_active = TRUE
                    ORDER BY created_at DESC
                    """,
                ).fetchall()

        return [self._parse_daily_schedule_row(row) for row in rows]

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
            self._execute(
                conn,
                """
                INSERT INTO batch_file_uploads(
                  upload_id, schedule_id, job_id, user_id, user_name, file_name, s3_bucket, s3_key,
                  s3_uri, queries_s3_bucket, queries_s3_key, queries_s3_uri, file_hash, record_count, created_at, is_active
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE)
                """,
                (
                    upload_id,
                    (schedule_id or "").strip() or None,
                    (job_id or "").strip() or None,
                    (user_id or "").strip() or None,
                    (user_name or "").strip() or None,
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

    def update_job_total_items(self, job_id: str, total_items: int) -> None:
        safe_job_id = (job_id or "").strip()
        if not safe_job_id:
            return
        with self._connect() as conn:
            self._execute(
                conn,
                "UPDATE jobs SET total_items = ?, updated_at = ? WHERE job_id = ?",
                (max(int(total_items), 0), now_iso(), safe_job_id),
            )

    def mark_job_failed(self, job_id: str, error_text: str) -> None:
        safe_job_id = (job_id or "").strip()
        if not safe_job_id:
            return
        # Persist a terminal job-level failure without needing to create per-item rows.
        # Set total_items=0 to avoid "pending inferred" counts on the UI.
        with self._connect() as conn:
            self._execute(
                conn,
                "UPDATE jobs SET status = ?, total_items = 0, updated_at = ? WHERE job_id = ?",
                (JobStatus.failed.value, now_iso(), safe_job_id),
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
        if self.is_postgres:
            query = """
                INSERT INTO job_items(job_id, item_key, request_json, response_json, status, error_text, updated_at)
                VALUES(%s, %s, %s, NULL, %s, NULL, %s)
                ON CONFLICT (job_id, item_key) DO NOTHING
                """
        else:
            query = """
                INSERT OR IGNORE INTO job_items(job_id, item_key, request_json, response_json, status, error_text, updated_at)
                VALUES(?, ?, ?, NULL, ?, NULL, ?)
                """

        params = [
            (
                safe_job_id,
                (item_key or "").strip(),
                json.dumps(request_payload),
                JobStatus.queued.value,
                ts,
            )
            for item_key, request_payload in items
            if (item_key or "").strip()
        ]
        if not params:
            return
        with self._connect() as conn:
            cur = conn.cursor()
            cur.executemany(self._sql(query), params)

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
            self._execute(
                conn,
                """
                INSERT INTO schedule_subscriptions(
                  subscription_id, schedule_id, user_id, user_name, email, is_active, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, TRUE, ?, ?)
                ON CONFLICT(schedule_id, email)
                DO UPDATE SET
                  user_id = excluded.user_id,
                  user_name = excluded.user_name,
                  is_active = TRUE,
                  updated_at = excluded.updated_at
                """,
                (
                    subscription_id,
                    safe_schedule_id,
                    (user_id or "").strip() or None,
                    (user_name or "").strip() or None,
                    safe_email,
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
            if user_id and user_id.strip():
                rows = self._execute(
                    conn,
                    """
                    SELECT subscription_id, schedule_id, user_id, user_name, email, is_active, created_at
                    FROM schedule_subscriptions
                    WHERE schedule_id = ?
                      AND user_id = ?
                      AND is_active = TRUE
                    ORDER BY created_at DESC
                    """,
                    (safe_schedule_id, user_id.strip()),
                ).fetchall()
            else:
                rows = self._execute(
                    conn,
                    """
                    SELECT subscription_id, schedule_id, user_id, user_name, email, is_active, created_at
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
                "user_id": row["user_id"],
                "user_name": row["user_name"],
                "email": row["email"],
                "is_active": _as_bool(row["is_active"]),
                "created_at": row["created_at"],
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
            for sub in subs:
                self._execute(
                    conn,
                    """
                    INSERT INTO schedule_notifications(
                      created_at, user_id, user_name, email, schedule_id, job_id, title, message, summary_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        created_at,
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
        safe_user_id = (user_id or "").strip() or None
        safe_email = (email or "").strip().lower() or None

        with self._connect() as conn:
            if safe_user_id and safe_email:
                rows = self._execute(
                    conn,
                    """
                    SELECT notification_id, created_at, user_id, user_name, email, schedule_id, job_id, title, message, summary_json
                    FROM schedule_notifications
                    WHERE user_id = ? OR email = ?
                    ORDER BY notification_id DESC
                    LIMIT ?
                    """,
                    (safe_user_id, safe_email, safe_limit),
                ).fetchall()
            elif safe_user_id:
                rows = self._execute(
                    conn,
                    """
                    SELECT notification_id, created_at, user_id, user_name, email, schedule_id, job_id, title, message, summary_json
                    FROM schedule_notifications
                    WHERE user_id = ?
                    ORDER BY notification_id DESC
                    LIMIT ?
                    """,
                    (safe_user_id, safe_limit),
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
                    "created_at": row["created_at"],
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
        safe_user_id = (user_id or "").strip()
        with self._connect() as conn:
            if safe_user_id:
                rows = self._execute(
                    conn,
                    """
                    SELECT bu.business_unit_code, bu.business_unit_name, bu.is_active, bu.created_at, bu.updated_at
                    FROM business_units bu
                    JOIN user_business_units ubu
                      ON ubu.business_unit_code = bu.business_unit_code
                     AND ubu.user_id = ?
                     AND ubu.is_active = TRUE
                    WHERE (? = TRUE OR bu.is_active = TRUE)
                    ORDER BY bu.business_unit_name ASC, bu.business_unit_code ASC
                    """,
                    (safe_user_id, include_inactive),
                ).fetchall()
            else:
                rows = self._execute(
                    conn,
                    """
                    SELECT business_unit_code, business_unit_name, is_active, created_at, updated_at
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
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
            if str(row["business_unit_code"] or "").strip()
        ]
        if safe_user_id and not results:
            fallback = self._get_business_unit_row(DEFAULT_FALLBACK_BUSINESS_UNIT_CODE, include_inactive=False)
            if fallback:
                return [fallback]
        return results

    def list_user_business_unit_codes(self, user_id: str) -> list[str]:
        safe_user_id = (user_id or "").strip()
        if not safe_user_id:
            return []
        rows = self.list_business_units(user_id=safe_user_id, include_inactive=False)
        return [str(row["business_unit_code"]).strip() for row in rows if str(row.get("business_unit_code") or "").strip()]

    def user_has_business_unit(self, user_id: str | None, business_unit_code: str | None) -> bool:
        safe_user_id = (user_id or "").strip()
        safe_code = self._normalize_business_unit_code(business_unit_code)
        if not safe_user_id or not safe_code:
            return False
        with self._connect() as conn:
            row = self._execute(
                conn,
                """
                SELECT 1
                FROM user_business_units ubu
                JOIN business_units bu
                  ON bu.business_unit_code = ubu.business_unit_code
                WHERE ubu.user_id = ?
                  AND ubu.business_unit_code = ?
                  AND ubu.is_active = TRUE
                  AND bu.is_active = TRUE
                LIMIT 1
                """,
                (safe_user_id, safe_code),
            ).fetchone()
            if row:
                return True

            has_user_mapping = self._execute(
                conn,
                """
                SELECT 1
                FROM user_business_units ubu
                JOIN business_units bu
                  ON bu.business_unit_code = ubu.business_unit_code
                WHERE ubu.user_id = ?
                  AND ubu.is_active = TRUE
                  AND bu.is_active = TRUE
                LIMIT 1
                """,
                (safe_user_id,),
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
        safe_user_id = (user_id or "").strip()
        if not safe_user_id:
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
                """
                DELETE FROM user_business_units
                WHERE user_id = ?
                """,
                (safe_user_id,),
            )

            for code in normalized_codes:
                if code not in valid_codes:
                    continue
                self._execute(
                    conn,
                    """
                    INSERT INTO user_business_units(
                      user_id, user_name, business_unit_code, is_active, created_at, updated_at
                    ) VALUES(?, ?, ?, TRUE, ?, ?)
                    """,
                    (safe_user_id, (user_name or "").strip() or None, code, ts, ts),
                )

        return [code for code in normalized_codes if code in valid_codes]

    def list_user_business_unit_mappings(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = self._execute(
                conn,
                """
                SELECT ubu.user_id, ubu.user_name, ubu.business_unit_code
                FROM user_business_units ubu
                JOIN business_units bu
                  ON bu.business_unit_code = ubu.business_unit_code
                WHERE ubu.is_active = TRUE
                  AND bu.is_active = TRUE
                ORDER BY LOWER(COALESCE(ubu.user_name, ubu.user_id)), ubu.user_id, ubu.business_unit_code
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
                SELECT user_id, user_name
                FROM (
                  SELECT user_id, user_name FROM user_business_units WHERE TRIM(COALESCE(user_id, '')) <> ''
                  UNION ALL
                  SELECT user_id, user_name FROM jobs WHERE TRIM(COALESCE(user_id, '')) <> ''
                  UNION ALL
                  SELECT user_id, user_name FROM daily_schedules WHERE TRIM(COALESCE(user_id, '')) <> ''
                  UNION ALL
                  SELECT user_id, user_name FROM batch_file_uploads WHERE TRIM(COALESCE(user_id, '')) <> ''
                  UNION ALL
                  SELECT user_id, user_name FROM api_access_logs WHERE TRIM(COALESCE(user_id, '')) <> ''
                  UNION ALL
                  SELECT user_id, user_name FROM audit_events WHERE TRIM(COALESCE(user_id, '')) <> ''
                ) known_users
                """,
            ).fetchall()

        merged: dict[str, str] = {}
        for row in rows:
            user_id = str(row["user_id"] or "").strip()
            if not user_id:
                continue
            user_name = str(row["user_name"] or "").strip()
            existing = merged.get(user_id, "")
            if not existing:
                merged[user_id] = user_name or user_id
                continue
            if _is_technical_identifier(existing) and user_name and not _is_technical_identifier(user_name):
                merged[user_id] = user_name

        return [
            {"user_id": user_id, "display_name": (display_name or user_id)}
            for user_id, display_name in sorted(
                merged.items(),
                key=lambda item: (str(item[1] or item[0]).lower(), str(item[0]).lower()),
            )
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
            if self.is_postgres:
                cur = self._execute(
                    conn,
                    """
                    INSERT INTO audit_events(
                      created_at, user_id, user_name, action, entity_type, entity_id, details_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    RETURNING event_id
                    """,
                    (
                        created_at,
                        (user_id or "").strip() or None,
                        (user_name or "").strip() or None,
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
                """
                INSERT INTO audit_events(
                  created_at, user_id, user_name, action, entity_type, entity_id, details_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    (user_id or "").strip() or None,
                    (user_name or "").strip() or None,
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
            if self.is_postgres:
                cur = self._execute(
                    conn,
                    """
                    INSERT INTO external_api_errors(
                      created_at, provider, operation, endpoint, status_code,
                      user_id, user_name, job_id, item_key, error_text, details_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING error_id
                    """,
                    (
                        created_at,
                        safe_provider,
                        (operation or "").strip() or None,
                        (endpoint or "").strip() or None,
                        safe_status,
                        (user_id or "").strip() or None,
                        (user_name or "").strip() or None,
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
                """
                INSERT INTO external_api_errors(
                  created_at, provider, operation, endpoint, status_code,
                  user_id, user_name, job_id, item_key, error_text, details_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    safe_provider,
                    (operation or "").strip() or None,
                    (endpoint or "").strip() or None,
                    safe_status,
                    (user_id or "").strip() or None,
                    (user_name or "").strip() or None,
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
            if self.is_postgres:
                cur = self._execute(
                    conn,
                    """
                    INSERT INTO api_access_logs(
                      created_at, correlation_id, request_method, request_path, query_string,
                      status_code, duration_ms, client_ip, user_agent, user_id, user_name, auth_state, details_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        (user_id or "").strip() or None,
                        (user_name or "").strip() or None,
                        (auth_state or "").strip() or None,
                        json.dumps(details or {}),
                    ),
                )
                row = cur.fetchone()
                return int(row["access_id"]) if row else 0

            cur = self._execute(
                conn,
                """
                INSERT INTO api_access_logs(
                  created_at, correlation_id, request_method, request_path, query_string,
                  status_code, duration_ms, client_ip, user_agent, user_id, user_name, auth_state, details_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    (user_id or "").strip() or None,
                    (user_name or "").strip() or None,
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

    def list_audit_events(self, limit: int = 200, user_id: str | None = None, offset: int = 0) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 1000)
        safe_offset = max(int(offset), 0)
        with self._connect() as conn:
            if user_id and user_id.strip():
                rows = self._execute(
                    conn,
                    """
                    SELECT event_id, created_at, user_id, user_name, action, entity_type, entity_id, details_json
                    FROM audit_events
                    WHERE user_id = ?
                    ORDER BY event_id DESC
                    LIMIT ?
                    OFFSET ?
                    """,
                    (user_id.strip(), safe_limit, safe_offset),
                ).fetchall()
            else:
                rows = self._execute(
                    conn,
                    """
                    SELECT event_id, created_at, user_id, user_name, action, entity_type, entity_id, details_json
                    FROM audit_events
                    ORDER BY event_id DESC
                    LIMIT ?
                    OFFSET ?
                    """,
                    (safe_limit, safe_offset),
                ).fetchall()

            missing_name_user_ids = sorted(
                {
                    str(row["user_id"]).strip()
                    for row in rows
                    if row["user_id"] and _is_technical_identifier(row["user_name"])
                }
            )
            user_name_fallback: dict[str, str] = {}
            if missing_name_user_ids:
                placeholders = ", ".join("?" for _ in missing_name_user_ids)
                lookup_rows = self._execute(
                    conn,
                    f"""
                    SELECT user_id, user_name, event_id
                    FROM audit_events
                    WHERE user_id IN ({placeholders})
                      AND user_name IS NOT NULL
                      AND TRIM(user_name) <> ''
                    ORDER BY event_id DESC
                    """,
                    tuple(missing_name_user_ids),
                ).fetchall()
                for lookup in lookup_rows:
                    fallback_user_id = str(lookup["user_id"] or "").strip()
                    fallback_user_name = str(lookup["user_name"] or "").strip()
                    if not fallback_user_id or _is_technical_identifier(fallback_user_name):
                        continue
                    if fallback_user_id not in user_name_fallback:
                        user_name_fallback[fallback_user_id] = fallback_user_name

        events: list[dict[str, Any]] = []
        for row in rows:
            resolved_user_id = row["user_id"]
            resolved_user_name = row["user_name"]
            if resolved_user_id and _is_technical_identifier(resolved_user_name):
                resolved_user_name = user_name_fallback.get(str(resolved_user_id).strip()) or None
            events.append(
                {
                    "event_id": int(row["event_id"]),
                    "created_at": row["created_at"],
                    "user_id": resolved_user_id,
                    "user_name": resolved_user_name,
                    "action": row["action"],
                    "entity_type": row["entity_type"],
                    "entity_id": row["entity_id"],
                    "details": json.loads(row["details_json"]) if row["details_json"] else {},
                }
            )
        return events

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
