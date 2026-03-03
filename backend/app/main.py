from __future__ import annotations

import hashlib
import json
import re
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .actimize import ActimizeClient
from .auth import AuthPrincipal, principal_has_permission, require_any_scope
from .config import settings
from .file_store import S3FileStore
from .models import (
    AuditEvent,
    BatchUploadAccepted,
    DailyScheduleInfo,
    EntityExample,
    EntityMatchResponse,
    MatchJobAccepted,
    MatchJobProgress,
    MatchJobRequest,
    ScheduleSubscription,
    UserNotification,
)
from .queue import SqsQueue
from .repository import JobRepository
from .screening_service import ScreeningService

repository = JobRepository(settings.app_db_path, settings.app_db_url)
queue = SqsQueue()
service = ScreeningService(repository=repository, queue=queue)
actimize = ActimizeClient()
file_store = S3FileStore()

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


_MACHINE_USER_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE)


def _looks_machine_user(value: str | None) -> bool:
    raw = (value or "").strip()
    if not raw:
        return True
    if raw.isdigit():
        return True
    if _MACHINE_USER_RE.match(raw):
        return True
    return False


def _preferred_actor_name(principal: AuthPrincipal, hinted_user_name: str | None = None) -> str:
    hinted = (hinted_user_name or "").strip()
    if hinted and not _looks_machine_user(hinted):
        return hinted

    if principal.email and principal.email.strip():
        return principal.email.strip()

    principal_name = (principal.user_name or "").strip()
    if principal_name and not _looks_machine_user(principal_name):
        return principal_name

    if hinted:
        return hinted
    if principal_name:
        return principal_name
    return principal.user_id


