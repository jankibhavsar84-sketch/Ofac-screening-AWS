from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

import boto3

from .actimize import ActimizeClient
from .config import settings
from .models import (
    ActimizeAlertCallbackAccepted,
    ActimizeAlertCallbackRequest,
    AdminUserOption,
    AuditEvent,
    AuditEventPage,
    BusinessUnit,
    DailyScheduleBatchRunStatus,
    DailyScheduleInfo,
    EntityMatchResponse,
    EntityMatches,
    JobStatus,
    MatchJobAccepted,
    MatchJobProgress,
    MatchJobRequest,
    ScreeningTypeOption,
    ScheduleSubscription,
    ScreeningQueueMessage,
    UserBusinessUnitMapping,
)
from .queue import SqsQueue
from .repository import JobRepository
from .sns_notifier import SnsNotifier


class ScreeningService:
    def __init__(self, repository: JobRepository, queue: SqsQueue, notifier: SnsNotifier | None = None) -> None:
        self.repository = repository
        self.queue = queue
        self.notifier = notifier

    def _normalize_requested_screening_types(self, screening_types: list[str] | None) -> list[str]:
        normalized_types, unresolved_types = self.repository.normalize_active_screening_types(screening_types)
        if unresolved_types and not normalized_types:
            unresolved = ", ".join(unresolved_types)
            raise ValueError(f"Unsupported or inactive screening type(s): {unresolved}")
        return normalized_types

    @staticmethod
    def _extract_cognito_user_pool_id(auth_issuer: str) -> str:
        issuer = (auth_issuer or "").strip().rstrip("/")
        if not issuer:
            return ""
        # Expected issuer format:
        # https://cognito-idp.<region>.amazonaws.com/<user_pool_id>
        match = re.match(r"^https://cognito-idp\.[^.]+\.amazonaws\.com/([A-Za-z0-9_-]+)$", issuer)
        if not match:
            return ""
        return match.group(1).strip()

    def _list_cognito_users(self) -> list[dict[str, str]]:
        user_pool_id = self._extract_cognito_user_pool_id(settings.auth_issuer)
        if not user_pool_id:
            return []

        client = boto3.client("cognito-idp", region_name=settings.aws_region or None)
        token: str | None = None
        users: list[dict[str, str]] = []

        while True:
            kwargs: dict[str, Any] = {"UserPoolId": user_pool_id, "Limit": 60}
            if token:
                kwargs["PaginationToken"] = token
            page = client.list_users(**kwargs)
            for item in page.get("Users", []) or []:
                attrs_raw = item.get("Attributes") or []
                attrs = {
                    str(attr.get("Name") or "").strip(): str(attr.get("Value") or "").strip()
                    for attr in attrs_raw
                    if str(attr.get("Name") or "").strip()
                }
                user_id = attrs.get("sub") or str(item.get("Username") or "").strip()
                if not user_id:
                    continue
                email = attrs.get("email", "").strip()
                preferred = attrs.get("preferred_username", "").strip()
                full_name = attrs.get("name", "").strip()
                username = str(item.get("Username") or "").strip()
                if full_name and email and full_name.lower() != email.lower():
                    display_name = f"{full_name} ({email})"
                else:
                    display_name = full_name or email or preferred or username or user_id
                users.append({"user_id": user_id, "display_name": display_name})
            token = page.get("PaginationToken")
            if not token:
                break

        return users

    def submit_job(self, payload: MatchJobRequest) -> MatchJobAccepted:
        has_deferred_batch_source = bool((payload.source_upload_id or "").strip())
        if not payload.queries and not has_deferred_batch_source:
            raise ValueError("At least one query is required")
        if payload.daily_screening and not (payload.batch_name and payload.batch_name.strip()):
            raise ValueError("batch_name is required when daily_screening is enabled")

        normalized_screening_types = self._normalize_requested_screening_types(payload.screening_types)
        daily_schedule_id: str | None = None
        scheduled_next_run_at: str | None = None
        source_schedule_id = (payload.schedule_id or "").strip() or None
        business_unit_code = self._normalize_business_unit_code(payload.business_unit_code)
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
        correlation_id = str(payload.correlation_id or "").strip() or str(uuid4())
        payload = payload.model_copy(update={"correlation_id": correlation_id, "screening_types": normalized_screening_types})

        if payload.daily_screening:
            self._validate_business_unit_access(payload.user_id, business_unit_code)
            schedule_id = source_schedule_id or str(uuid4())
            daily_schedule_id, created = self.repository.create_or_update_daily_schedule(
                schedule_id=schedule_id,
                batch_name=payload.batch_name.strip(),
                user_id=payload.user_id,
                user_name=payload.user_name,
                business_unit_code=business_unit_code,
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
            business_unit_code = self._normalize_business_unit_code((schedule_snapshot or {}).get("business_unit_code")) or business_unit_code
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
                    "business_unit_code": business_unit_code,
                    "correlation_id": correlation_id,
                },
            )
        elif source_schedule_id:
            schedule_snapshot = self.repository.get_daily_schedule(source_schedule_id)
            if not schedule_snapshot:
                raise ValueError(f"Daily schedule {source_schedule_id} not found")
            schedule_frequency = self.repository.normalize_schedule_frequency(schedule_snapshot.get("schedule_frequency"))
            business_unit_code = self._normalize_business_unit_code(schedule_snapshot.get("business_unit_code"))
            if not business_unit_code:
                raise ValueError("Business Unit is required for scheduled screening")
        else:
            self._validate_business_unit_access(payload.user_id, business_unit_code)

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
                business_unit_code=business_unit_code,
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
                    "business_unit_code": business_unit_code,
                    "correlation_id": correlation_id,
                },
            )
            return MatchJobAccepted(
                job_id=job_id,
                status=JobStatus.completed,
                submitted_at=submitted_at,
                total_items=0,
                business_unit_code=business_unit_code or None,
                daily_schedule_id=daily_schedule_id,
                screened_item_keys=[],
            )

        if not base_queries and source_upload_id:
            job_id = str(uuid4())
            submitted_at = self.repository.create_job(
                job_id=job_id,
                total_items=0,
                status=JobStatus.queued,
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
                query_count=0,
                business_unit_code=business_unit_code,
            )
            self.queue.enqueue(
                ScreeningQueueMessage(
                    message_type="JOB_DISPATCH",
                    job_id=job_id,
                    submitted_at=submitted_at,
                    screening_types=payload.screening_types,
                    mock_screening=payload.mock_screening,
                    user_id=payload.user_id,
                    user_name=payload.user_name,
                    correlation_id=correlation_id,
                    business_unit_code=business_unit_code or None,
                    source_schedule_id=source_schedule_id,
                    source_upload_id=source_upload_id,
                )
            )
            self.repository.add_audit_event(
                action="SCREENING_JOB_SUBMITTED",
                user_id=payload.user_id,
                user_name=payload.user_name,
                entity_type="screening_job",
                entity_id=job_id,
                details={
                    "total_items": 0,
                    "screening_types": payload.screening_types,
                    "daily_screening": payload.daily_screening,
                    "batch_name": payload.batch_name,
                    "mock_screening": payload.mock_screening,
                    "source_schedule_id": source_schedule_id,
                    "source_upload_id": source_upload_id,
                    "skipped_existing_records": 0,
                    "business_unit_code": business_unit_code,
                    "correlation_id": correlation_id,
                    "dispatch_mode": "DEFERRED_SOURCE_UPLOAD",
                },
            )
            return MatchJobAccepted(
                job_id=job_id,
                status=JobStatus.queued,
                submitted_at=submitted_at,
                total_items=0,
                business_unit_code=business_unit_code or None,
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
                business_unit_code=business_unit_code,
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
                    "business_unit_code": business_unit_code,
                    "correlation_id": correlation_id,
                },
            )
            return MatchJobAccepted(
                job_id=job_id,
                status=JobStatus.completed,
                submitted_at=submitted_at,
                total_items=0,
                business_unit_code=business_unit_code or None,
                daily_schedule_id=daily_schedule_id,
                screened_item_keys=[],
            )

        screening_types_for_dispatch = self._resolve_dispatch_screening_types(payload.screening_types)
        expected_item_total = len(queries_for_job) * len(screening_types_for_dispatch)
        actimize = ActimizeClient(repository=self.repository)

        job_id = str(uuid4())
        submitted_at = self.repository.create_job(
            job_id=job_id,
            total_items=expected_item_total,
            source_schedule_id=source_schedule_id,
            source_upload_id=source_upload_id,
            user_id=payload.user_id,
            user_name=payload.user_name,
        )
        self.repository.upsert_job_metadata(
            job_id=job_id,
            mode=inferred_mode,
            screening_types=screening_types_for_dispatch,
            mock_screening=payload.mock_screening,
            batch_name=payload.batch_name,
            daily_screening=bool(payload.daily_screening or source_schedule_id),
            schedule_frequency=schedule_frequency if (payload.daily_screening or source_schedule_id) else None,
            daily_schedule_id=source_schedule_id,
            query_count=len(base_queries),
            business_unit_code=business_unit_code,
        )

        safe_business_unit_code = self._normalize_business_unit_code(business_unit_code)
        is_single_mode = inferred_mode == "SINGLE"
        for item_key in queries_for_job:
            query = payload.queries[item_key]
            safe_item_key = str(item_key or "").strip()
            base_props = query.properties if isinstance(query.properties, dict) else {}

            party_keys_by_screening_type: dict[str, str] = {}
            for screening_type in screening_types_for_dispatch:
                if is_single_mode:
                    party_key = actimize.build_on_demand_party_key(screening_type)
                else:
                    party_key = actimize.build_batch_party_key(safe_item_key, screening_type)
                if party_key:
                    party_keys_by_screening_type[screening_type] = party_key

            for screening_type in screening_types_for_dispatch:
                per_type_party_key = party_keys_by_screening_type.get(screening_type, "")
                per_type_item_key = (
                    self._build_screening_item_key(safe_item_key, screening_type)
                    if is_single_mode
                    else self._build_batch_screening_item_key(safe_item_key, screening_type)
                )
                per_type_props = dict(base_props)
                if per_type_party_key:
                    per_type_props["partyKey"] = per_type_party_key
                    per_type_props["partyKeysByScreeningType"] = {screening_type: per_type_party_key}
                per_type_props["screeningType"] = screening_type
                if safe_business_unit_code:
                    per_type_props["businessUnit"] = safe_business_unit_code

                per_type_query = query.model_copy(update={"properties": per_type_props})
                per_type_request_payload = per_type_query.model_dump(mode="json")
                self.repository.add_job_item(
                    job_id=job_id,
                    item_key=per_type_item_key,
                    request_payload=per_type_request_payload,
                )

                queue_message = ScreeningQueueMessage(
                    job_id=job_id,
                    item_key=per_type_item_key,
                    query=per_type_query,
                    submitted_at=submitted_at,
                    screening_types=[screening_type],
                    mock_screening=payload.mock_screening,
                    user_id=payload.user_id,
                    user_name=payload.user_name,
                    correlation_id=correlation_id,
                    business_unit_code=safe_business_unit_code or None,
                    source_schedule_id=source_schedule_id,
                    source_record_hash=record_hashes.get(item_key),
                )
                self.repository.add_audit_event(
                    action="SQS_ENQUEUE_STARTED",
                    user_id=payload.user_id,
                    user_name=payload.user_name,
                    entity_type="screening_queue_item",
                    entity_id=f"{job_id}:{per_type_item_key}",
                    details={
                        "job_id": job_id,
                        "item_key": per_type_item_key,
                        "source_item_key": item_key,
                        "queue_name": settings.aws_sqs_queue_name,
                        "source_schedule_id": source_schedule_id,
                        "screening_types": [screening_type],
                        "mock_screening": payload.mock_screening,
                        "correlation_id": correlation_id,
                        "request": per_type_request_payload,
                    },
                )
                try:
                    self.queue.enqueue(queue_message)
                    self.repository.add_audit_event(
                        action="SQS_ENQUEUED",
                        user_id=payload.user_id,
                        user_name=payload.user_name,
                        entity_type="screening_queue_item",
                        entity_id=f"{job_id}:{per_type_item_key}",
                        details={
                            "job_id": job_id,
                            "item_key": per_type_item_key,
                            "source_item_key": item_key,
                            "queue_name": settings.aws_sqs_queue_name,
                            "source_schedule_id": source_schedule_id,
                            "correlation_id": correlation_id,
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    self.repository.add_audit_event(
                        action="SQS_ENQUEUE_FAILED",
                        user_id=payload.user_id,
                        user_name=payload.user_name,
                        entity_type="screening_queue_item",
                        entity_id=f"{job_id}:{per_type_item_key}",
                        details={
                            "job_id": job_id,
                            "item_key": per_type_item_key,
                            "source_item_key": item_key,
                            "queue_name": settings.aws_sqs_queue_name,
                            "source_schedule_id": source_schedule_id,
                            "correlation_id": correlation_id,
                            "error": str(exc),
                        },
                    )
                    raise

        self.repository.add_audit_event(
            action="SCREENING_JOB_SUBMITTED",
            user_id=payload.user_id,
            user_name=payload.user_name,
            entity_type="screening_job",
            entity_id=job_id,
            details={
                "total_items": expected_item_total,
                "query_count": len(queries_for_job),
                "screening_type_count": len(screening_types_for_dispatch),
                "screening_types": screening_types_for_dispatch,
                "daily_screening": payload.daily_screening,
                "batch_name": payload.batch_name,
                "mock_screening": payload.mock_screening,
                "source_schedule_id": source_schedule_id,
                "source_upload_id": source_upload_id,
                "skipped_existing_records": skipped_existing_records,
                "business_unit_code": business_unit_code,
                "correlation_id": correlation_id,
            },
        )

        return MatchJobAccepted(
            job_id=job_id,
            status=JobStatus.queued,
            submitted_at=submitted_at,
            total_items=expected_item_total,
            business_unit_code=business_unit_code or None,
            daily_schedule_id=daily_schedule_id,
            screened_item_keys=list(queries_for_job.keys()),
        )

    @staticmethod
    def _normalize_business_unit_code(value: str | None) -> str:
        return str(value or "").strip().upper()

    @staticmethod
    def _resolve_dispatch_screening_types(screening_types: list[str] | None) -> list[str]:
        resolved: list[str] = []
        seen: set[str] = set()
        for raw in screening_types or []:
            safe = str(raw or "").strip()
            if not safe:
                continue
            dedupe_key = safe.lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            resolved.append(safe)
        return resolved or ["Sanction"]

    @staticmethod
    def _build_screening_item_key(base_item_key: str, screening_type: str) -> str:
        safe_base = str(base_item_key or "").strip()
        safe_type = str(screening_type or "").strip()
        if safe_base and safe_type:
            return f"{safe_base}::{safe_type}"
        return safe_base or safe_type

    @staticmethod
    def _build_batch_screening_item_key(base_item_key: str, screening_type: str) -> str:
        safe_base = str(base_item_key or "").strip()
        safe_type = str(screening_type or "").strip()
        if safe_base and safe_type:
            return f"{safe_base}_{safe_type}"
        return safe_base or safe_type

    @staticmethod
    def _parse_job_status(value: Any) -> JobStatus:
        raw_value = str(value or "").strip().upper()
        for candidate in JobStatus:
            if candidate.value == raw_value:
                return candidate
        return JobStatus.processing

    def _validate_business_unit_access(self, user_id: str | None, business_unit_code: str | None) -> str:
        safe_code = self._normalize_business_unit_code(business_unit_code)
        if not safe_code:
            raise ValueError("Business Unit is required")
        safe_user_id = str(user_id or "").strip()
        if safe_user_id and not self.repository.user_has_business_unit(safe_user_id, safe_code):
            raise ValueError("Selected Business Unit is not mapped to this user")
        return safe_code

    def get_progress(self, job_id: str) -> MatchJobProgress | None:
        snapshot = self.repository.get_job_snapshot(job_id)
        if not snapshot:
            return None

        status = self._parse_job_status(snapshot["status"])

        progress = MatchJobProgress(
            job_id=snapshot["job_id"],
            status=status,
            submitted_at=str(snapshot.get("created_at") or ""),
            total_items=snapshot["total_items"],
            completed_items=snapshot["counts"]["completed"],
            failed_items=snapshot["counts"]["failed"],
            pending_items=snapshot["counts"]["pending"],
            processing_items=snapshot["counts"]["processing"],
        )

        # Some jobs (e.g., large batch uploads) may be created before per-item records exist.
        # In that case, treat missing job_items as pending work rather than a terminal job.
        accounted = progress.completed_items + progress.failed_items + progress.pending_items + progress.processing_items
        inferred_pending = max(0, progress.total_items - (progress.completed_items + progress.failed_items + progress.processing_items))
        if progress.pending_items == 0 and inferred_pending > 0 and accounted < progress.total_items:
            progress.pending_items = inferred_pending

        is_terminal = (progress.completed_items + progress.failed_items) >= progress.total_items and progress.processing_items == 0
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
                            "error_text": str(item.get("error_text") or "").strip() or None,
                        }
                    )

            if status == JobStatus.failed:
                progress.status = JobStatus.failed
            else:
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
    def _normalize_screening_type_key(value: str | None) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).lower()

    @classmethod
    def _build_screening_type_lookup(cls, mapping_rows: list[dict[str, Any]]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for row in mapping_rows:
            screening_type = str(row.get("screening_type") or "").strip()
            search_definition_id = str(row.get("search_definition_id") or "").strip()
            search_definition_name = str(row.get("search_definition_name") or "").strip()
            if not screening_type:
                continue
            for candidate in (screening_type, search_definition_id, search_definition_name):
                normalized = cls._normalize_screening_type_key(candidate)
                if normalized and normalized not in lookup:
                    lookup[normalized] = screening_type
        return lookup

    @classmethod
    def _canonical_screening_type(cls, value: Any, screening_type_lookup: dict[str, str] | None) -> str:
        safe_value = str(value or "").strip()
        if not safe_value:
            return ""
        normalized = cls._normalize_screening_type_key(safe_value)
        if screening_type_lookup and normalized:
            mapped = str(screening_type_lookup.get(normalized) or "").strip()
            if mapped:
                return mapped
        return safe_value

    @classmethod
    def _extract_responses_by_screening_type(cls, matches: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        if not isinstance(matches, dict):
            return {}
        raw_mapping = matches.get("responses_by_screening_type")
        if not isinstance(raw_mapping, dict):
            raw_mapping = {}

        normalized: dict[str, dict[str, Any]] = {}
        for raw_key, raw_value in raw_mapping.items():
            if not isinstance(raw_value, dict):
                continue
            candidates = [
                str(raw_key or "").strip(),
                str(raw_value.get("requested_screening_type") or "").strip(),
            ]
            for candidate in candidates:
                normalized_key = cls._normalize_screening_type_key(candidate)
                if normalized_key and normalized_key not in normalized:
                    normalized[normalized_key] = raw_value
        return normalized

    @classmethod
    def _response_for_screening_type(
        cls,
        matches: dict[str, Any],
        screening_type: str | None,
    ) -> dict[str, Any]:
        per_type = cls._extract_responses_by_screening_type(matches)
        if not per_type:
            return matches
        normalized_type = cls._normalize_screening_type_key(screening_type)
        if normalized_type and normalized_type in per_type:
            return per_type[normalized_type]
        if len(per_type) == 1:
            return next(iter(per_type.values()))
        return matches

    @classmethod
    def _resolve_screening_types_for_item(
        cls,
        request_payload: dict[str, Any] | None,
        matches: dict[str, Any] | None,
        default_screening_types: list[str] | None,
        screening_type_lookup: dict[str, str] | None = None,
    ) -> list[str]:
        resolved: list[str] = []
        seen: set[str] = set()

        def _append(raw_value: Any) -> None:
            safe_value = cls._canonical_screening_type(raw_value, screening_type_lookup)
            if not safe_value:
                return
            dedupe_key = cls._normalize_screening_type_key(safe_value)
            if not dedupe_key or dedupe_key in seen:
                return
            seen.add(dedupe_key)
            resolved.append(safe_value)

        props = (request_payload or {}).get("properties")
        if isinstance(props, dict):
            for key in ("screeningType", "screening_type"):
                raw_value = props.get(key)
                if isinstance(raw_value, list):
                    for candidate in raw_value:
                        _append(candidate)
                else:
                    _append(raw_value)

        per_type = cls._extract_responses_by_screening_type(matches if isinstance(matches, dict) else {})
        for response_payload in per_type.values():
            if not isinstance(response_payload, dict):
                continue
            _append(response_payload.get("requested_screening_type"))

        if resolved:
            return resolved

        for screening_type in default_screening_types or []:
            _append(screening_type)
        return resolved or [""]

    @staticmethod
    def _classify_single_result(matches: dict[str, Any]) -> str:
        if not isinstance(matches, dict):
            return "FAILED"
        status = matches.get("status")
        if isinstance(status, int) and status != 200:
            return "FAILED"
        error_text = str(matches.get("error_text") or matches.get("error") or "").strip()
        if error_text:
            return "FAILED"
        engine_message = str(matches.get("engine_message") or "").strip().upper()
        if engine_message == "PM":
            return "HIT"
        if engine_message == "NM":
            return "NO_HIT"
        results = matches.get("results", [])
        if not isinstance(results, list):
            return "FAILED"
        for result in results:
            if isinstance(result, dict) and bool(result.get("match")):
                return "HIT"
        return "NO_HIT"

    @classmethod
    def _classify_result_from_matches(cls, matches: dict[str, Any]) -> str:
        if not isinstance(matches, dict):
            return "FAILED"
        per_type = cls._extract_responses_by_screening_type(matches)
        if per_type:
            outcomes = [cls._classify_single_result(response) for response in per_type.values()]
            if any(outcome == "HIT" for outcome in outcomes):
                return "HIT"
            if any(outcome == "FAILED" for outcome in outcomes):
                return "FAILED"
            return "NO_HIT"
        return cls._classify_single_result(matches)

    @staticmethod
    def _extract_string_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item or "").strip() for item in value if str(item or "").strip()]
        if isinstance(value, str):
            safe = value.strip()
            return [safe] if safe else []
        return []

    def _extract_country_from_query(self, query: dict[str, Any] | None) -> str:
        props = (query or {}).get("properties")
        if not isinstance(props, dict):
            return ""

        for key in ("country", "nationality", "countries", "jurisdiction"):
            values = self._extract_string_list(props.get(key))
            if values:
                rendered = ", ".join(dict.fromkeys([value.upper() if len(value) == 2 else value for value in values]))
                if rendered:
                    return rendered
        return ""

    @staticmethod
    def _extract_party_key_from_query(query: dict[str, Any] | None, fallback: str = "") -> str:
        props = (query or {}).get("properties")
        if isinstance(props, dict):
            for key in ("partyKey", "party_key", "party key", "PartyKey"):
                values = props.get(key)
                if isinstance(values, list):
                    for value in values:
                        safe = str(value or "").strip()
                        if safe:
                            return safe
                if isinstance(values, str) and values.strip():
                    return values.strip()
        return str(fallback or "").strip()

    @classmethod
    def _extract_party_key_for_screening_type(
        cls,
        request_payload: dict[str, Any] | None,
        matches: dict[str, Any] | None,
        screening_type: str | None,
        fallback: str = "",
    ) -> str:
        matches_query = matches.get("query") if isinstance(matches, dict) and isinstance(matches.get("query"), dict) else None
        from_matches = cls._extract_party_key_from_query(matches_query, "")
        if from_matches:
            return from_matches

        props = (request_payload or {}).get("properties")
        if isinstance(props, dict):
            raw_mapping = props.get("partyKeysByScreeningType")
            if not isinstance(raw_mapping, dict):
                raw_mapping = props.get("party_keys_by_screening_type")
            if isinstance(raw_mapping, dict):
                normalized_target = cls._normalize_screening_type_key(screening_type)
                if normalized_target:
                    for raw_type, raw_key in raw_mapping.items():
                        if cls._normalize_screening_type_key(raw_type) != normalized_target:
                            continue
                        mapped_value = str(raw_key or "").strip()
                        if mapped_value:
                            return mapped_value

        return cls._extract_party_key_from_query(request_payload, fallback)

    @staticmethod
    def _build_matches_payload(
        item_status: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any] | None,
        error_text: str,
    ) -> dict[str, Any]:
        safe_status = str(item_status or "").strip().upper()
        if safe_status in {JobStatus.queued.value, JobStatus.processing.value}:
            return {
                "results": [],
                "total": {"value": 0, "relation": "eq"},
                "query": request_payload,
                "status": 202,
            }
        if safe_status == JobStatus.failed.value or response_payload is None:
            return {
                "results": [],
                "total": {"value": 0, "relation": "eq"},
                "query": request_payload,
                "status": 500,
                "error_text": error_text or None,
            }
        return response_payload

    @staticmethod
    def _engine_status_from_matches(matches: dict[str, Any]) -> str:
        classification = ScreeningService._classify_result_from_matches(matches)
        status = int(matches.get("status") or 0) if isinstance(matches.get("status"), int) else None
        if status == 202:
            return "PROCESSING"
        if classification == "HIT":
            return "HIT"
        if classification == "NO_HIT":
            return "NO_HIT"
        return "FAILED"

    @staticmethod
    def _ui_status_from_engine(engine_status: str, manual_match: bool = False) -> str:
        if manual_match:
            return "Match"
        if engine_status == "NO_HIT":
            return "Clear"
        if engine_status == "HIT":
            return "Potential Match"
        if engine_status == "PROCESSING":
            return "Pending"
        return "Failed"

    @staticmethod
    def _top_matching_score(matches: dict[str, Any]) -> float | None:
        results = matches.get("results")
        if not isinstance(results, list):
            return None
        scores = [
            float(result.get("score"))
            for result in results
            if isinstance(result, dict) and isinstance(result.get("score"), (int, float))
        ]
        if not scores:
            return None
        return max(scores)

    @staticmethod
    def _parse_json_payload(raw: Any) -> dict[str, Any] | None:
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            parsed = json.loads(raw)
        except Exception:  # noqa: BLE001
            return None
        return parsed if isinstance(parsed, dict) else None

    def _build_recent_result_rows(
        self,
        row: dict[str, Any],
        active_schedule_ids: set[str],
        screening_type_lookup: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        job_id = str(row.get("job_id") or "").strip()
        item_key = str(row.get("item_key") or "").strip()
        if not job_id or not item_key:
            return []

        request_payload = self._parse_json_payload(row.get("request_json")) or {}
        response_payload = self._parse_json_payload(row.get("response_json"))
        item_status = str(row.get("item_status") or "").strip().upper()
        error_text = str(row.get("item_error_text") or "").strip()
        item_matches = self._build_matches_payload(item_status, request_payload, response_payload, error_text)
        ui_type = self._query_to_ui_type(request_payload)
        display_name = self._display_name_from_query(request_payload, item_key)
        job_created_at = str(row.get("created_at") or "").strip()
        submitted_at = str(
            row.get("item_updated_at")
            or row.get("job_updated_at")
            or row.get("created_at")
            or ""
        ).strip()
        screening_types = self._parse_screening_types(row.get("screening_types_json"))
        screening_types = [self._canonical_screening_type(value, screening_type_lookup) for value in screening_types]
        screening_types = [value for value in screening_types if value]
        daily_schedule_id = str(row.get("daily_schedule_id") or row.get("source_schedule_id") or "").strip() or None
        daily_schedule_active = bool(daily_schedule_id and daily_schedule_id in active_schedule_ids)

        mode_raw = str(row.get("mode") or "").strip().upper()
        inferred_mode = (
            "BATCH"
            if row.get("source_upload_id") or row.get("source_schedule_id") or int(row.get("total_items") or 0) > 1
            else "SINGLE"
        )
        mode = mode_raw if mode_raw in {"SINGLE", "BATCH"} else inferred_mode

        submission_stub = {
            "id": job_id,
            "mode": mode,
            "createdAt": job_created_at or submitted_at,
            "createdByUserId": row.get("user_id"),
            "createdByUserName": row.get("user_name"),
            "businessUnitCode": row.get("business_unit_code"),
            "screeningTypes": screening_types,
            "fileName": (
                str(row.get("file_name") or "").strip()
                or str(row.get("upload_file_name") or "").strip()
                or str(row.get("batch_name") or "").strip()
                or "Batch Submission"
            ),
            "dailyScheduleId": daily_schedule_id,
            "dailyScheduleActive": daily_schedule_active,
        }

        screening_types_for_rows = self._resolve_screening_types_for_item(
            request_payload=request_payload,
            matches=item_matches,
            default_screening_types=screening_types,
            screening_type_lookup=screening_type_lookup,
        )
        out: list[dict[str, Any]] = []
        for index, screening_type in enumerate(screening_types_for_rows):
            safe_screening_type = str(screening_type or "").strip()
            if screening_type_lookup:
                safe_screening_type = self._canonical_screening_type(safe_screening_type, screening_type_lookup)
            matches = self._response_for_screening_type(item_matches, safe_screening_type)
            party_key = self._extract_party_key_for_screening_type(
                request_payload,
                matches,
                safe_screening_type,
                fallback=item_key,
            )
            engine_status = self._engine_status_from_matches(matches)
            manual_status_cd = str(matches.get("manual_status_cd") or "").strip().upper()
            manual_match = bool(matches.get("manual_match") is True or manual_status_cd == "T")
            ui_status = self._ui_status_from_engine(engine_status, manual_match=manual_match)
            submission_for_row = dict(submission_stub)
            if safe_screening_type:
                submission_for_row["screeningType"] = safe_screening_type

            if mode == "SINGLE":
                raw = {
                    "submission": submission_for_row,
                    "m": {
                        "key": item_key,
                        "uiType": ui_type,
                        "displayName": display_name,
                    },
                    "matches": matches,
                }
            else:
                raw = {
                    "submission": submission_for_row,
                    "item": {
                        "displayName": display_name,
                        "customerType": "Person" if ui_type == "Individual" else "Entity",
                        "result": engine_status,
                        "details": {
                            "uiType": ui_type,
                            "matches": matches,
                        },
                    },
                }

            row_suffix = safe_screening_type or str(index + 1)
            row_suffix = re.sub(r"[^A-Za-z0-9]+", "_", row_suffix).strip("_") or str(index + 1)
            out.append(
                {
                    "id": f"{job_id}_{item_key}_{row_suffix}",
                    "entity": display_name,
                    "partyKey": party_key,
                    "mode": mode,
                    "type": ui_type,
                    "screeningType": safe_screening_type,
                    "country": self._extract_country_from_query(request_payload),
                    "engineStatus": engine_status,
                    "manualMatch": manual_match,
                    "uiStatus": ui_status,
                    "matchingScore": self._top_matching_score(matches),
                    "submittedAt": submitted_at,
                    "batchSubmissionId": None if mode == "SINGLE" else job_id,
                    "dailyScheduleId": daily_schedule_id,
                    "dailyScheduleActive": daily_schedule_active,
                    "raw": raw,
                }
            )
        return out

    def handle_actimize_alert_callback(
        self,
        payload: ActimizeAlertCallbackRequest,
        correlation_id: str | None = None,
    ) -> ActimizeAlertCallbackAccepted:
        callback_result = self.repository.apply_actimize_alert_callback(
            unique_key=payload.unique_key,
            alert_id=payload.alert_id,
            screening_cd=payload.screening_cd,
            status_cd=payload.status_cd,
            update_timestamp=payload.update_timestamp,
            source_system_cd=payload.source_system_cd,
            tenant_cd=payload.tenant_cd,
            correlation_id=correlation_id,
            raw_payload=payload.model_dump(mode="json"),
        )

        self.repository.add_audit_event(
            action="ACTIMIZE_ALERT_CALLBACK_RECEIVED",
            entity_type="actimize_alert",
            entity_id=payload.alert_id,
            details={
                "unique_key": payload.unique_key,
                "normalized_unique_key": callback_result.get("normalized_unique_key"),
                "status_cd": payload.status_cd,
                "screening_cd": payload.screening_cd,
                "source_system_cd": payload.source_system_cd,
                "tenant_cd": payload.tenant_cd,
                "matched_items": int(callback_result.get("matched_items") or 0),
                "correlation_id": correlation_id,
            },
        )

        return ActimizeAlertCallbackAccepted(
            callback_id=int(callback_result.get("callback_id") or 0),
            unique_key=payload.unique_key,
            alert_id=payload.alert_id,
            status_cd=payload.status_cd,
            matched_items=int(callback_result.get("matched_items") or 0),
            processed_at=str(callback_result.get("processed_at") or ""),
        )

    def list_user_recent_results(self, user_id: str | None, user_name: str | None, limit: int = 1000) -> list[dict[str, Any]]:
        rows = self.repository.list_recent_result_items(user_id=user_id, user_name=user_name, limit=limit)
        screening_type_lookup = self._build_screening_type_lookup(
            self.repository.list_active_actimize_screening_type_mappings()
        )
        active_schedule_ids = {
            str(s.get("schedule_id", "")).strip()
            for s in self.repository.list_active_daily_schedules(user_id=user_id)
            if str(s.get("schedule_id", "")).strip()
        }
        recent_rows: list[dict[str, Any]] = []
        for row in rows:
            mapped_rows = self._build_recent_result_rows(row, active_schedule_ids, screening_type_lookup)
            if mapped_rows:
                recent_rows.extend(mapped_rows)
            if len(recent_rows) >= limit:
                break
        return recent_rows[:limit]

    def get_user_result_summary(self, user_id: str | None, user_name: str | None) -> dict[str, int]:
        return self.repository.get_user_result_summary_counts(user_id=user_id, user_name=user_name)

    def list_user_submissions(self, user_id: str | None, user_name: str | None, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.repository.list_jobs_for_history(user_id=user_id, user_name=user_name, limit=limit)
        items_by_job = self.repository.list_job_items_for_jobs(
            [str(row.get("job_id") or "").strip() for row in rows]
        )
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
            job_items = items_by_job.get(job_id, [])

            mode_raw = str(row.get("mode") or "").strip().upper()
            inferred_mode = (
                "BATCH"
                if row.get("source_upload_id") or row.get("source_schedule_id") or int(row.get("total_items") or 0) > 1
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

                for item in job_items:
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
                            "error_text": str(item.get("error_text") or "").strip() or None,
                        }
                    else:
                        matches = response_payload
                        if self._classify_result_from_matches(matches) == "HIT":
                            any_hit = True

                    meta.append({"key": item_key, "uiType": ui_type, "displayName": display_name})
                    responses[item_key] = matches

                overall = "PROCESSING" if any_processing else "HIT" if any_hit else "FAILED" if any_error else "NO_HIT"
                submissions.append(
                    {
                        "id": job_id,
                        "createdAt": str(row.get("created_at") or ""),
                        "mode": "SINGLE",
                        "createdByUserId": row.get("user_id"),
                        "createdByUserName": row.get("user_name"),
                        "customerType": "Person",
                        "displayName": f"Single Screening ({len(meta)})",
                        "result": overall,
                        "screeningTypes": screening_types,
                        "businessUnitCode": row.get("business_unit_code"),
                        "details": {
                            "meta": meta,
                            "responses": responses,
                            "screeningTypes": screening_types,
                            "mockScreening": bool(row.get("mock_screening")),
                            "businessUnitCode": row.get("business_unit_code"),
                        },
                    }
                )
                continue

            batch_items: list[dict[str, Any]] = []
            has_hit = False
            has_error = False
            has_processing = False

            for item in job_items:
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
                    result = "FAILED"
                    message = str(item.get("error_text") or "Screening failed for this row")
                    matches = {
                        "results": [],
                        "total": {"value": 0, "relation": "eq"},
                        "query": request_payload,
                        "status": 500,
                        "error_text": str(item.get("error_text") or "").strip() or None,
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

            overall = "PROCESSING" if has_processing else "HIT" if has_hit else "FAILED" if has_error else "NO_HIT"
            file_name = (
                str(row.get("file_name") or "").strip()
                or str(row.get("upload_file_name") or "").strip()
                or str(row.get("batch_name") or "").strip()
                or "Batch Submission"
            )
            submissions.append(
                {
                    "id": job_id,
                    "createdAt": str(row.get("created_at") or ""),
                    "mode": "BATCH",
                    "createdByUserId": row.get("user_id"),
                    "createdByUserName": row.get("user_name"),
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
                    "businessUnitCode": row.get("business_unit_code"),
                    "items": batch_items,
                }
            )

        return submissions

    def list_daily_schedules(self) -> list[DailyScheduleInfo]:
        schedules = self.repository.list_active_daily_schedules()
        items: list[DailyScheduleInfo] = []
        for s in schedules:
            total_items = len(s["queries"]) if isinstance(s["queries"], dict) else 0
            if total_items == 0 and str(s.get("source_upload_id") or "").strip():
                upload = self.repository.get_batch_file_upload(str(s.get("source_upload_id") or "").strip())
                total_items = int((upload or {}).get("record_count") or 0)
            items.append(
                DailyScheduleInfo(
                    schedule_id=s["schedule_id"],
                    batch_name=s["batch_name"],
                    user_id=s.get("user_id"),
                    user_name=s.get("user_name"),
                    business_unit_code=s.get("business_unit_code"),
                    screening_types=s["screening_types"] if isinstance(s["screening_types"], list) else [],
                    schedule_frequency=s.get("schedule_frequency", "DAILY"),
                    timezone=s["timezone"],
                    run_hour=int(s["run_hour"]),
                    run_minute=int(s["run_minute"]),
                    created_at=s["created_at"],
                    last_run_at=s["last_run_at"],
                    next_run_at=s["next_run_at"],
                    total_items=total_items,
                    is_active=bool(s["is_active"]),
                    source_file_name=s.get("source_file_name"),
                    source_s3_uri=s.get("source_s3_uri"),
                    source_upload_id=s.get("source_upload_id"),
                )
            )
        return items

    @staticmethod
    def _derive_batch_run_status(
        job_status: str,
        total_items: int,
        completed_items: int,
        failed_items: int,
        pending_items: int,
        processing_items: int,
    ) -> str:
        safe_job_status = str(job_status or "").strip().upper()
        if pending_items > 0 or processing_items > 0:
            return "PROCESSING"
        if total_items <= 0:
            return "COMPLETED" if safe_job_status == JobStatus.completed.value else safe_job_status or "QUEUED"
        if failed_items > 0 and completed_items <= 0:
            return "FAILED"
        if failed_items > 0 and completed_items > 0:
            return "PARTIAL"
        if completed_items > 0:
            return "COMPLETED"
        return safe_job_status or "QUEUED"

    def list_daily_schedule_batch_runs(self, limit: int = 200) -> list[DailyScheduleBatchRunStatus]:
        rows = self.repository.list_daily_schedule_batch_runs(limit=limit)
        runs: list[DailyScheduleBatchRunStatus] = []

        for row in rows:
            total_items = int(row.get("total_items") or 0)
            completed_items = int(row.get("completed_items") or 0)
            failed_items = int(row.get("failed_items") or 0)
            pending_items = int(row.get("pending_items") or 0)
            processing_items = int(row.get("processing_items") or 0)
            job_status = str(row.get("job_status") or "").strip().upper() or "QUEUED"
            run_status = self._derive_batch_run_status(
                job_status=job_status,
                total_items=total_items,
                completed_items=completed_items,
                failed_items=failed_items,
                pending_items=pending_items,
                processing_items=processing_items,
            )

            runs.append(
                DailyScheduleBatchRunStatus(
                    job_id=str(row.get("job_id") or "").strip(),
                    schedule_id=str(row.get("schedule_id") or "").strip(),
                    batch_name=str(row.get("batch_name") or "").strip() or "Scheduled Batch",
                    schedule_frequency=(str(row.get("schedule_frequency") or "").strip() or None),
                    source_file_name=(str(row.get("source_file_name") or "").strip() or None),
                    source_upload_id=(str(row.get("source_upload_id") or "").strip() or None),
                    status=job_status,
                    run_status=run_status,
                    total_items=total_items,
                    completed_items=completed_items,
                    failed_items=failed_items,
                    pending_items=pending_items,
                    processing_items=processing_items,
                    submitted_at=str(row.get("created_at") or ""),
                    updated_at=str(row.get("updated_at") or ""),
                    user_id=(str(row.get("user_id") or "").strip() or None),
                    user_name=(str(row.get("user_name") or "").strip() or None),
                )
            )
        return runs

    def list_screening_type_options(self) -> list[ScreeningTypeOption]:
        rows = self.repository.list_active_actimize_screening_type_mappings()
        options: list[ScreeningTypeOption] = []
        seen_types: set[str] = set()

        for row in rows:
            screening_type = str(row.get("screening_type") or "").strip()
            search_definition_id = str(row.get("search_definition_id") or "").strip()
            search_definition_name = str(row.get("search_definition_name") or "").strip()
            try:
                display_order = int(row.get("display_order") if row.get("display_order") is not None else 1000)
            except (TypeError, ValueError):
                display_order = 1000
            value = screening_type
            if not value:
                continue
            dedupe_key = value.lower()
            if dedupe_key in seen_types:
                continue
            seen_types.add(dedupe_key)
            options.append(
                ScreeningTypeOption(
                    value=value,
                    label=value,
                    screening_type=value,
                    search_definition_id=search_definition_id or value,
                    search_definition_name=search_definition_name or search_definition_id or value,
                    display_order=display_order,
                )
            )
        return options

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

    def rerun_daily_schedule(
        self,
        schedule_id: str,
        actor_user_id: str | None = None,
        actor_user_name: str | None = None,
    ) -> MatchJobAccepted:
        safe_schedule_id = str(schedule_id or "").strip()
        if not safe_schedule_id:
            raise ValueError("schedule_id is required")

        schedule = self.repository.get_daily_schedule(safe_schedule_id)
        if not schedule or not bool(schedule.get("is_active")):
            raise ValueError(f"Daily schedule {safe_schedule_id} not found")

        raw_queries = schedule.get("queries") if isinstance(schedule.get("queries"), dict) else {}
        source_upload_id = str(schedule.get("source_upload_id") or "").strip() or None
        if not raw_queries and not source_upload_id:
            raise ValueError(f"Daily schedule {safe_schedule_id} has no query source configured")

        schedule_user_id = str(schedule.get("user_id") or "").strip() or None
        schedule_user_name = str(schedule.get("user_name") or "").strip() or None
        correlation_id = str(uuid4())

        payload = MatchJobRequest(
            queries=raw_queries,
            screening_types=list(schedule.get("screening_types") or []),
            mock_screening=bool(schedule.get("mock_screening")),
            business_unit_code=schedule.get("business_unit_code"),
            daily_screening=False,
            schedule_frequency=str(schedule.get("schedule_frequency") or "DAILY"),
            schedule_id=safe_schedule_id,
            source_upload_id=source_upload_id,
            batch_name=str(schedule.get("batch_name") or safe_schedule_id).strip() or safe_schedule_id,
            correlation_id=correlation_id,
            user_id=schedule_user_id or actor_user_id,
            user_name=schedule_user_name or actor_user_name,
        )

        accepted = self.submit_job(payload).model_copy(update={"daily_schedule_id": safe_schedule_id})
        self.repository.add_audit_event(
            action="DAILY_SCHEDULE_ADHOC_RERUN_TRIGGERED",
            user_id=actor_user_id,
            user_name=actor_user_name,
            entity_type="daily_schedule",
            entity_id=safe_schedule_id,
            details={
                "job_id": accepted.job_id,
                "batch_name": schedule.get("batch_name"),
                "query_count": len(raw_queries),
                "screening_types": list(schedule.get("screening_types") or []),
                "source_upload_id": source_upload_id,
                "correlation_id": correlation_id,
            },
        )
        return accepted

    def list_audit_events(self, limit: int = 200, user_id: str | None = None, offset: int = 0) -> list[AuditEvent]:
        events = self.repository.list_audit_events(limit=limit, user_id=user_id, offset=offset)
        return [AuditEvent.model_validate(e) for e in events]

    def list_audit_events_page(
        self,
        limit: int = 200,
        user_id: str | None = None,
        offset: int = 0,
        errors_only: bool = False,
    ) -> AuditEventPage:
        page = self.repository.list_audit_events_page(limit=limit, user_id=user_id, offset=offset, errors_only=errors_only)
        return AuditEventPage(
            items=[AuditEvent.model_validate(item) for item in page.get("items", [])],
            total=int(page.get("total") or 0),
            limit=int(page.get("limit") or limit),
            offset=int(page.get("offset") or offset),
        )

    def list_admin_users(self) -> list[AdminUserOption]:
        merged: dict[str, str] = {}
        for row in self.repository.list_known_users():
            user_id = str(row.get("user_id") or "").strip()
            if not user_id:
                continue
            display_name = str(row.get("display_name") or "").strip() or user_id
            merged[user_id] = display_name

        try:
            for row in self._list_cognito_users():
                user_id = str(row.get("user_id") or "").strip()
                if not user_id:
                    continue
                display_name = str(row.get("display_name") or "").strip() or user_id
                existing = merged.get(user_id)
                if not existing or existing == user_id:
                    merged[user_id] = display_name
        except Exception:
            # Fall back to DB-known users when Cognito listing is unavailable.
            pass

        return [
            AdminUserOption(user_id=user_id, display_name=display_name or user_id)
            for user_id, display_name in sorted(
                merged.items(),
                key=lambda item: (str(item[1] or item[0]).lower(), str(item[0]).lower()),
            )
        ]

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
        if self.notifier and self.notifier.enabled:
            try:
                sns_result = self.notifier.ensure_email_subscription(schedule_id=schedule_id, email=email)
                self.repository.add_audit_event(
                    action="SNS_EMAIL_SUBSCRIPTION_SYNCED",
                    user_id=user_id,
                    user_name=user_name,
                    entity_type="daily_schedule_subscription",
                    entity_id=subscription_id,
                    details={
                        "schedule_id": schedule_id,
                        "email": email,
                        "topic_arn": sns_result.get("topic_arn"),
                        "subscription_arn": sns_result.get("subscription_arn"),
                        "pending_confirmation": bool(sns_result.get("pending_confirmation")),
                        "created": bool(sns_result.get("created")),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                self.repository.add_audit_event(
                    action="SNS_EMAIL_SUBSCRIPTION_SYNC_FAILED",
                    user_id=user_id,
                    user_name=user_name,
                    entity_type="daily_schedule_subscription",
                    entity_id=subscription_id,
                    details={"schedule_id": schedule_id, "email": email, "error": str(exc)},
                )
                raise RuntimeError(f"Failed to configure SNS email subscription: {exc}") from exc
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
            if self.notifier and self.notifier.enabled:
                try:
                    remaining_active = self.repository.count_active_schedule_subscriptions_for_email(email)
                    if remaining_active == 0:
                        removed_sns_subs = self.notifier.unsubscribe_email(schedule_id=schedule_id, email=email)
                        self.repository.add_audit_event(
                            action="SNS_EMAIL_SUBSCRIPTION_REMOVED",
                            user_id=user_id,
                            user_name=user_name,
                            entity_type="daily_schedule_subscription",
                            entity_id=schedule_id,
                            details={"schedule_id": schedule_id, "email": email, "removed_count": int(removed_sns_subs)},
                        )
                    else:
                        self.repository.add_audit_event(
                            action="SNS_EMAIL_SUBSCRIPTION_RETAINED",
                            user_id=user_id,
                            user_name=user_name,
                            entity_type="daily_schedule_subscription",
                            entity_id=schedule_id,
                            details={
                                "schedule_id": schedule_id,
                                "email": email,
                                "remaining_active_subscriptions": remaining_active,
                            },
                        )
                except Exception as exc:  # noqa: BLE001
                    self.repository.add_audit_event(
                        action="SNS_EMAIL_SUBSCRIPTION_REMOVE_FAILED",
                        user_id=user_id,
                        user_name=user_name,
                        entity_type="daily_schedule_subscription",
                        entity_id=schedule_id,
                        details={"schedule_id": schedule_id, "email": email, "error": str(exc)},
                    )
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

    def list_business_units_for_user(self, user_id: str) -> list[BusinessUnit]:
        rows = self.repository.list_business_units(user_id=user_id, include_inactive=False)
        return [BusinessUnit.model_validate(row) for row in rows]

    def list_all_business_units(self, include_inactive: bool = True) -> list[BusinessUnit]:
        rows = self.repository.list_business_units(user_id=None, include_inactive=include_inactive)
        return [BusinessUnit.model_validate(row) for row in rows]

    def create_business_unit(
        self,
        business_unit_code: str,
        business_unit_name: str,
        actor_user_id: str | None,
        actor_user_name: str | None,
    ) -> BusinessUnit:
        row = self.repository.upsert_business_unit(business_unit_code=business_unit_code, business_unit_name=business_unit_name)
        self.repository.add_audit_event(
            action="BUSINESS_UNIT_UPSERTED",
            user_id=actor_user_id,
            user_name=actor_user_name,
            entity_type="business_unit",
            entity_id=row.get("business_unit_code"),
            details={"business_unit_name": row.get("business_unit_name")},
        )
        return BusinessUnit.model_validate(row)

    def update_business_unit(
        self,
        business_unit_code: str,
        next_business_unit_code: str | None,
        next_business_unit_name: str,
        actor_user_id: str | None,
        actor_user_name: str | None,
    ) -> BusinessUnit | None:
        row = self.repository.update_business_unit(
            business_unit_code=business_unit_code,
            next_business_unit_code=next_business_unit_code,
            next_business_unit_name=next_business_unit_name,
        )
        if not row:
            return None
        self.repository.add_audit_event(
            action="BUSINESS_UNIT_UPDATED",
            user_id=actor_user_id,
            user_name=actor_user_name,
            entity_type="business_unit",
            entity_id=row.get("business_unit_code"),
            details={"business_unit_name": row.get("business_unit_name")},
        )
        return BusinessUnit.model_validate(row)

    def delete_business_unit(self, business_unit_code: str, actor_user_id: str | None, actor_user_name: str | None) -> bool:
        removed = self.repository.delete_business_unit(business_unit_code)
        if removed:
            self.repository.add_audit_event(
                action="BUSINESS_UNIT_DELETED",
                user_id=actor_user_id,
                user_name=actor_user_name,
                entity_type="business_unit",
                entity_id=business_unit_code,
            )
        return removed

    def list_user_business_unit_mappings(self) -> list[UserBusinessUnitMapping]:
        rows = self.repository.list_user_business_unit_mappings()
        return [UserBusinessUnitMapping.model_validate(row) for row in rows]

    def set_user_business_unit_mapping(
        self,
        user_id: str,
        user_name: str | None,
        business_unit_codes: list[str],
        actor_user_id: str | None,
        actor_user_name: str | None,
    ) -> UserBusinessUnitMapping:
        saved_codes = self.repository.set_user_business_units(
            user_id=user_id,
            user_name=user_name,
            business_unit_codes=business_unit_codes,
        )
        self.repository.add_audit_event(
            action="USER_BUSINESS_UNITS_UPDATED",
            user_id=actor_user_id,
            user_name=actor_user_name,
            entity_type="user_business_units",
            entity_id=user_id,
            details={"user_name": user_name, "business_unit_codes": saved_codes},
        )
        return UserBusinessUnitMapping(user_id=user_id, user_name=user_name, business_unit_codes=saved_codes)
