from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .actimize import ActimizeClient
from .auth import AuthPrincipal, require_any_scope
from .config import settings
from .models import AuditEvent, DailyScheduleInfo, EntityMatchResponse, MatchJobAccepted, MatchJobProgress, MatchJobRequest
from .queue import SqsQueue
from .repository import JobRepository
from .screening_service import ScreeningService

repository = JobRepository(settings.app_db_path)
queue = SqsQueue()
service = ScreeningService(repository=repository, queue=queue)
actimize = ActimizeClient()

app = FastAPI(title=settings.app_name, version=settings.app_version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    queue.ensure_queue()


def get_service() -> ScreeningService:
    return service


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/screenings/jobs", response_model=MatchJobAccepted)
def create_screening_job(
    payload: MatchJobRequest,
    principal: AuthPrincipal = Depends(require_any_scope("screening.write")),
    svc: ScreeningService = Depends(get_service),
) -> MatchJobAccepted:
    try:
        payload = payload.model_copy(update={"user_id": principal.user_id, "user_name": principal.user_name})
        return svc.submit_job(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/screenings/jobs/{job_id}", response_model=MatchJobProgress)
def get_screening_job(
    job_id: str,
    _: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> MatchJobProgress:
    progress = svc.get_progress(job_id)
    if not progress:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return progress


@app.get("/api/v1/screenings/daily-schedules", response_model=list[DailyScheduleInfo])
def list_daily_schedules(
    _: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> list[DailyScheduleInfo]:
    return svc.list_daily_schedules()


@app.delete("/api/v1/screenings/daily-schedules/{schedule_id}")
def remove_daily_schedule(
    schedule_id: str,
    user_id: str | None = Query(default=None),
    user_name: str | None = Query(default=None),
    principal: AuthPrincipal = Depends(require_any_scope("screening.write")),
    svc: ScreeningService = Depends(get_service),
) -> dict[str, str]:
    actor_user_id = principal.user_id if principal.user_id else user_id
    actor_user_name = principal.user_name if principal.user_name else user_name
    removed = svc.remove_daily_schedule(schedule_id, user_id=actor_user_id, user_name=actor_user_name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Daily schedule {schedule_id} not found")
    return {"status": "removed", "schedule_id": schedule_id}


@app.get("/api/v1/audit-events", response_model=list[AuditEvent])
def list_audit_events(
    limit: int = Query(default=200, ge=1, le=1000),
    user_id: str | None = Query(default=None),
    _: AuthPrincipal = Depends(require_any_scope("screening.admin")),
    svc: ScreeningService = Depends(get_service),
) -> list[AuditEvent]:
    return svc.list_audit_events(limit=limit, user_id=user_id)


@app.post("/api/v1/screenings/match", response_model=EntityMatchResponse)
def match_sync(
    payload: MatchJobRequest,
    principal: AuthPrincipal = Depends(require_any_scope("screening.write")),
) -> EntityMatchResponse:
    if not payload.queries:
        raise HTTPException(status_code=400, detail="At least one query is required")
    payload = payload.model_copy(update={"user_id": principal.user_id, "user_name": principal.user_name})
    repository.add_audit_event(
        action="SYNC_SCREENING_SUBMITTED",
        user_id=payload.user_id,
        user_name=payload.user_name,
        entity_type="sync_screening",
        entity_id=None,
        details={
            "total_items": len(payload.queries),
            "screening_types": payload.screening_types,
            "mock_screening": payload.mock_screening,
        },
    )

    responses: dict[str, dict] = {}
    for item_key, query in payload.queries.items():
        try:
            screened = actimize.screen_many_types(
                query,
                payload.screening_types,
                payload.mock_screening,
            )
            raw_results = screened.get("results", [])
            results = raw_results if isinstance(raw_results, list) else []
            trimmed_results = results[: settings.screening_result_limit]

            responses[item_key] = {
                "results": trimmed_results,
                "total": {"value": len(trimmed_results), "relation": "eq"},
                "query": query.model_dump(mode="json"),
                "status": int(screened.get("status", 200) or 200),
            }
        except Exception as exc:  # noqa: BLE001
            responses[item_key] = {
                "results": [],
                "total": {"value": 0, "relation": "eq"},
                "query": query.model_dump(mode="json"),
                "status": 500,
                "error": str(exc),
            }

    return EntityMatchResponse.model_validate(
        {
            "responses": responses,
            "limit": settings.screening_result_limit,
        }
    )
