from __future__ import annotations

import hashlib
import json
import re
from time import monotonic
from typing import Any
from urllib.parse import parse_qsl
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.responses import Response

from .actimize import ActimizeClient, ExternalApiCallError
from .auth import AuthPrincipal, clear_audit_principal, get_audit_principal, principal_has_permission, require_any_scope
from .config import settings
from .file_store import S3FileStore
from .models import (
    ActimizeAlertCallbackAccepted,
    ActimizeAlertCallbackRequest,
    AdminUserOption,
    AuditEvent,
    AuditEventPage,
    BatchUploadAccepted,
    BusinessUnit,
    BusinessUnitUpdateRequest,
    BusinessUnitUpsertRequest,
    DailyScheduleBatchRunStatusPage,
    DailyScheduleInfoPage,
    EntityMatchResponse,
    JobStatus,
    MatchJobAccepted,
    MatchJobProgress,
    MatchJobRequest,
    ScreeningTypeOption,
    ScreeningQueueMessage,
    ScheduleSubscription,
    UserBusinessUnitMapping,
    UserBusinessUnitUpdateRequest,
)
from .queue import SqsQueue
from .repository import JobRepository
from .screening_service import ScreeningService
from .sns_notifier import SnsNotifier

repository = JobRepository(
    settings.app_db_path,
    settings.app_db_url,
)
screening_queue = SqsQueue(settings.aws_sqs_queue_name)
dispatch_queue = SqsQueue(settings.aws_dispatch_sqs_queue_name)
notifier = SnsNotifier()
service = ScreeningService(
    repository=repository,
    queue=screening_queue,
    notifier=notifier,
    dispatch_queue=dispatch_queue,
)
actimize = ActimizeClient(repository=repository)
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
    screening_queue.ensure_queue()
    dispatch_queue.ensure_queue()


_SENSITIVE_QUERY_KEYS = {
    "token",
    "access_token",
    "id_token",
    "authorization",
    "password",
    "secret",
    "client_secret",
    "email",
    "subscribe_email",
    "subscribe_emails",
}
_SUBSCRIPTION_EMAIL_DOMAIN = "prudential.com"
_BASIC_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _is_sensitive_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    return normalized in _SENSITIVE_QUERY_KEYS or normalized.endswith("_token") or normalized.endswith("_secret")


def _redact_value(value: str) -> str:
    safe = str(value or "").strip()
    if not safe:
        return ""
    if len(safe) <= 2:
        return "*" * len(safe)
    return f"{safe[:2]}***"


def _sanitize_query_params(raw_query: str) -> dict[str, str]:
    if not raw_query:
        return {}
    redacted: dict[str, str] = {}
    for key, value in parse_qsl(raw_query, keep_blank_values=True):
        safe_key = str(key or "").strip()
        if not safe_key:
            continue
        if _is_sensitive_key(safe_key):
            redacted[safe_key] = _redact_value(value)
        else:
            redacted[safe_key] = str(value or "").strip()
    return redacted


def _sanitize_query_string(raw_query: str) -> str | None:
    params = _sanitize_query_params(raw_query)
    if not params:
        return None
    return "&".join(f"{key}={value}" for key, value in params.items())


def _request_correlation_id(request: Request) -> str:
    from_state = str(getattr(request.state, "correlation_id", "") or "").strip()
    if from_state:
        return from_state
    from_header = str(request.headers.get("x-correlation-id") or "").strip()
    if from_header:
        return from_header
    generated = str(uuid4())
    request.state.correlation_id = generated
    return generated


