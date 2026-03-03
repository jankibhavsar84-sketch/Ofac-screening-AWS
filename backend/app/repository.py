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

            self._ensure_column(conn, "jobs", "source_schedule_id", "TEXT")
            self._ensure_column(conn, "jobs", "source_upload_id", "TEXT")
            self._ensure_column(conn, "jobs", "user_id", "TEXT")
            self._ensure_column(conn, "jobs", "user_name", "TEXT")

            self._ensure_column(conn, "daily_schedules", "user_id", "TEXT")
            self._ensure_column(conn, "daily_schedules", "user_name", "TEXT")
            self._ensure_column(conn, "daily_schedules", "schedule_frequency", "TEXT NOT NULL DEFAULT 'DAILY'")
            self._ensure_column(conn, "daily_schedules", "source_upload_id", "TEXT")
            self._ensure_column(conn, "daily_schedules", "source_file_name", "TEXT")
            self._ensure_column(conn, "daily_schedules", "source_s3_uri", "TEXT")

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
                  source_upload_id, source_file_name, source_s3_uri
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, TRUE, ?, ?, ?)
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
        schedule_frequency: str | None = None,
        batch_name: str | None = None,
    ) -> bool:
        safe_schedule_id = (schedule_id or "").strip()
        if not safe_schedule_id:
            return False

        safe_frequency = self.normalize_schedule_frequency(schedule_frequency) if schedule_frequency else None

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
                  source_upload_id, source_file_name, source_s3_uri
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
                  source_upload_id, source_file_name, source_s3_uri
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
                      source_upload_id, source_file_name, source_s3_uri
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
                      source_upload_id, source_file_name, source_s3_uri
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
                  s3_uri, file_hash, record_count, created_at, is_active
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE)
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
                    (file_hash or "").strip() or None,
                    max(int(record_count), 0),
                    created_at,
                ),
            )
        return upload_id

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

        return {
            "job_id": snapshot["job_id"],
            "status": snapshot["status"],
            "total_items": snapshot["total_items"],
            "completed_items": snapshot["counts"]["completed"],
            "failed_items": snapshot["counts"]["failed"],
            "pending_items": snapshot["counts"]["pending"],
            "processing_items": snapshot["counts"]["processing"],
            "matched_items": matched_items,
            "clear_items": max(int(snapshot["counts"]["completed"]) - matched_items, 0),
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
        title = f"Scheduled screening completed: {batch_name}"
        message = (
            f"Job {job_id} completed. "
            f"Total {summary['total_items']}, matches {summary['matched_items']}, "
            f"clear {summary['clear_items']}, failed {summary['failed_items']}."
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

    def list_audit_events(self, limit: int = 200, user_id: str | None = None) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 1000)
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
                    """,
                    (user_id.strip(), safe_limit),
                ).fetchall()
            else:
                rows = self._execute(
                    conn,
                    """
                    SELECT event_id, created_at, user_id, user_name, action, entity_type, entity_id, details_json
                    FROM audit_events
                    ORDER BY event_id DESC
                    LIMIT ?
                    """,
                    (safe_limit,),
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
