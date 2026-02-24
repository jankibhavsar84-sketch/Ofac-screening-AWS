from __future__ import annotations

from uuid import uuid4

from .config import settings
from .models import (
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
                )
            )

        return MatchJobAccepted(
            job_id=job_id,
            status=JobStatus.queued,
            submitted_at=submitted_at,
            total_items=len(payload.queries),
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