def _client_ip(request: Request) -> str | None:
    forwarded = str(request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return None


def _extract_response_detail(response: Response | None) -> str | None:
    if response is None:
        return None
    try:
        body = getattr(response, "body", None)
        if isinstance(body, (bytes, bytearray)):
            text = body.decode("utf-8", errors="ignore").strip()
            return text[:500] if text else None
    except Exception:  # noqa: BLE001
        return None
    return None


def _trim_screening_match_payload(
    payload: dict[str, Any],
    limit: int,
    fallback_query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_limit = max(int(limit or 0), 0)
    safe_payload = dict(payload) if isinstance(payload, dict) else {}

    raw_results = safe_payload.get("results")
    results = raw_results if isinstance(raw_results, list) else []
    trimmed_results = results[:safe_limit] if safe_limit > 0 else []
    safe_payload["results"] = trimmed_results
    safe_payload["total"] = {"value": len(trimmed_results), "relation": "eq"}
    if not isinstance(safe_payload.get("status"), int):
        safe_payload["status"] = 200
    if not isinstance(safe_payload.get("query"), dict):
        safe_payload["query"] = fallback_query or {}

    raw_mapping = safe_payload.get("responses_by_screening_type")
    if isinstance(raw_mapping, dict):
        trimmed_mapping: dict[str, dict[str, Any]] = {}
        for key, value in raw_mapping.items():
            if not isinstance(value, dict):
                continue
            trimmed_mapping[str(key)] = _trim_screening_match_payload(value, safe_limit, fallback_query=fallback_query)
        safe_payload["responses_by_screening_type"] = trimmed_mapping
    return safe_payload


def _count_match_candidates(payload: dict[str, Any]) -> int:
    if not isinstance(payload, dict):
        return 0
    raw_mapping = payload.get("responses_by_screening_type")
    if isinstance(raw_mapping, dict):
        total = 0
        for value in raw_mapping.values():
            if not isinstance(value, dict):
                continue
            results = value.get("results")
            if isinstance(results, list):
                total += len(results)
        return total
    results = payload.get("results")
    return len(results) if isinstance(results, list) else 0


def _build_single_party_keys_by_screening_type(screening_types: list[str] | None) -> dict[str, str]:
    safe_types = [str(value or "").strip() for value in (screening_types or []) if str(value or "").strip()]
    if not safe_types:
        safe_types = ["Sanction"]
    return {safe_type: actimize.build_on_demand_party_key(safe_type) for safe_type in safe_types}


@app.middleware("http")
async def audit_api_access(request: Request, call_next: Any) -> Response:
    clear_audit_principal()
    incoming_correlation = str(request.headers.get("x-correlation-id") or "").strip()
    correlation_id = incoming_correlation or str(uuid4())
    request.state.correlation_id = correlation_id
    start = monotonic()
    response: Response | None = None
    unhandled_error: str | None = None
    try:
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    except Exception as exc:  # noqa: BLE001
        unhandled_error = str(exc)
        raise
    finally:
        if request.url.path.startswith("/api/v1/") and settings.audit_access_log_enabled:
            try:
                elapsed_ms = int((monotonic() - start) * 1000)
                status_code = int(response.status_code) if response is not None else 500
                principal = get_audit_principal()
                user_id = principal.user_id if principal else None
                user_name = principal.user_name if principal else None
                auth_state = "AUTHORIZED"
                if status_code == 401:
                    auth_state = "AUTHENTICATION_FAILED"
                elif status_code == 403:
                    auth_state = "AUTHORIZATION_FAILED"
                elif status_code >= 500:
                    auth_state = "SERVER_ERROR"

                sanitized_query_params = _sanitize_query_params(request.url.query)
                details: dict[str, Any] = {
                    "query_params": sanitized_query_params,
                    "route_name": str(request.scope.get("path") or request.url.path),
                }
                if unhandled_error:
                    details["error"] = unhandled_error
                response_detail = _extract_response_detail(response)
                if response_detail and status_code >= 400:
                    details["response_detail"] = response_detail

                repository.add_api_access_log(
                    request_method=request.method,
                    request_path=request.url.path,
                    query_string=_sanitize_query_string(request.url.query),
                    status_code=status_code,
                    duration_ms=elapsed_ms,
                    correlation_id=correlation_id,
                    client_ip=_client_ip(request),
                    user_agent=str(request.headers.get("user-agent") or "").strip() or None,
                    user_id=user_id,
                    user_name=user_name,
                    auth_state=auth_state,
                    details=details,
                )

                if status_code == 401:
                    repository.add_audit_event(
                        action="API_AUTHENTICATION_FAILED",
                        user_id=user_id,
                        user_name=user_name,
                        entity_type="api_request",
                        entity_id=request.url.path,
                        details={
                            "method": request.method,
                            "status_code": status_code,
                            "correlation_id": correlation_id,
                            "client_ip": _client_ip(request),
                            "query_params": sanitized_query_params,
                            "response_detail": response_detail,
                        },
                    )
                elif status_code == 403:
                    repository.add_audit_event(
                        action="API_AUTHORIZATION_FAILED",
                        user_id=user_id,
                        user_name=user_name,
                        entity_type="api_request",
                        entity_id=request.url.path,
                        details={
                            "method": request.method,
                            "status_code": status_code,
                            "correlation_id": correlation_id,
                            "client_ip": _client_ip(request),
                            "query_params": sanitized_query_params,
                            "response_detail": response_detail,
                        },
                    )
            except Exception:
                pass
        clear_audit_principal()


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


def _normalize_subscription_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def _is_allowed_subscription_email(value: str | None) -> bool:
    email = _normalize_subscription_email(value)
    if not email or not _BASIC_EMAIL_RE.match(email):
        return False
    return email.endswith(f"@{_SUBSCRIPTION_EMAIL_DOMAIN}")


def _parse_subscription_emails(raw_values: list[str]) -> tuple[list[str], list[str]]:
    seen: set[str] = set()
    valid_emails: list[str] = []
    invalid_emails: list[str] = []
    for raw in raw_values:
        for token in re.split(r"[,\n;]+", str(raw or "")):
            candidate = _normalize_subscription_email(token)
            if not candidate:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            if _is_allowed_subscription_email(candidate):
                valid_emails.append(candidate)
            else:
                invalid_emails.append(candidate)
    return valid_emails, invalid_emails


def _normalize_business_unit_code(value: str | None) -> str:
    return str(value or "").strip().upper()


def _as_str_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v or "").strip() for v in value if str(v or "").strip()]
    if isinstance(value, str):
        safe = value.strip()
        return [safe] if safe else []
    return []


