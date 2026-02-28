from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import JobStatus, now_iso

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - optional dependency for local sqlite mode
    psycopg = None
    dict_row = None


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
                  total_items INTEGER NOT NULL
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
                  timezone TEXT NOT NULL,
                  run_hour INTEGER NOT NULL,
                  run_minute INTEGER NOT NULL,
                  created_at TEXT NOT NULL,
                  last_run_at TEXT,
                  next_run_at TEXT NOT NULL,
                  is_active BOOLEAN NOT NULL DEFAULT TRUE
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

            self._ensure_column(conn, "daily_schedules", "user_id", "TEXT")
            self._ensure_column(conn, "daily_schedules", "user_name", "TEXT")

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
    def compute_next_run_at(
        now_utc: datetime,
        timezone_name: str,
        run_hour: int,
        run_minute: int,
    ) -> str:
        tz_name = timezone_name.strip() or "America/New_York"
        safe_hour = min(max(int(run_hour), 0), 23)
        safe_minute = min(max(int(run_minute), 0), 59)

        try:
            local_tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            local_tz = ZoneInfo("America/New_York")
        local_now = now_utc.astimezone(local_tz)
        local_target = local_now.replace(hour=safe_hour, minute=safe_minute, second=0, microsecond=0)
        if local_now >= local_target:
            local_target = local_target + timedelta(days=1)
        return local_target.astimezone(timezone.utc).isoformat()

    def create_job(self, job_id: str, total_items: int) -> str:
        ts = now_iso()
        with self._connect() as conn:
            self._execute(
                conn,
                "INSERT INTO jobs(job_id, status, created_at, updated_at, total_items) VALUES(?, ?, ?, ?, ?)",
                (job_id, JobStatus.queued.value, ts, ts, total_items),
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
                "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                (JobStatus.processing.value, ts, job_id),
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

        if pending > 0 or processing > 0:
            status = JobStatus.processing.value
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
                "SELECT job_id, status, created_at, updated_at, total_items FROM jobs WHERE job_id = ?",
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
            "total_items": job["total_items"],
            "counts": counts,
            "items": parsed_items,
        }

    def create_daily_schedule(
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
    ) -> str:
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        next_run_at = self.compute_next_run_at(now, timezone_name, run_hour, run_minute)
        with self._connect() as conn:
            self._execute(
                conn,
                """
                INSERT INTO daily_schedules(
                  schedule_id, batch_name, user_id, user_name, queries_json, screening_types_json, mock_screening,
                  timezone, run_hour, run_minute, created_at, last_run_at, next_run_at, is_active
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, TRUE)
                """,
                (
                    schedule_id,
                    batch_name,
                    (user_id or "").strip() or None,
                    (user_name or "").strip() or None,
                    json.dumps(queries),
                    json.dumps(screening_types),
                    bool(mock_screening),
                    timezone_name,
                    run_hour,
                    run_minute,
                    created_at,
                    next_run_at,
                ),
            )
        return schedule_id

    def list_due_daily_schedules(self, now_iso_utc: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = self._execute(
                conn,
                """
                SELECT
                  schedule_id, batch_name, user_id, user_name, queries_json, screening_types_json, mock_screening,
                  timezone, run_hour, run_minute, created_at, last_run_at, next_run_at, is_active
                FROM daily_schedules
                WHERE is_active = TRUE
                  AND next_run_at <= ?
                ORDER BY next_run_at ASC
                """,
                (now_iso_utc,),
            ).fetchall()

        schedules: list[dict[str, Any]] = []
        for row in rows:
            schedules.append(self._parse_daily_schedule_row(row))
        return schedules

    @staticmethod
    def _parse_daily_schedule_row(row: Any) -> dict[str, Any]:
        return {
            "schedule_id": row["schedule_id"],
            "batch_name": row["batch_name"],
            "user_id": row["user_id"],
            "user_name": row["user_name"],
            "queries": json.loads(row["queries_json"]) if row["queries_json"] else {},
            "screening_types": json.loads(row["screening_types_json"]) if row["screening_types_json"] else [],
            "mock_screening": bool(row["mock_screening"]),
            "timezone": row["timezone"],
            "run_hour": int(row["run_hour"]),
            "run_minute": int(row["run_minute"]),
            "created_at": row["created_at"],
            "last_run_at": row["last_run_at"],
            "next_run_at": row["next_run_at"],
            "is_active": bool(row["is_active"]),
        }

    def list_active_daily_schedules(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = self._execute(
                conn,
                """
                SELECT
                  schedule_id, batch_name, user_id, user_name, queries_json, screening_types_json, mock_screening,
                  timezone, run_hour, run_minute, created_at, last_run_at, next_run_at, is_active
                FROM daily_schedules
                WHERE is_active = TRUE
                ORDER BY created_at DESC
                """,
            ).fetchall()

        schedules: list[dict[str, Any]] = []
        for row in rows:
            schedules.append(self._parse_daily_schedule_row(row))
        return schedules

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
                    if row["user_id"] and not str(row["user_name"] or "").strip()
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
                    if not fallback_user_id or not fallback_user_name:
                        continue
                    if fallback_user_id not in user_name_fallback:
                        user_name_fallback[fallback_user_id] = fallback_user_name

        events: list[dict[str, Any]] = []
        for row in rows:
            resolved_user_id = row["user_id"]
            resolved_user_name = row["user_name"]
            if resolved_user_id and not str(resolved_user_name or "").strip():
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