def _parse_subscription_emails(raw_values: list[str]) -> list[str]:
    seen: set[str] = set()
    emails: list[str] = []
    for raw in raw_values:
        for token in re.split(r"[,\n;]+", str(raw or "")):
            candidate = token.strip().lower()
            if not candidate or "@" not in candidate:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            emails.append(candidate)
    return emails


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/screenings/jobs", response_model=MatchJobAccepted)
def create_screening_job(
    payload: MatchJobRequest,
    principal: AuthPrincipal = Depends(require_any_scope("screening.write", "screening.daily", "screening.admin")),
    svc: ScreeningService = Depends(get_service),
) -> MatchJobAccepted:
    if payload.daily_screening and not principal_has_permission(principal, "screening.daily", "screening.admin"):
        raise HTTPException(status_code=403, detail="Only Compliance/Admin can enable daily screening")

    try:
        actor_user_name = _preferred_actor_name(principal, payload.user_name)
        payload = payload.model_copy(update={"user_id": principal.user_id, "user_name": actor_user_name})
        return svc.submit_job(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/screenings/batch-upload", response_model=BatchUploadAccepted)
async def create_batch_job_with_upload(
    file: UploadFile = File(...),
    queries_json: str = Form(...),
    screening_types_json: str = Form(default="[]"),
    batch_name: str = Form(default=""),
    daily_screening: bool = Form(default=False),
    schedule_frequency: str = Form(default="DAILY"),
    schedule_run_at: str | None = Form(default=None),
    schedule_id: str | None = Form(default=None),
    mock_screening: bool = Form(default=False),
    subscribe_results: bool = Form(default=False),
    subscribe_email: str | None = Form(default=None),
    subscribe_emails: str | None = Form(default=None),
    user_name: str | None = Form(default=None),
    principal: AuthPrincipal = Depends(require_any_scope("screening.write", "screening.daily", "screening.admin")),
    svc: ScreeningService = Depends(get_service),
) -> BatchUploadAccepted:
    if (daily_screening or (schedule_id or "").strip()) and not principal_has_permission(principal, "screening.daily", "screening.admin"):
        raise HTTPException(status_code=403, detail="Only Compliance/Admin can enable scheduled screening")

    if not file.filename:
        raise HTTPException(status_code=400, detail="file is required")

    try:
        parsed_queries = json.loads(queries_json)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid queries_json: {exc}") from exc
    if not isinstance(parsed_queries, dict) or not parsed_queries:
        raise HTTPException(status_code=400, detail="queries_json must be a non-empty object")

    try:
        parsed_types = json.loads(screening_types_json)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid screening_types_json: {exc}") from exc
    if not isinstance(parsed_types, list):
        raise HTTPException(status_code=400, detail="screening_types_json must be a JSON array")
    screening_types = [str(v).strip() for v in parsed_types if str(v).strip()]

    body = await file.read()
    if not body:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    upload_id = str(uuid4())
    file_hash = hashlib.sha256(body).hexdigest()
    s3_info: dict[str, str] = {}
    if file_store.is_enabled():
        try:
            s3_info = file_store.upload_source_file(
                job_id=upload_id,
                user_id=principal.user_id,
                original_filename=file.filename,
                body=body,
                content_type=file.content_type,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Failed to upload file to S3: {exc}") from exc

    actor_user_name = _preferred_actor_name(principal, user_name)

    repository.register_batch_file_upload(
        upload_id=upload_id,
        file_name=file.filename,
        user_id=principal.user_id,
        user_name=actor_user_name,
        record_count=len(parsed_queries),
        file_hash=file_hash,
        s3_bucket=s3_info.get("bucket"),
        s3_key=s3_info.get("key"),
        s3_uri=s3_info.get("s3_uri"),
        schedule_id=(schedule_id or "").strip() or None,
    )

    queries: dict[str, EntityExample] = {}
    for item_key, value in parsed_queries.items():
        queries[str(item_key)] = EntityExample.model_validate(value)

    payload = MatchJobRequest(
        queries=queries,
        screening_types=screening_types,
        mock_screening=bool(mock_screening),
        daily_screening=bool(daily_screening),
        schedule_frequency=schedule_frequency,
        schedule_run_at=(schedule_run_at or "").strip() or None,
        schedule_id=(schedule_id or "").strip() or None,
        source_upload_id=upload_id,
        batch_name=(batch_name or "").strip() or None,
        user_id=principal.user_id,
        user_name=actor_user_name,
    )

    try:
        accepted = svc.submit_job(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    repository.attach_upload_to_job(upload_id=upload_id, job_id=accepted.job_id)
    if accepted.daily_schedule_id:
        repository.attach_upload_to_schedule(
            schedule_id=accepted.daily_schedule_id,
            upload_id=upload_id,
            file_name=file.filename,
            s3_uri=s3_info.get("s3_uri"),
        )

    if subscribe_results and accepted.daily_schedule_id:
        subscription_emails = _parse_subscription_emails(
            [
                subscribe_emails or "",
                subscribe_email or "",
                principal.email or "",
            ]
        )
        for email in subscription_emails:
            svc.subscribe_to_schedule(
                schedule_id=accepted.daily_schedule_id,
                user_id=principal.user_id,
                user_name=actor_user_name,
                email=email,
            )

    repository.add_audit_event(
        action="BATCH_FILE_UPLOADED",
        user_id=principal.user_id,
        user_name=actor_user_name,
        entity_type="batch_file_upload",
        entity_id=upload_id,
        details={
            "file_name": file.filename,
            "record_count": len(parsed_queries),
            "s3_uri": s3_info.get("s3_uri"),
            "job_id": accepted.job_id,
            "daily_schedule_id": accepted.daily_schedule_id,
            "schedule_frequency": payload.schedule_frequency,
            "schedule_run_at": payload.schedule_run_at,
            "schedule_id": payload.schedule_id,
        },
    )

    return BatchUploadAccepted(
        job_id=accepted.job_id,
        status=accepted.status,
        submitted_at=accepted.submitted_at,
        total_items=accepted.total_items,
        daily_schedule_id=accepted.daily_schedule_id,
        screened_item_keys=accepted.screened_item_keys,
        source_upload_id=upload_id,
        file_name=file.filename,
        s3_uri=s3_info.get("s3_uri"),
        schedule_frequency=payload.schedule_frequency if payload.daily_screening else None,
    )


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


@app.get("/api/v1/screenings/daily-schedules/{schedule_id}/subscriptions", response_model=list[ScheduleSubscription])
def list_daily_schedule_subscriptions(
    schedule_id: str,
    principal: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> list[ScheduleSubscription]:
    return svc.list_schedule_subscriptions(schedule_id=schedule_id, user_id=principal.user_id)


@app.post("/api/v1/screenings/daily-schedules/{schedule_id}/subscriptions", response_model=ScheduleSubscription)
def subscribe_daily_schedule(
    schedule_id: str,
    email: str = Query(default=""),
    principal: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> ScheduleSubscription:
    safe_email = email.strip().lower() or principal.email.strip().lower()
    if not safe_email:
        raise HTTPException(status_code=400, detail="email is required")
    return svc.subscribe_to_schedule(
        schedule_id=schedule_id,
        user_id=principal.user_id,
        user_name=_preferred_actor_name(principal),
        email=safe_email,
    )


@app.delete("/api/v1/screenings/daily-schedules/{schedule_id}/subscriptions")
def unsubscribe_daily_schedule(
    schedule_id: str,
    email: str = Query(default=""),
    principal: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> dict[str, str]:
    safe_email = email.strip().lower() or principal.email.strip().lower()
    if not safe_email:
        raise HTTPException(status_code=400, detail="email is required")
    removed = svc.unsubscribe_from_schedule(
        schedule_id=schedule_id,
        email=safe_email,
        user_id=principal.user_id,
        user_name=_preferred_actor_name(principal),
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "removed", "schedule_id": schedule_id, "email": safe_email}


@app.delete("/api/v1/screenings/daily-schedules/{schedule_id}")
def remove_daily_schedule(
    schedule_id: str,
    user_id: str | None = Query(default=None),
    user_name: str | None = Query(default=None),
    principal: AuthPrincipal = Depends(require_any_scope("screening.daily", "screening.admin")),
    svc: ScreeningService = Depends(get_service),
) -> dict[str, str]:
    actor_user_id = principal.user_id if principal.user_id else user_id
    actor_user_name = _preferred_actor_name(principal, user_name)
    removed = svc.remove_daily_schedule(schedule_id, user_id=actor_user_id, user_name=actor_user_name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Daily schedule {schedule_id} not found")
    return {"status": "removed", "schedule_id": schedule_id}


@app.get("/api/v1/audit-events", response_model=list[AuditEvent])
def list_audit_events(
    limit: int = Query(default=200, ge=1, le=1000),
    user_id: str | None = Query(default=None),
    _: AuthPrincipal = Depends(require_any_scope("screening.admin", "screening.useradmin")),
    svc: ScreeningService = Depends(get_service),
) -> list[AuditEvent]:
    return svc.list_audit_events(limit=limit, user_id=user_id)


@app.get("/api/v1/notifications", response_model=list[UserNotification])
def list_user_notifications(
    limit: int = Query(default=100, ge=1, le=1000),
    principal: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> list[UserNotification]:
    return svc.list_user_notifications(limit=limit, user_id=principal.user_id, email=principal.email)


@app.post("/api/v1/screenings/match", response_model=EntityMatchResponse)
def match_sync(
    payload: MatchJobRequest,
    principal: AuthPrincipal = Depends(require_any_scope("screening.write", "screening.single.mock", "screening.admin")),
) -> EntityMatchResponse:
    if not payload.queries:
        raise HTTPException(status_code=400, detail="At least one query is required")

    if not payload.mock_screening and not principal_has_permission(principal, "screening.write", "screening.admin"):
        raise HTTPException(status_code=403, detail="Viewer can perform only mock single screening")

    actor_user_name = _preferred_actor_name(principal, payload.user_name)
    payload = payload.model_copy(update={"user_id": principal.user_id, "user_name": actor_user_name})
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
            repository.add_audit_event(
                action="SYNC_SCREENING_ITEM_FAILED",
                user_id=payload.user_id,
                user_name=payload.user_name,
                entity_type="sync_screening_item",
                entity_id=item_key,
                details={"item_key": item_key, "error": str(exc)},
            )
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