def _validate_batch_upload_queries(parsed_queries: dict[str, Any]) -> None:
    allowed_schemas = {"person", "individual", "company", "organization", "legalentity", "unknown"}
    errors: list[str] = []
    seen_query_keys: set[str] = set()

    for item_key, raw_query in parsed_queries.items():
        query_key = str(item_key).strip()
        if not query_key:
            errors.append("PartyKey is required and cannot be blank")
            continue

        normalized_query_key = query_key.upper()
        if normalized_query_key in seen_query_keys:
            errors.append(f"Duplicate PartyKey '{query_key}'. PartyKey must be unique within the file")
            continue
        seen_query_keys.add(normalized_query_key)

        # Legacy auto row keys indicate upload was not keyed by PartyKey.
        if re.match(r"^row_\d+$", query_key, flags=re.IGNORECASE):
            errors.append(f"{query_key}: invalid PartyKey. Upload must include a non-empty PartyKey column")
            continue

        if not isinstance(raw_query, dict):
            errors.append(f"{query_key}: query must be an object")
            continue

        schema = str(raw_query.get("schema") or "").strip().lower()
        if schema not in allowed_schemas:
            errors.append(f"{query_key}: unsupported schema '{raw_query.get('schema')}'")

        props = raw_query.get("properties")
        if not isinstance(props, dict):
            errors.append(f"{query_key}: properties must be an object")
            continue

        names = _as_str_values(props.get("name"))
        if not names:
            errors.append(f"{query_key}: at least one non-empty name is required")

        raw_genders = (
            _as_str_values(props.get("genderCode"))
            + _as_str_values(props.get("gender_code"))
            + _as_str_values(props.get("gender"))
        )
        for raw_gender in raw_genders:
            normalized = raw_gender.strip().upper()
            if normalized in {"M", "F", ""}:
                continue
            if raw_gender.strip().lower() in {"male", "female", "unknown"}:
                continue
            errors.append(f"{query_key}: gender code must be M, F, or blank")
            break

    if errors:
        preview = "; ".join(errors[:6])
        if len(errors) > 6:
            preview += f"; +{len(errors) - 6} more"
        raise HTTPException(status_code=400, detail=f"Upload validation failed: {preview}")


