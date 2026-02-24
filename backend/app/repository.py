from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import JobStatus, now_iso


class JobRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._ensure_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_db(self) -> None:
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                  job_id TEXT PRIMARY KEY,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  total_items INTEGER NOT NULL
                );
                """
            )
            conn.execute(
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
                """
            )
            conn.commit()

    def create_job(self, job_id: str, total_items: int) -> str:
        ts = now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs(job_id, status, created_at, updated_at, total_items) VALUES(?, ?, ?, ?, ?)",
                (job_id, JobStatus.queued.value, ts, ts, total_items),
            )
            conn.commit()
        return ts

    def add_job_item(self, job_id: str, item_key: str, request_payload: dict[str, Any]) -> None:
        ts = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO job_items(job_id, item_key, request_json, response_json, status, error_text, updated_at)
                VALUES(?, ?, ?, NULL, ?, NULL, ?)
                """,
                (job_id, item_key, json.dumps(request_payload), JobStatus.queued.value, ts),
            )
            conn.commit()

    def mark_item_processing(self, job_id: str, item_key: str) -> None:
        ts = now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE job_items SET status = ?, updated_at = ? WHERE job_id = ? AND item_key = ?",
                (JobStatus.processing.value, ts, job_id, item_key),
            )
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                (JobStatus.processing.value, ts, job_id),
            )
            conn.commit()

    def mark_item_completed(self, job_id: str, item_key: str, response_payload: dict[str, Any]) -> None:
        ts = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE job_items
                SET status = ?, response_json = ?, error_text = NULL, updated_at = ?
                WHERE job_id = ? AND item_key = ?
                """,
                (JobStatus.completed.value, json.dumps(response_payload), ts, job_id, item_key),
            )
            conn.commit()
        self._refresh_job_status(job_id)

    def mark_item_failed(self, job_id: str, item_key: str, error_text: str) -> None:
        ts = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE job_items
                SET status = ?, response_json = NULL, error_text = ?, updated_at = ?
                WHERE job_id = ? AND item_key = ?
                """,
                (JobStatus.failed.value, error_text[:2000], ts, job_id, item_key),
            )
            conn.commit()
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
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                (status, now_iso(), job_id),
            )
            conn.commit()

    def get_job_snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            job = conn.execute(
                "SELECT job_id, status, created_at, updated_at, total_items FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if not job:
                return None

            items = conn.execute(
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

