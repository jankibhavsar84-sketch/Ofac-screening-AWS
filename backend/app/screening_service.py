from __future__ import annotations

from typing import Any
from uuid import uuid4

from .config import settings
from .models import (
    AuditEvent,
    DailyScheduleInfo,
    EntityMatchResponse,
    EntityMatches,
    JobStatus,
    MatchJobAccepted,
    MatchJobProgress,
    MatchJobRequest,
    ScheduleSubscription,
    ScreeningQueueMessage,
    UserNotification,
)
from .queue import SqsQueue
from .repository import JobRepository


class ScreeningService:
    def __init__(self, repository: JobRepository, queue: SqsQueue) -> None:
        self.repository = repository
        self.queue = queue

    def submit_job(self, payload: MatchJobRequest) -> MatchJobAccepted:
        if not payload.queries:
            raise ValueError("At least one query is required")
        if payload.daily_screening and not (payload.batch_name and payload.batch_name.strip()):
            raise ValueError("batch_name is required when daily_screening is enabled")

        daily_schedule_id: str | None = None
        scheduled_next_run_at: str | None = None
        source_schedule_id = (payload.schedule_id or "").strip() or None
        schedule_frequency = self.repository.normalize_schedule_frequency(payload.schedule_frequency)
        source_upload_id = (payload.source_upload_id or "").strip() or None
        base_queries = {k: v.model_dump(mode="json") for k, v in payload.queries.items()}
        inferred_mode = (
            "BATCH"
            if payload.daily_screening
            or source_upload_id
            or source_schedule_id
            or (payload.batch_name and payload.batch_name.strip())
            else "SINGLE"
        )

        if payload.daily_screening:
            schedule_id = source_schedule_id or str(uuid4())
            daily_schedule_id, created = self.repository.create_or_update_daily_schedule(
                schedule_id=schedule_id,
                batch_name=payload.batch_name.strip(),
                user_id=payload.user_id,
                user_name=payload.user_name,
                queries=base_queries,
                screening_types=payload.screening_types,
                mock_screening=payload.mock_screening,
                timezone_name=settings.daily_screening_timezone,
                run_hour=settings.daily_screening_hour,
                run_minute=settings.daily_screening_minute,
                schedule_frequency=schedule_frequency,
                schedule_run_at=payload.schedule_run_at,
                source_upload_id=source_upload_id,
            )
            source_schedule_id = daily_schedule_id
            schedule_snapshot = self.repository.get_daily_schedule(daily_schedule_id)
            scheduled_next_run_at = (schedule_snapshot or {}).get("next_run_at")
            self.repository.add_audit_event(
                action="DAILY_SCHEDULE_CREATED" if created else "DAILY_SCHEDULE_UPDATED",
                user_id=payload.user_id,
                user_name=payload.user_name,
                entity_type="daily_schedule",
                entity_id=daily_schedule_id,
                details={
                    "batch_name": payload.batch_name,
                    "total_items": len(base_queries),
                    "screening_types": payload.screening_types,
                    "schedule_frequency": schedule_frequency,
                    "timezone": settings.daily_screening_timezone,
                    "run_hour": settings.daily_screening_hour,
                    "run_minute": settings.daily_screening_minute,
                    "schedule_run_at": payload.schedule_run_at,
                    "next_run_at": scheduled_next_run_at,
                },
            )
        elif source_schedule_id:
            schedule_snapshot = self.repository.get_daily_schedule(source_schedule_id)
            if schedule_snapshot:
                schedule_frequency = self.repository.normalize_schedule_frequency(schedule_snapshot.get("schedule_frequency"))

        # Daily schedule setup should not execute immediately; worker triggers at next_run_at.
        if payload.daily_screening and source_schedule_id:
            job_id = str(uuid4())
            submitted_at = self.repository.create_job(
                job_id=job_id,
                total_items=0,
                status=JobStatus.completed,
                source_schedule_id=source_schedule_id,
                source_upload_id=source_upload_id,
                user_id=payload.user_id,
                user_name=payload.user_name,
            )
            self.repository.upsert_job_metadata(
                job_id=job_id,
                mode="BATCH",
                screening_types=payload.screening_types,
                mock_screening=payload.mock_screening,
                batch_name=payload.batch_name,
                daily_screening=True,
                schedule_frequency=schedule_frequency,
                daily_schedule_id=source_schedule_id,
                query_count=len(base_queries),
                deferred_until=scheduled_next_run_at,
            )
            self.repository.add_audit_event(
                action="SCREENING_JOB_DEFERRED_UNTIL_SCHEDULE_TIME",
                user_id=payload.user_id,
                user_name=payload.user_name,
                entity_type="screening_job",
                entity_id=job_id,
                details={
                    "source_schedule_id": source_schedule_id,
                    "batch_name": payload.batch_name,
                    "total_items": 0,
                    "schedule_frequency": schedule_frequency,
                    "schedule_run_at": payload.schedule_run_at,
                    "next_run_at": scheduled_next_run_at,
                },
            )
            return MatchJobAccepted(
                job_id=job_id,
                status=JobStatus.completed,
                submitted_at=submitted_at,
                total_items=0,
                daily_schedule_id=daily_schedule_id,
                screened_item_keys=[],
            )

        queries_for_job = base_queries
        record_hashes: dict[str, str] = {
            item_key: self.repository.hash_query_payload(query_payload) for item_key, query_payload in base_queries.items()
        }
        skipped_existing_records = 0
        if source_schedule_id:
            queries_for_job, record_hashes, skipped_existing_records = self.repository.filter_unscreened_schedule_queries(
                source_schedule_id,
                base_queries,
            )

        if not queries_for_job:
            job_id = str(uuid4())
            submitted_at = self.repository.create_job(
                job_id=job_id,
                total_items=0,
                status=JobStatus.completed,
                source_schedule_id=source_schedule_id,
                source_upload_id=source_upload_id,
                user_id=payload.user_id,
                user_name=payload.user_name,
            )
            self.repository.upsert_job_metadata(
                job_id=job_id,
                mode=inferred_mode,
                screening_types=payload.screening_types,
                mock_screening=payload.mock_screening,
                batch_name=payload.batch_name,
                daily_screening=bool(payload.daily_screening or source_schedule_id),
                schedule_frequency=schedule_frequency if (payload.daily_screening or source_schedule_id) else None,
                daily_schedule_id=source_schedule_id,
                query_count=len(base_queries),
            )
            self.repository.add_audit_event(
                action="SCREENING_JOB_SKIPPED_NO_NEW_RECORDS",
                user_id=payload.user_id,
                user_name=payload.user_name,
                entity_type="screening_job",
                entity_id=job_id,
                details={
                    "source_schedule_id": source_schedule_id,
                    "total_items": 0,
                    "skipped_existing_records": skipped_existing_records,
                },
            )
            return MatchJobAccepted(
                job_id=job_id,
                status=JobStatus.completed,
                submitted_at=submitted_at,
                total_items=0,
                daily_schedule_id=daily_schedule_id,
                screened_item_keys=[],
            )

        job_id = str(uuid4())
        submitted_at = self.repository.create_job(
            job_id=job_id,
            total_items=len(queries_for_job),
            source_schedule_id=source_schedule_id,
            source_upload_id=source_upload_id,
            user_id=payload.user_id,
            user_name=payload.user_name,
        )
        self.repository.upsert_job_metadata(
            job_id=job_id,
            mode=inferred_mode,
            screening_types=payload.screening_types,
            mock_screening=payload.mock_screening,
            batch_name=payload.batch_name,
            daily_screening=bool(payload.daily_screening or source_schedule_id),
            schedule_frequency=schedule_frequency if (payload.daily_screening or source_schedule_id) else None,
            daily_schedule_id=source_schedule_id,
            query_count=len(base_queries),
        )

        for item_key, query_payload in queries_for_job.items():
            query = payload.queries[item_key]
            self.repository.add_job_item(job_id=job_id, item_key=item_key, request_payload=query_payload)
            self.queue.enqueue(
                ScreeningQueueMessage(
                    job_id=job_id,
                    item_key=item_key,
                    query=query,
                    submitted_at=submitted_at,
                    screening_types=payload.screening_types,
                    mock_screening=payload.mock_screening,
                    user_id=payload.user_id,
                    user_name=payload.user_name,
                    source_schedule_id=source_schedule_id,
                    source_record_hash=record_hashes.get(item_key),
                )
            )

        self.repository.add_audit_event(
            action="SCREENING_JOB_SUBMITTED",
            user_id=payload.user_id,
            user_name=payload.user_name,
            entity_type="screening_job",
            entity_id=job_id,
            details={
                "total_items": len(queries_for_job),
                "screening_types": payload.screening_types,
                "daily_screening": payload.daily_screening,
                "batch_name": payload.batch_name,
                "mock_screening": payload.mock_screening,
                "source_schedule_id": source_schedule_id,
                "source_upload_id": source_upload_id,
                "skipped_existing_records": skipped_existing_records,
            },
        )

        return MatchJobAccepted(
            job_id=job_id,
            status=JobStatus.queued,
            submitted_at=submitted_at,
            total_items=len(queries_for_job),
            daily_schedule_id=daily_schedule_id,
            screened_item_keys=list(queries_for_job.keys()),
        )

    def get_progress(self, job_id: str) -> MatchJobProgress | None:
        snapshot = self.repository.get_job_snapshot(job_id)
        if not snapshot:
            return None

        status_raw = snapshot["status"]
        status = JobStatus(status_raw) if status_raw in JobStatus._value2member_map_ else JobStatus.processing

        progress = MatchJobProgress(
            job_id=snapshot["job_id"],
            status=status,
            submitted_at=snapshot["created_at"],
            total_items=snapshot["total_items"],
            completed_items=snapshot["counts"]["completed"],
            failed_items=snapshot["counts"]["failed"],
            pending_items=snapshot["counts"]["pending"],
            processing_items=snapshot["counts"]["processing"],
        )

        is_terminal = progress.pending_items == 0 and progress.processing_items == 0
        if is_terminal:
            responses: dict[str, EntityMatches] = {}
            for item in snapshot["items"]:
                item_key = item["item_key"]
                if item["response"]:
                    responses[item_key] = EntityMatches.model_validate(item["response"])
                else:
                    # Keep response shape stable for frontend; failed items are surfaced with status=500.
                    responses[item_key] = EntityMatches.model_validate(
                        {
                            "results": [],
                            "total": {"value": 0, "relation": "eq"},
                            "query": item["request"],
                            "status": 500,
                        }
                    )

            progress.status = JobStatus.completed if (progress.completed_items > 0 or progress.total_items == 0) else JobStatus.failed
            progress.responses = responses
            progress.limit = settings.screening_result_limit

        return progress

    def get_terminal_match_response(self, progress: MatchJobProgress) -> EntityMatchResponse:
        if not progress.responses:
            raise ValueError("Job not finished")
        return EntityMatchResponse(responses=progress.responses, limit=progress.limit or settings.screening_result_limit)

    @staticmethod
    def _parse_screening_types(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            try:
                import json

                decoded = json.loads(raw)
                if isinstance(decoded, list):
                    return [str(v).strip() for v in decoded if str(v).strip()]
            except Exception:  # noqa: BLE001
                return []
        return []

    @staticmethod
    def _query_to_ui_type(query: dict[str, Any] | None) -> str:
        schema = str((query or {}).get("schema") or "").strip().lower()
        if schema in {"person", "individual"}:
            return "Individual"
        if schema == "unknown":
            return "Unknown"
        if schema == "vessel":
            return "Vessel"
        if schema == "aircraft":
            return "Aircraft"
        return "Organization"

    @staticmethod
    def _display_name_from_query(query: dict[str, Any] | None, fallback: str) -> str:
        props = (query or {}).get("properties")
        if isinstance(props, dict):
            names = props.get("name")
            if isinstance(names, list):
                for value in names:
                    safe = str(value or "").strip()
                    if safe:
                        return safe
            if isinstance(names, str) and names.strip():
                return names.strip()
        safe_fallback = str(fallback or "").strip()
        return safe_fallback or "Unknown"

    @staticmethod
    def _classify_result_from_matches(matches: dict[str, Any]) -> str:
        results = matches.get("results", []) if isinstance(matches, dict) else []
        if not isinstance(results, list):
            return "NO_HIT"
        for result in results:
            if isinstance(result, dict) and bool(result.get("match")):
                return "HIT"
        return "NO_HIT"

    def list_user_submissions(self, user_id: str | None, user_name: str | None, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.repository.list_jobs_for_history(user_id=user_id, user_name=user_name, limit=limit)
        active_schedule_ids = {
            str(s.get("schedule_id", "")).strip()
            for s in self.repository.list_active_daily_schedules(user_id=user_id)
            if str(s.get("schedule_id", "")).strip()
        }

        submissions: list[dict[str, Any]] = []
        for row in rows:
            job_id = str(row.get("job_id") or "").strip()
            if not job_id:
                continue
            snapshot = self.repository.get_job_snapshot(job_id)
            if not snapshot:
                continue

            mode_raw = str(row.get("mode") or "").strip().upper()
            inferred_mode = (
                "BATCH"
                if row.get("source_upload_id") or row.get("source_schedule_id") or int(snapshot.get("total_items") or 0) > 1
                else "SINGLE"
            )
            mode = mode_raw if mode_raw in {"SINGLE", "BATCH"} else inferred_mode

            screening_types = self._parse_screening_types(row.get("screening_types_json"))
            daily_schedule_id = (row.get("daily_schedule_id") or row.get("source_schedule_id") or "").strip() or None
            daily_schedule_active = bool(daily_schedule_id and daily_schedule_id in active_schedule_ids)

            if mode == "SINGLE":
                meta: list[dict[str, str]] = []
                responses: dict[str, dict[str, Any]] = {}
                any_hit = False
                any_error = False
                any_processing = False

                for item in snapshot.get("items", []):
                    item_key = str(item.get("item_key") or "").strip()
                    if not item_key:
                        continue

                    request_payload = item.get("request") if isinstance(item.get("request"), dict) else {}
                    ui_type = self._query_to_ui_type(request_payload)
                    display_name = self._display_name_from_query(request_payload, item_key)
                    status = str(item.get("status") or "").strip().upper()
                    response_payload = item.get("response") if isinstance(item.get("response"), dict) else None

                    if status in {JobStatus.queued.value, JobStatus.processing.value}:
                        any_processing = True
                        matches = {
                            "results": [],
                            "total": {"value": 0, "relation": "eq"},
                            "query": request_payload,
                            "status": 202,
                        }
                    elif status == JobStatus.failed.value or response_payload is None:
                        any_error = True
                        matches = {
                            "results": [],
                            "total": {"value": 0, "relation": "eq"},
                            "query": request_payload,
                            "status": 500,
                        }
                    else:
                        matches = response_payload
                        if self._classify_result_from_matches(matches) == "HIT":
                            any_hit = True

                    meta.append({"key": item_key, "uiType": ui_type, "displayName": display_name})
                    responses[item_key] = matches

                overall = "PROCESSING" if any_processing else "HIT" if any_hit else "ERROR" if any_error else "NO_HIT"
                submissions.append(
                    {
                        "id": job_id,
                        "createdAt": snapshot.get("created_at"),
                        "mode": "SINGLE",
                        "createdByUserId": snapshot.get("user_id"),
                        "createdByUserName": snapshot.get("user_name"),
                        "customerType": "Person",
                        "displayName": f"Single Screening ({len(meta)})",
                        "result": overall,
                        "screeningTypes": screening_types,
                        "details": {
                            "meta": meta,
                            "responses": responses,
                            "screeningTypes": screening_types,
                            "mockScreening": bool(row.get("mock_screening")),
                        },
                    }
                )
                continue

            batch_items: list[dict[str, Any]] = []
            has_hit = False
            has_error = False
            has_processing = False

            for item in snapshot.get("items", []):
                request_payload = item.get("request") if isinstance(item.get("request"), dict) else {}
                item_key = str(item.get("item_key") or "").strip() or "item"
                ui_type = self._query_to_ui_type(request_payload)
                display_name = self._display_name_from_query(request_payload, item_key)
                status = str(item.get("status") or "").strip().upper()
                response_payload = item.get("response") if isinstance(item.get("response"), dict) else None

                if status in {JobStatus.queued.value, JobStatus.processing.value}:
                    result = "PROCESSING"
                    message = "Screening in progress"
                    matches = {
                        "results": [],
                        "total": {"value": 0, "relation": "eq"},
                        "query": request_payload,
                        "status": 202,
                    }
                    has_processing = True
                elif status == JobStatus.failed.value or response_payload is None:
                    result = "ERROR"
                    message = str(item.get("error_text") or "Screening failed for this row")
                    matches = {
                        "results": [],
                        "total": {"value": 0, "relation": "eq"},
                        "query": request_payload,
                        "status": 500,
                    }
                    has_error = True
                else:
                    matches = response_payload
                    result = self._classify_result_from_matches(matches)
                    if result == "HIT":
                        has_hit = True
                        top_caption = ""
                        results = matches.get("results", []) if isinstance(matches, dict) else []
                        if isinstance(results, list) and results:
                            first = results[0]
                            if isinstance(first, dict):
                                top_caption = str(first.get("caption") or "").strip()
                        message = f"Top match: {top_caption}" if top_caption else None
                    else:
                        message = None

                batch_items.append(
                    {
                        "customerType": "Person" if ui_type == "Individual" else "Entity",
                        "displayName": display_name,
                        "result": result,
                        "message": message,
                        "details": {"uiType": ui_type, "matches": matches},
                    }
                )

            deferred_until = str(row.get("deferred_until") or "").strip()
            if not batch_items:
                placeholder_name = (
                    str(row.get("batch_name") or "").strip()
                    or str(row.get("file_name") or "").strip()
                    or str(row.get("upload_file_name") or "").strip()
                    or "Scheduled Screening"
                )
                placeholder_result = "PROCESSING" if deferred_until else "NO_HIT"
                placeholder_message = (
                    "Scheduled. Screening will start at the configured run time."
                    if deferred_until
                    else "No new records to screen."
                )
                has_processing = placeholder_result == "PROCESSING"
                batch_items.append(
                    {
                        "customerType": "Entity",
                        "displayName": placeholder_name,
                        "result": placeholder_result,
                        "message": placeholder_message,
                        "details": {
                            "uiType": "Organization",
                            "matches": {
                                "results": [],
                                "total": {"value": 0, "relation": "eq"},
                                "query": {"schema": "Company", "properties": {"name": [placeholder_name]}},
                                "status": 202 if placeholder_result == "PROCESSING" else 204,
                            },
                        },
                    }
                )

            overall = "PROCESSING" if has_processing else "HIT" if has_hit else "ERROR" if has_error else "NO_HIT"
            file_name = (
                str(row.get("file_name") or "").strip()
                or str(row.get("upload_file_name") or "").strip()
                or str(row.get("batch_name") or "").strip()
                or "Batch Submission"
            )
            submissions.append(
                {
                    "id": job_id,
                    "createdAt": snapshot.get("created_at"),
                    "mode": "BATCH",
                    "createdByUserId": snapshot.get("user_id"),
                    "createdByUserName": snapshot.get("user_name"),
                    "jobId": job_id,
                    "fileName": file_name,
                    "overallResult": overall,
                    "screeningTypes": screening_types,
                    "dailyScreening": bool(row.get("daily_screening") or daily_schedule_id),
                    "scheduleFrequency": row.get("schedule_frequency"),
                    "dailyScheduleId": daily_schedule_id,
                    "dailyScheduleActive": daily_schedule_active,
                    "sourceUploadId": row.get("source_upload_id"),
                    "sourceS3Uri": row.get("upload_s3_uri"),
                    "items": batch_items,
                }
            )

        return submissions

    def list_daily_schedules(self) -> list[DailyScheduleInfo]:
        schedules = self.repository.list_active_daily_schedules()
        return [
            DailyScheduleInfo(
                schedule_id=s["schedule_id"],
                batch_name=s["batch_name"],
                user_id=s.get("user_id"),
                user_name=s.get("user_name"),
                screening_types=s["screening_types"] if isinstance(s["screening_types"], list) else [],
                schedule_frequency=s.get("schedule_frequency", "DAILY"),
                timezone=s["timezone"],
                run_hour=int(s["run_hour"]),
                run_minute=int(s["run_minute"]),
                created_at=s["created_at"],
                last_run_at=s["last_run_at"],
                next_run_at=s["next_run_at"],
                total_items=len(s["queries"]) if isinstance(s["queries"], dict) else 0,
                is_active=bool(s["is_active"]),
                source_file_name=s.get("source_file_name"),
                source_s3_uri=s.get("source_s3_uri"),
                source_upload_id=s.get("source_upload_id"),
            )
            for s in schedules
        ]

    def remove_daily_schedule(self, schedule_id: str, user_id: str | None = None, user_name: str | None = None) -> bool:
        removed = self.repository.deactivate_daily_schedule(schedule_id)
        if removed:
            self.repository.add_audit_event(
                action="DAILY_SCHEDULE_DISABLED",
                user_id=user_id,
                user_name=user_name,
                entity_type="daily_schedule",
                entity_id=schedule_id,
                details={"disabled_by": user_name or user_id},
            )
        return removed

    def list_audit_events(self, limit: int = 200, user_id: str | None = None) -> list[AuditEvent]:
        events = self.repository.list_audit_events(limit=limit, user_id=user_id)
        return [AuditEvent.model_validate(e) for e in events]

    def subscribe_to_schedule(
        self,
        schedule_id: str,
        user_id: str | None,
        user_name: str | None,
        email: str,
    ) -> ScheduleSubscription:
        subscription_id = self.repository.upsert_schedule_subscription(
            schedule_id=schedule_id,
            user_id=user_id,
            user_name=user_name,
            email=email,
        )
        self.repository.add_audit_event(
            action="DAILY_SCHEDULE_SUBSCRIBED",
            user_id=user_id,
            user_name=user_name,
            entity_type="daily_schedule_subscription",
            entity_id=subscription_id,
            details={"schedule_id": schedule_id, "email": email},
        )
        rows = self.repository.list_schedule_subscriptions(schedule_id=schedule_id, user_id=user_id)
        for row in rows:
            if row["subscription_id"] == subscription_id:
                return ScheduleSubscription.model_validate(row)
        return ScheduleSubscription(
            subscription_id=subscription_id,
            schedule_id=schedule_id,
            user_id=user_id,
            user_name=user_name,
            email=email,
            is_active=True,
            created_at="",
        )

    def unsubscribe_from_schedule(
        self,
        schedule_id: str,
        email: str,
        user_id: str | None = None,
        user_name: str | None = None,
    ) -> bool:
        removed = self.repository.deactivate_schedule_subscription(schedule_id=schedule_id, email=email)
        if removed:
            self.repository.add_audit_event(
                action="DAILY_SCHEDULE_UNSUBSCRIBED",
                user_id=user_id,
                user_name=user_name,
                entity_type="daily_schedule_subscription",
                entity_id=schedule_id,
                details={"schedule_id": schedule_id, "email": email},
            )
        return removed

    def list_schedule_subscriptions(self, schedule_id: str, user_id: str | None = None) -> list[ScheduleSubscription]:
        rows = self.repository.list_schedule_subscriptions(schedule_id=schedule_id, user_id=user_id)
        return [ScheduleSubscription.model_validate(row) for row in rows]

    def list_user_notifications(
        self,
        limit: int = 100,
        user_id: str | None = None,
        email: str | None = None,
    ) -> list[UserNotification]:
        rows = self.repository.list_user_notifications(limit=limit, user_id=user_id, email=email)
        return [UserNotification.model_validate(row) for row in rows]
