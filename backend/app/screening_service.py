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
    ScreeningQueueMessage,
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
        if payload.daily_screening:
            daily_schedule_id = str(uuid4())
            self.repository.create_daily_schedule(
                schedule_id=daily_schedule_id,
                batch_name=payload.batch_name.strip(),
                user_id=payload.user_id,
                user_name=payload.user_name,
                queries={k: v.model_dump(mode="json") for k, v in payload.queries.items()},
                screening_types=payload.screening_types,
                mock_screening=payload.mock_screening,
                timezone_name=settings.daily_screening_timezone,
                run_hour=settings.daily_screening_hour,
                run_minute=settings.daily_screening_minute,
            )
            self.repository.add_audit_event(
                action="DAILY_SCHEDULE_CREATED",
                user_id=payload.user_id,
                user_name=payload.user_name,
                entity_type="daily_schedule",
                entity_id=daily_schedule_id,
                details={
                    "batch_name": payload.batch_name,
                    "total_items": len(payload.queries),
                    "screening_types": payload.screening_types,
                    "timezone": settings.daily_screening_timezone,
                    "run_hour": settings.daily_screening_hour,
                    "run_minute": settings.daily_screening_minute,
                },
            )

        job_id = str(uuid4())
        submitted_at = self.repository.create_job(job_id=job_id, total_items=len(payload.queries))

        for item_key, query in payload.queries.items():
            query_payload = query.model_dump(mode="json")
            self.repository.add_job_item(job_id=job_id, item_key=item_key, request_payload=query_payload)
            self.queue.enqueue(
                ScreeningQueueMessage(
                    job_id=job_id,
                    item_key=item_key,
                    query=query,
                    submitted_at=submitted_at,
                    screening_types=payload.screening_types,
                    mock_screening=payload.mock_screening,
                )
            )

        self.repository.add_audit_event(
            action="SCREENING_JOB_SUBMITTED",
            user_id=payload.user_id,
            user_name=payload.user_name,
            entity_type="screening_job",
            entity_id=job_id,
            details={
                "total_items": len(payload.queries),
                "screening_types": payload.screening_types,
                "daily_screening": payload.daily_screening,
                "batch_name": payload.batch_name,
                "mock_screening": payload.mock_screening,
            },
        )

        return MatchJobAccepted(
            job_id=job_id,
            status=JobStatus.queued,
            submitted_at=submitted_at,
            total_items=len(payload.queries),
            daily_schedule_id=daily_schedule_id,
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

            progress.status = JobStatus.completed if progress.completed_items > 0 else JobStatus.failed
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
                timezone=s["timezone"],
                run_hour=int(s["run_hour"]),
                run_minute=int(s["run_minute"]),
                created_at=s["created_at"],
                last_run_at=s["last_run_at"],
                next_run_at=s["next_run_at"],
                total_items=len(s["queries"]) if isinstance(s["queries"], dict) else 0,
                is_active=bool(s["is_active"]),
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
