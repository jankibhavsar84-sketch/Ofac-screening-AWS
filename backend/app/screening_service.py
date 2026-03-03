from __future__ import annotations

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
        source_schedule_id = (payload.schedule_id or "").strip() or None
        schedule_frequency = self.repository.normalize_schedule_frequency(payload.schedule_frequency)
        source_upload_id = (payload.source_upload_id or "").strip() or None
        base_queries = {k: v.model_dump(mode="json") for k, v in payload.queries.items()}

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
                },
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