def _resolve_external_api_context(exc: Exception) -> tuple[str, str, str, int | None, dict[str, Any]]:
    if isinstance(exc, ExternalApiCallError):
        return (
            exc.provider,
            exc.operation,
            exc.endpoint,
            exc.status_code,
            dict(exc.details or {}),
        )
    return (
        settings.actimize_provider,
        "screen_many_types",
        "",
        None,
        {},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/integrations/actimize/alerts/callback", response_model=ActimizeAlertCallbackAccepted)
def receive_actimize_alert_callback(
    payload: ActimizeAlertCallbackRequest,
    request: Request,
    svc: ScreeningService = Depends(get_service),
) -> ActimizeAlertCallbackAccepted:
    try:
        correlation_id = _request_correlation_id(request)
        return svc.handle_actimize_alert_callback(payload, correlation_id=correlation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/screenings/jobs", response_model=MatchJobAccepted)
def create_screening_job(
    payload: MatchJobRequest,
    request: Request,
    principal: AuthPrincipal = Depends(require_any_scope("screening.write", "screening.daily", "screening.admin")),
    svc: ScreeningService = Depends(get_service),
) -> MatchJobAccepted:
    if payload.daily_screening and not principal_has_permission(principal, "screening.daily", "screening.admin"):
        raise HTTPException(status_code=403, detail="Only Compliance/Admin can enable daily screening")

    try:
        correlation_id = _request_correlation_id(request)
        actor_user_name = _preferred_actor_name(principal, payload.user_name)
        payload = payload.model_copy(
            update={"user_id": principal.user_id, "user_name": actor_user_name, "correlation_id": correlation_id}
        )
        return svc.submit_job(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/screenings/batch-upload", response_model=BatchUploadAccepted)
async def create_batch_job_with_upload(
    request: Request,
    principal: AuthPrincipal = Depends(require_any_scope("screening.write", "screening.daily", "screening.admin")),
    svc: ScreeningService = Depends(get_service),
) -> BatchUploadAccepted:
    # FastAPI/Starlette defaults to a 1MB multipart max part size, which breaks batch uploads
    # once either the XLSX file or a JSON form field exceeds that size.
    form = await request.form(max_part_size=settings.multipart_max_part_size_bytes)

    def _form_str(key: str, default: str | None = None) -> str | None:
        value = form.get(key)
        if value is None:
            return default
        if isinstance(value, str):
            safe = value.strip()
            return safe if safe else default
        return str(value).strip() or default

    def _form_bool(key: str, default: bool = False) -> bool:
        raw = _form_str(key, None)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}

    def _form_required_str(key: str) -> str:
        value = _form_str(key, None)
        if not value:
            raise HTTPException(status_code=400, detail=f"{key} is required")
        return value

    file = form.get("file")
    if not isinstance(file, StarletteUploadFile) or not str(getattr(file, "filename", "") or "").strip():
        raise HTTPException(status_code=400, detail="file is required")
    safe_file_name = str(file.filename or "").strip()
    if not re.search(r"\.(csv|xlsx)\Z", safe_file_name, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Only CSV and XLSX batch files are supported")

    screening_types_json = _form_str("screening_types_json", "[]") or "[]"
    batch_name = _form_str("batch_name", "") or ""
    daily_screening = _form_bool("daily_screening", False)
    schedule_frequency = _form_str("schedule_frequency", "DAILY") or "DAILY"
    schedule_run_at = _form_str("schedule_run_at", None)
    schedule_id_raw = _form_str("schedule_id", None)
    schedule_id: int | None = None
    if schedule_id_raw is not None and str(schedule_id_raw).strip() != "":
        try:
            schedule_id = int(str(schedule_id_raw).strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="schedule_id must be an integer") from exc
    mock_screening = _form_bool("mock_screening", False)
    subscribe_results = _form_bool("subscribe_results", False)
    subscribe_email = _form_str("subscribe_email", None)
    subscribe_emails = _form_str("subscribe_emails", None)
    business_unit_code = _form_required_str("business_unit_code")
    user_name = _form_str("user_name", None)

    if (daily_screening or schedule_id is not None) and not principal_has_permission(principal, "screening.daily", "screening.admin"):
        raise HTTPException(status_code=403, detail="Only Compliance/Admin can enable scheduled screening")

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
    is_scheduled_upload = bool(daily_screening or schedule_id is not None)

    upload_id = str(uuid4())
    file_hash = hashlib.sha256(body).hexdigest()
    s3_info: dict[str, str] = {}
    if file_store.is_enabled():
        try:
            s3_info = file_store.upload_source_file(
                job_id=upload_id,
                user_id=principal.user_id,
                original_filename=safe_file_name,
                body=body,
                content_type=file.content_type,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Failed to upload file to S3: {exc}") from exc

    actor_user_name = _preferred_actor_name(principal, user_name)
    correlation_id = _request_correlation_id(request)

    repository.register_batch_file_upload(
        upload_id=upload_id,
        file_name=safe_file_name,
        user_id=principal.user_id,
        user_name=actor_user_name,
        record_count=0,
        file_hash=file_hash,
        s3_bucket=s3_info.get("bucket"),
        s3_key=s3_info.get("key"),
        s3_uri=s3_info.get("s3_uri"),
        schedule_id=schedule_id,
    )

    # Scheduled/daily batch jobs should not execute immediately; preserve existing behavior.
    if is_scheduled_upload:
        payload = MatchJobRequest(
            queries={},
            screening_types=screening_types,
            mock_screening=bool(mock_screening),
            business_unit_code=_normalize_business_unit_code(business_unit_code),
            daily_screening=bool(daily_screening),
            schedule_frequency=schedule_frequency,
            schedule_run_at=(schedule_run_at or "").strip() or None,
            schedule_id=schedule_id,
            source_upload_id=upload_id,
            batch_name=(batch_name or "").strip() or None,
            correlation_id=correlation_id,
            user_id=principal.user_id,
            user_name=actor_user_name,
        )

        try:
            accepted = svc.submit_job(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        repository.attach_upload_to_job(upload_id=upload_id, job_id=accepted.job_id)
    else:
        # Immediate batch jobs can be very large (10k+ records). Creating job_items and enqueuing
        # one SQS message per record can exceed CloudFront's 60s origin timeout. Instead, create
        # the job quickly and let the worker expand/enqueue per-record tasks.
        safe_bu = _normalize_business_unit_code(business_unit_code)
        if not repository.user_has_business_unit(principal.user_id, safe_bu):
            raise HTTPException(status_code=400, detail="Selected Business Unit is not mapped to this user")

        if not file_store.is_enabled() or not s3_info.get("bucket") or not s3_info.get("key"):
            raise HTTPException(
                status_code=500,
                detail="Batch dispatch requires S3 storage to be enabled (AWS_S3_UPLOAD_BUCKET).",
            )

        submitted_at, job_id = repository.create_job(
            job_id=None,
            total_items=0,
            status=JobStatus.queued,
            source_upload_id=upload_id,
            user_id=principal.user_id,
            user_name=actor_user_name,
        )
        accepted = MatchJobAccepted(
            job_id=job_id,
            status=JobStatus.queued,
            submitted_at=submitted_at,
            total_items=0,
            business_unit_code=safe_bu or None,
            daily_schedule_id=None,
            screened_item_keys=[],
        )

        repository.attach_upload_to_job(upload_id=upload_id, job_id=accepted.job_id)
        dispatch = ScreeningQueueMessage(
            message_type="JOB_DISPATCH",
            job_id=job_id,
            submitted_at=submitted_at,
            screening_types=screening_types,
            mock_screening=bool(mock_screening),
            user_id=principal.user_id,
            user_name=actor_user_name,
            correlation_id=correlation_id,
            business_unit_code=safe_bu or None,
            source_upload_id=upload_id,
        )
        dispatch_queue.enqueue(dispatch)

    deferred_until: str | None = None
    if accepted.daily_schedule_id:
        schedule_snapshot = repository.get_daily_schedule(accepted.daily_schedule_id)
        deferred_until = (schedule_snapshot or {}).get("next_run_at")
    repository.upsert_job_metadata(
        job_id=accepted.job_id,
        mode="BATCH",
        screening_types=screening_types,
        mock_screening=bool(mock_screening),
        batch_name=(batch_name or "").strip() or None,
        file_name=safe_file_name,
        daily_screening=bool(daily_screening),
        schedule_frequency=schedule_frequency if daily_screening else None,
        daily_schedule_id=accepted.daily_schedule_id,
        query_count=0,
        deferred_until=deferred_until if (accepted.total_items == 0 and daily_screening and accepted.daily_schedule_id) else None,
        business_unit_code=_normalize_business_unit_code(business_unit_code),
    )
    if accepted.daily_schedule_id:
        repository.attach_upload_to_schedule(
            schedule_id=accepted.daily_schedule_id,
            upload_id=upload_id,
            file_name=safe_file_name,
            s3_uri=s3_info.get("s3_uri"),
        )

    if subscribe_results and accepted.daily_schedule_id:
        subscription_emails, invalid_subscription_emails = _parse_subscription_emails(
            [
                subscribe_emails or "",
                subscribe_email or "",
                principal.email or "",
            ]
        )
        if invalid_subscription_emails:
            invalid_preview = ", ".join(invalid_subscription_emails[:5])
            suffix = " ..." if len(invalid_subscription_emails) > 5 else ""
            raise HTTPException(
                status_code=400,
                detail=f"Only @{_SUBSCRIPTION_EMAIL_DOMAIN} subscription emails are allowed. Invalid: {invalid_preview}{suffix}",
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
            "file_name": safe_file_name,
            "record_count": 0,
            "record_count_pending": True,
            "s3_uri": s3_info.get("s3_uri"),
            "job_id": accepted.job_id,
            "daily_schedule_id": accepted.daily_schedule_id,
            "schedule_frequency": schedule_frequency,
            "schedule_run_at": schedule_run_at,
            "schedule_id": schedule_id,
            "business_unit_code": _normalize_business_unit_code(business_unit_code),
            "correlation_id": correlation_id,
        },
    )

    return BatchUploadAccepted(
        job_id=accepted.job_id,
        status=accepted.status,
        submitted_at=accepted.submitted_at,
        total_items=accepted.total_items,
        business_unit_code=accepted.business_unit_code,
        daily_schedule_id=accepted.daily_schedule_id,
        screened_item_keys=accepted.screened_item_keys,
        source_upload_id=upload_id,
        file_name=safe_file_name,
        s3_uri=s3_info.get("s3_uri"),
        schedule_frequency=schedule_frequency if daily_screening else None,
        row_meta=[
            {
                "key": row.key,
                "display_name": row.display_name,
                "ui_type": row.ui_type,
            }
            for row in ()
        ],
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


@app.get("/api/v1/screenings/daily-schedules", response_model=DailyScheduleInfoPage)
def list_daily_schedules(
    page: int = Query(default=1, ge=1),
    principal: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> DailyScheduleInfoPage:
    # Enforce fixed-size paging for configured daily schedules to keep payloads bounded.
    # Admins can view all schedules; non-admin users can view only schedules they created.
    user_scope_filter = None if principal_has_permission(principal, "screening.admin") else principal.user_id
    return svc.list_daily_schedules(page=page, page_size=10, user_id=user_scope_filter)


@app.get("/api/v1/screenings/daily-schedules/batch-runs", response_model=DailyScheduleBatchRunStatusPage)
def list_daily_schedule_batch_runs(
    page: int = Query(default=1, ge=1),
    _: AuthPrincipal = Depends(require_any_scope("screening.admin")),
    svc: ScreeningService = Depends(get_service),
) -> DailyScheduleBatchRunStatusPage:
    # Enforce fixed-size paging for admin batch-run status to keep payloads bounded.
    return svc.list_daily_schedule_batch_runs(page=page, page_size=10)


@app.get("/api/v1/business-units", response_model=list[BusinessUnit])
def list_user_business_units(
    principal: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> list[BusinessUnit]:
    return svc.list_business_units_for_user(principal.user_id)


@app.get("/api/v1/admin/business-units", response_model=list[BusinessUnit])
def list_admin_business_units(
    include_inactive: bool = Query(default=True),
    _: AuthPrincipal = Depends(require_any_scope("screening.admin", "screening.useradmin")),
    svc: ScreeningService = Depends(get_service),
) -> list[BusinessUnit]:
    return svc.list_all_business_units(include_inactive=include_inactive)


@app.post("/api/v1/admin/business-units", response_model=BusinessUnit)
def create_admin_business_unit(
    payload: BusinessUnitUpsertRequest,
    principal: AuthPrincipal = Depends(require_any_scope("screening.admin", "screening.useradmin")),
    svc: ScreeningService = Depends(get_service),
) -> BusinessUnit:
    try:
        return svc.create_business_unit(
            business_unit_code=payload.business_unit_code,
            business_unit_name=payload.business_unit_name,
            business_unit_short_code=payload.bu_short_code,
            actor_user_id=principal.user_id,
            actor_user_name=_preferred_actor_name(principal),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/v1/admin/business-units/{business_unit_code}", response_model=BusinessUnit)
def update_admin_business_unit(
    business_unit_code: str,
    payload: BusinessUnitUpdateRequest,
    principal: AuthPrincipal = Depends(require_any_scope("screening.admin", "screening.useradmin")),
    svc: ScreeningService = Depends(get_service),
) -> BusinessUnit:
    try:
        updated = svc.update_business_unit(
            business_unit_code=business_unit_code,
            next_business_unit_code=payload.business_unit_code,
            next_business_unit_name=payload.business_unit_name,
            next_business_unit_short_code=payload.bu_short_code,
            actor_user_id=principal.user_id,
            actor_user_name=_preferred_actor_name(principal),
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Business Unit {business_unit_code} not found")
        return updated
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/v1/admin/business-units/{business_unit_code}")
def delete_admin_business_unit(
    business_unit_code: str,
    principal: AuthPrincipal = Depends(require_any_scope("screening.admin", "screening.useradmin")),
    svc: ScreeningService = Depends(get_service),
) -> dict[str, str]:
    removed = svc.delete_business_unit(
        business_unit_code=business_unit_code,
        actor_user_id=principal.user_id,
        actor_user_name=_preferred_actor_name(principal),
    )
    if not removed:
        raise HTTPException(status_code=404, detail=f"Business Unit {business_unit_code} not found")
    return {"status": "removed", "business_unit_code": _normalize_business_unit_code(business_unit_code)}


@app.get("/api/v1/admin/business-unit-mappings", response_model=list[UserBusinessUnitMapping])
def list_admin_business_unit_mappings(
    _: AuthPrincipal = Depends(require_any_scope("screening.admin", "screening.useradmin")),
    svc: ScreeningService = Depends(get_service),
) -> list[UserBusinessUnitMapping]:
    return svc.list_user_business_unit_mappings()


@app.get("/api/v1/admin/users", response_model=list[AdminUserOption])
def list_admin_users(
    _: AuthPrincipal = Depends(require_any_scope("screening.admin", "screening.useradmin")),
    svc: ScreeningService = Depends(get_service),
) -> list[AdminUserOption]:
    return svc.list_admin_users()


@app.put("/api/v1/admin/business-unit-mappings/{user_id}", response_model=UserBusinessUnitMapping)
def upsert_admin_business_unit_mapping(
    user_id: str,
    payload: UserBusinessUnitUpdateRequest,
    principal: AuthPrincipal = Depends(require_any_scope("screening.admin", "screening.useradmin")),
    svc: ScreeningService = Depends(get_service),
) -> UserBusinessUnitMapping:
    try:
        return svc.set_user_business_unit_mapping(
            user_id=user_id,
            user_name=payload.user_name,
            business_unit_codes=payload.business_unit_codes,
            actor_user_id=principal.user_id,
            actor_user_name=_preferred_actor_name(principal),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/screenings/submissions", response_model=list[dict[str, Any]])
def list_screening_submissions(
    limit: int = Query(default=200, ge=1, le=1000),
    principal: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> list[dict[str, Any]]:
    return svc.list_user_submissions(
        user_id=principal.user_id,
        user_name=_preferred_actor_name(principal),
        limit=limit,
    )


@app.get("/api/v1/screenings/summary", response_model=dict[str, int])
def get_screening_summary(
    principal: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> dict[str, int]:
    return svc.get_user_result_summary(
        user_id=principal.user_id,
        user_name=_preferred_actor_name(principal),
    )


@app.get("/api/v1/screenings/types", response_model=list[ScreeningTypeOption])
def list_screening_types(
    business_unit_code: str = Query(default=""),
    principal: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> list[ScreeningTypeOption]:
    try:
        return svc.list_screening_type_options(
            user_id=principal.user_id,
            business_unit_code=_normalize_business_unit_code(business_unit_code) or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/screenings/results", response_model=list[dict[str, Any]])
def list_recent_screening_results(
    limit: int = Query(default=1000, ge=1, le=5000),
    principal: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> list[dict[str, Any]]:
    return svc.list_user_recent_results(
        user_id=principal.user_id,
        user_name=_preferred_actor_name(principal),
        limit=limit,
    )


@app.get("/api/v1/screenings/daily-schedules/{schedule_id}/subscriptions", response_model=list[ScheduleSubscription])
def list_daily_schedule_subscriptions(
    schedule_id: int,
    principal: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> list[ScheduleSubscription]:
    return svc.list_schedule_subscriptions(schedule_id=schedule_id, user_id=principal.user_id)


@app.post("/api/v1/screenings/daily-schedules/{schedule_id}/subscriptions", response_model=ScheduleSubscription)
def subscribe_daily_schedule(
    schedule_id: int,
    email: str = Query(default=""),
    principal: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> ScheduleSubscription:
    safe_email = _normalize_subscription_email(email) or _normalize_subscription_email(principal.email)
    if not safe_email:
        raise HTTPException(status_code=400, detail="email is required")
    if not _is_allowed_subscription_email(safe_email):
        raise HTTPException(status_code=400, detail=f"Only @{_SUBSCRIPTION_EMAIL_DOMAIN} email addresses are allowed")
    return svc.subscribe_to_schedule(
        schedule_id=schedule_id,
        user_id=principal.user_id,
        user_name=_preferred_actor_name(principal),
        email=safe_email,
    )


@app.delete("/api/v1/screenings/daily-schedules/{schedule_id}/subscriptions")
def unsubscribe_daily_schedule(
    schedule_id: int,
    email: str = Query(default=""),
    principal: AuthPrincipal = Depends(require_any_scope("screening.read")),
    svc: ScreeningService = Depends(get_service),
) -> dict[str, str | int]:
    safe_email = _normalize_subscription_email(email) or _normalize_subscription_email(principal.email)
    if not safe_email:
        raise HTTPException(status_code=400, detail="email is required")
    if not _is_allowed_subscription_email(safe_email):
        raise HTTPException(status_code=400, detail=f"Only @{_SUBSCRIPTION_EMAIL_DOMAIN} email addresses are allowed")
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
    schedule_id: int,
    user_id: str | None = Query(default=None),
    user_name: str | None = Query(default=None),
    principal: AuthPrincipal = Depends(require_any_scope("screening.daily", "screening.admin")),
    svc: ScreeningService = Depends(get_service),
) -> dict[str, str | int]:
    actor_user_id = principal.user_id if principal.user_id else user_id
    actor_user_name = _preferred_actor_name(principal, user_name)
    removed = svc.remove_daily_schedule(schedule_id, user_id=actor_user_id, user_name=actor_user_name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Daily schedule {schedule_id} not found")
    return {"status": "removed", "schedule_id": schedule_id}


@app.post("/api/v1/screenings/daily-schedules/{schedule_id}/rerun", response_model=MatchJobAccepted)
def rerun_daily_schedule(
    schedule_id: int,
    principal: AuthPrincipal = Depends(require_any_scope("screening.daily", "screening.admin")),
    svc: ScreeningService = Depends(get_service),
) -> MatchJobAccepted:
    try:
        return svc.rerun_daily_schedule(
            schedule_id=schedule_id,
            actor_user_id=principal.user_id,
            actor_user_name=_preferred_actor_name(principal),
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc


@app.get("/api/v1/audit-events", response_model=list[AuditEvent])
def list_audit_events(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user_id: str | None = Query(default=None),
    _: AuthPrincipal = Depends(require_any_scope("screening.admin", "screening.useradmin")),
    svc: ScreeningService = Depends(get_service),
) -> list[AuditEvent]:
    return svc.list_audit_events(limit=limit, user_id=user_id, offset=offset)


@app.get("/api/v1/audit-events/page", response_model=AuditEventPage)
def list_audit_events_page(
    limit: int = Query(default=100, ge=1, le=300),
    offset: int = Query(default=0, ge=0),
    user_id: str | None = Query(default=None),
    errors_only: bool = Query(default=False),
    _: AuthPrincipal = Depends(require_any_scope("screening.admin", "screening.useradmin")),
    svc: ScreeningService = Depends(get_service),
) -> AuditEventPage:
    return svc.list_audit_events_page(limit=limit, user_id=user_id, offset=offset, errors_only=errors_only)


@app.post("/api/v1/screenings/match", response_model=EntityMatchResponse)
def match_sync(
    payload: MatchJobRequest,
    request: Request,
    principal: AuthPrincipal = Depends(require_any_scope("screening.write", "screening.single.mock", "screening.admin")),
) -> EntityMatchResponse:
    if not payload.queries:
        raise HTTPException(status_code=400, detail="At least one query is required")

    if not payload.mock_screening and not principal_has_permission(principal, "screening.write", "screening.admin"):
        raise HTTPException(status_code=403, detail="Viewer can perform only mock single screening")

    actor_user_name = _preferred_actor_name(principal, payload.user_name)
    normalized_business_unit_code = _normalize_business_unit_code(payload.business_unit_code)
    if not normalized_business_unit_code:
        raise HTTPException(status_code=400, detail="Business Unit is required")
    if not repository.user_has_business_unit(principal.user_id, normalized_business_unit_code):
        raise HTTPException(status_code=403, detail="Selected Business Unit is not mapped to this user")
    correlation_id = _request_correlation_id(request)
    payload = payload.model_copy(
        update={"user_id": principal.user_id, "user_name": actor_user_name, "correlation_id": correlation_id}
    )
    _, job_id = repository.create_job(
        job_id=None,
        total_items=len(payload.queries),
        status=JobStatus.processing,
        user_id=payload.user_id,
        user_name=payload.user_name,
    )
    repository.upsert_job_metadata(
        job_id=job_id,
        mode="SINGLE",
        screening_types=payload.screening_types,
        mock_screening=payload.mock_screening,
        query_count=len(payload.queries),
        business_unit_code=normalized_business_unit_code,
    )
    repository.add_audit_event(
        action="SYNC_SCREENING_SUBMITTED",
        user_id=payload.user_id,
        user_name=payload.user_name,
        entity_type="sync_screening",
        entity_id=job_id,
        details={
            "job_id": job_id,
            "total_items": len(payload.queries),
            "screening_types": payload.screening_types,
            "mock_screening": payload.mock_screening,
            "business_unit_code": normalized_business_unit_code,
            "correlation_id": correlation_id,
        },
    )

    responses: dict[str, dict] = {}
    for item_key, query in payload.queries.items():
        query_for_screening = query.model_copy(deep=True)
        request_props = dict(query_for_screening.properties if isinstance(query_for_screening.properties, dict) else {})
        party_keys_by_type = _build_single_party_keys_by_screening_type(payload.screening_types)
        primary_party_key = next(iter(party_keys_by_type.values()), "")
        if primary_party_key:
            request_props["partyKey"] = primary_party_key
        request_props["partyKeysByScreeningType"] = party_keys_by_type
        if normalized_business_unit_code:
            request_props["businessUnit"] = normalized_business_unit_code
        query_for_screening.properties = request_props
        request_payload = query_for_screening.model_dump(mode="json")
        repository.add_job_item(job_id=job_id, item_key=item_key, request_payload=request_payload)
        repository.add_audit_event(
            action="SYNC_SCREENING_API_CALL_STARTED",
            user_id=payload.user_id,
            user_name=payload.user_name,
            entity_type="sync_screening_item",
            entity_id=f"{job_id}:{item_key}",
            details={
                "job_id": job_id,
                "item_key": item_key,
                "provider": settings.actimize_provider,
                "operation": "screen_many_types",
                "screening_types": payload.screening_types,
                "mock_screening": payload.mock_screening,
                "business_unit_code": normalized_business_unit_code,
                "correlation_id": correlation_id,
                "request": request_payload,
            },
        )
        try:
            screened = actimize.screen_many_types(
                query_for_screening,
                payload.screening_types,
                payload.mock_screening,
                requester_name=actor_user_name,
            )
            normalized_payload = _trim_screening_match_payload(
                screened,
                settings.screening_result_limit,
                fallback_query=request_payload,
            )
            responses[item_key] = normalized_payload
            repository.mark_item_completed(job_id=job_id, item_key=item_key, response_payload=responses[item_key])
            repository.add_audit_event(
                action="SYNC_SCREENING_API_CALL_SUCCEEDED",
                user_id=payload.user_id,
                user_name=payload.user_name,
                entity_type="sync_screening_item",
                entity_id=f"{job_id}:{item_key}",
                details={
                    "job_id": job_id,
                    "item_key": item_key,
                    "provider": settings.actimize_provider,
                    "operation": "screen_many_types",
                    "screening_types": payload.screening_types,
                    "mock_screening": payload.mock_screening,
                    "business_unit_code": normalized_business_unit_code,
                    "correlation_id": correlation_id,
                    "result_count": _count_match_candidates(normalized_payload),
                    "result": responses[item_key],
                },
            )
        except Exception as exc:  # noqa: BLE001
            provider, operation, endpoint, status_code, api_details = _resolve_external_api_context(exc)

            repository.add_external_api_error(
                provider=provider,
                operation=operation,
                endpoint=endpoint,
                status_code=status_code,
                user_id=payload.user_id,
                user_name=payload.user_name,
                job_id=job_id,
                item_key=item_key,
                error_text=str(exc),
                details={
                    "query": request_payload,
                    "screening_types": payload.screening_types,
                    "mock_screening": payload.mock_screening,
                    "business_unit_code": normalized_business_unit_code,
                    "correlation_id": correlation_id,
                    **api_details,
                },
            )
            repository.add_audit_event(
                action="SYNC_SCREENING_API_CALL_FAILED",
                user_id=payload.user_id,
                user_name=payload.user_name,
                entity_type="sync_screening_item",
                entity_id=f"{job_id}:{item_key}",
                details={
                    "job_id": job_id,
                    "item_key": item_key,
                    "provider": provider,
                    "operation": operation,
                    "endpoint": endpoint,
                    "status_code": status_code,
                    "screening_types": payload.screening_types,
                    "mock_screening": payload.mock_screening,
                    "business_unit_code": normalized_business_unit_code,
                    "correlation_id": correlation_id,
                    "request": request_payload,
                    "error": str(exc),
                    **api_details,
                },
            )
            repository.add_audit_event(
                action="SYNC_SCREENING_ITEM_FAILED",
                user_id=payload.user_id,
                user_name=payload.user_name,
                entity_type="sync_screening_item",
                entity_id=item_key,
                details={"job_id": job_id, "item_key": item_key, "error": str(exc), "correlation_id": correlation_id},
            )
            repository.mark_item_failed(job_id=job_id, item_key=item_key, error_text=str(exc))
            responses[item_key] = {
                "results": [],
                "total": {"value": 0, "relation": "eq"},
                "query": request_payload,
                "status": 500,
                "error_text": str(exc),
            }

    return EntityMatchResponse.model_validate(
        {
            "responses": responses,
            "limit": settings.screening_result_limit,
        }
    )
