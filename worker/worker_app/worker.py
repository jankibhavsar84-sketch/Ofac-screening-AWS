from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from threading import Lock, Thread
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import boto3

from app.actimize import ActimizeClient, ExternalApiCallError
from app.batch_upload_parser import BatchUploadValidationError, parse_batch_upload
from app.config import settings
from app.models import EntityExample, JobStatus, MatchJobRequest, ScreeningQueueMessage
from app.queue import SqsQueue
from app.repository import JobRepository
from app.screening_service import ScreeningService
from app.sns_notifier import SnsNotifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("screening-worker")
_RETRYABLE_EXTERNAL_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_RETRYABLE_DATABASE_ERROR_MARKERS = (
    "couldn't get a connection after",
    "connection timeout expired",
    "timeout expired",
    "server closed the connection unexpectedly",
    "connection has been closed unexpectedly",
    "ssl syscall error",
    "too many clients already",
    "remaining connection slots are reserved",
    "connection refused",
    "deadlock detected",
    "canceling statement due to lock timeout",
    "canceling statement due to statement timeout",
)


def _normalize_schedule_id(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


class WorkerHealthState:
    def __init__(self, max_age_s: int) -> None:
        self.max_age_s = max(int(max_age_s), 1)
        self._lock = Lock()
        self._last_heartbeat_at_monotonic = time.monotonic()

    def touch(self) -> None:
        with self._lock:
            self._last_heartbeat_at_monotonic = time.monotonic()

    def snapshot(self) -> tuple[bool, float, int]:
        now = time.monotonic()
        with self._lock:
            age_s = max(0.0, now - self._last_heartbeat_at_monotonic)
            max_age_s = self.max_age_s
        return age_s <= max_age_s, age_s, max_age_s


def _build_worker_health_handler(health_state: WorkerHealthState) -> type[BaseHTTPRequestHandler]:
    class _WorkerHealthHandler(BaseHTTPRequestHandler):
        server_version = "OFACWorkerHealth/1.0"

        def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path not in {"/health", "/health/"}:
                self.send_error(404)
                return
            is_healthy, age_s, max_age_s = health_state.snapshot()
            if is_healthy:
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "heartbeat_age_s": round(age_s, 3),
                        "max_age_s": max_age_s,
                    },
                )
                return
            self._send_json(
                503,
                {
                    "status": "stale",
                    "heartbeat_age_s": round(age_s, 3),
                    "max_age_s": max_age_s,
                },
            )

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            # Keep worker logs focused on screening events.
            return

    return _WorkerHealthHandler


def _start_worker_health_server(health_state: WorkerHealthState) -> ThreadingHTTPServer:
    host = str(settings.worker_health_host or "127.0.0.1").strip() or "127.0.0.1"
    port = max(int(settings.worker_health_port), 1)
    server = ThreadingHTTPServer((host, port), _build_worker_health_handler(health_state))
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, name="worker-health-http", daemon=True)
    thread.start()
    logger.info("worker health endpoint listening on http://%s:%s/health", host, port)
    return server


def _s3_client() -> object:
    client_kwargs: dict[str, object] = {
        "service_name": "s3",
        "region_name": settings.aws_region,
    }
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        client_kwargs["aws_access_key_id"] = settings.aws_access_key_id
        client_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    if settings.aws_endpoint_url:
        client_kwargs["endpoint_url"] = settings.aws_endpoint_url
    return boto3.client(**client_kwargs)


def _download_s3_text(s3: object, bucket: str, key: str) -> str:
    obj = s3.get_object(Bucket=bucket, Key=key)  # type: ignore[attr-defined]
    body = obj["Body"].read()  # type: ignore[index]
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    return str(body)


def _download_s3_bytes(s3: object, bucket: str, key: str) -> bytes:
    obj = s3.get_object(Bucket=bucket, Key=key)  # type: ignore[attr-defined]
    body = obj["Body"].read()  # type: ignore[index]
    if isinstance(body, bytes):
        return body
    return str(body).encode("utf-8")


def _load_batch_queries(
    *,
    repository: JobRepository,
    upload_id: str,
    upload: dict[str, Any],
    s3: object,
) -> dict[str, dict[str, Any]]:
    queries_bucket = str(upload.get("queries_s3_bucket") or "").strip()
    queries_key = str(upload.get("queries_s3_key") or "").strip()
    if queries_bucket and queries_key:
        raw = _download_s3_text(s3, queries_bucket, queries_key)
        if isinstance(raw, dict):
            parsed = raw
        else:
            safe_raw = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
            parsed = json.loads(safe_raw)
        if not isinstance(parsed, dict) or not parsed:
            raise RuntimeError("queries.json must be a non-empty object")
        repository.update_batch_file_upload_record_count(upload_id, len(parsed))
        return parsed

    source_bucket = str(upload.get("s3_bucket") or "").strip()
    source_key = str(upload.get("s3_key") or "").strip()
    source_file_name = str(upload.get("file_name") or "").strip() or "upload.csv"
    if not source_bucket or not source_key:
        raise RuntimeError("Source upload file was not stored in S3 for this upload")

    raw_body = _download_s3_bytes(s3, source_bucket, source_key)
    parsed_upload = parse_batch_upload(source_file_name, raw_body)
    parsed = {
        item_key: query.model_dump(mode="json")
        for item_key, query in parsed_upload.queries.items()
    }
    if not parsed:
        raise RuntimeError("Uploaded batch file did not contain any valid screening rows")
    repository.update_batch_file_upload_record_count(upload_id, len(parsed))
    return parsed


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


def _build_screening_item_key(base_item_key: str, screening_type: str) -> str:
    safe_base = str(base_item_key or "").strip()
    safe_type = str(screening_type or "").strip()
    if safe_base and safe_type:
        return f"{safe_base}_{safe_type}"
    return safe_base or safe_type


def _handle_job_dispatch(
    *,
    repository: JobRepository,
    queue: SqsQueue,
    actimize: ActimizeClient,
    message: ScreeningQueueMessage,
    receipt_handle: str,
) -> None:
    # Large batch dispatch can take longer than the default 60s visibility timeout.
    queue.change_visibility(receipt_handle, timeout_seconds=3600)

    job_id = str(message.job_id or "").strip()
    upload_id = str(message.source_upload_id or "").strip()
    if not job_id or not upload_id:
        repository.add_audit_event(
            action="BATCH_DISPATCH_FAILED",
            user_id=message.user_id,
            user_name=message.user_name,
            entity_type="screening_job",
            entity_id=job_id or "unknown_job",
            details={"error": "Missing job_id or source_upload_id"},
        )
        return

    safe_business_unit_code = str(message.business_unit_code or "").strip().upper()
    if not safe_business_unit_code:
        metadata = repository.get_job_metadata(job_id) or {}
        safe_business_unit_code = str(metadata.get("business_unit_code") or "").strip().upper()
        if safe_business_unit_code:
            message = message.model_copy(update={"business_unit_code": safe_business_unit_code})

    upload = repository.get_batch_file_upload(upload_id)
    if not upload:
        repository.add_audit_event(
            action="BATCH_DISPATCH_FAILED",
            user_id=message.user_id,
            user_name=message.user_name,
            entity_type="batch_file_upload",
            entity_id=upload_id,
            details={"job_id": job_id, "error": "Batch upload record not found"},
        )
        repository.mark_job_failed(job_id, "Batch upload record not found")
        return

    s3 = _s3_client()
    skipped_existing_records = 0
    record_hashes: dict[str, str] = {}
    try:
        parsed = _load_batch_queries(repository=repository, upload_id=upload_id, upload=upload, s3=s3)
    except BatchUploadValidationError as exc:
        repository.add_audit_event(
            action="BATCH_DISPATCH_FAILED",
            user_id=message.user_id,
            user_name=message.user_name,
            entity_type="batch_file_upload",
            entity_id=upload_id,
            details={"job_id": job_id, "error": str(exc)},
        )
        repository.mark_job_failed(job_id, str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        repository.add_audit_event(
            action="BATCH_DISPATCH_FAILED",
            user_id=message.user_id,
            user_name=message.user_name,
            entity_type="batch_file_upload",
            entity_id=upload_id,
            details={"job_id": job_id, "error": f"Failed to load/parse batch payload: {exc}"},
        )
        repository.mark_job_failed(job_id, f"Failed to parse batch payload: {exc}")
        return

    if message.source_schedule_id is not None:
        parsed, record_hashes, skipped_existing_records = repository.filter_unscreened_schedule_queries(
            message.source_schedule_id,
            parsed,
        )

    screening_types_for_dispatch = _resolve_dispatch_screening_types(message.screening_types)
    if screening_types_for_dispatch != list(message.screening_types or []):
        message = message.model_copy(update={"screening_types": screening_types_for_dispatch})

    expected_query_count = len(parsed)
    expected_total = expected_query_count * len(screening_types_for_dispatch)
    repository.update_job_total_items(job_id, expected_total)
    repository.upsert_job_metadata(
        job_id=job_id,
        screening_types=screening_types_for_dispatch,
        query_count=expected_query_count,
    )
    repository.add_audit_event(
        action="BATCH_DISPATCH_STARTED",
        user_id=message.user_id,
        user_name=message.user_name,
        entity_type="screening_job",
        entity_id=job_id,
        details={
            "job_id": job_id,
            "source_upload_id": upload_id,
            "total_items": expected_total,
            "query_count": expected_query_count,
            "screening_type_count": len(screening_types_for_dispatch),
            "skipped_existing_records": skipped_existing_records,
            "queue_name": settings.aws_sqs_queue_name,
        },
    )

    submitted_at = str(message.submitted_at or "").strip() or datetime.now(timezone.utc).isoformat()
    correlation_id = str(message.correlation_id or "").strip() or str(uuid4())

    # Expand and enqueue in chunks to keep memory bounded.
    batch: list[tuple[str, dict[str, object], EntityExample, str | None]] = []
    dispatched_query_count = 0
    dispatched_items = 0
    for item_key, raw_query in parsed.items():
        safe_key = str(item_key or "").strip()
        if not safe_key:
            continue
        if not isinstance(raw_query, dict):
            continue
        try:
            query = EntityExample.model_validate(raw_query)
        except Exception as exc:  # noqa: BLE001
            # Record-level validation errors should not block the whole batch.
            repository.add_audit_event(
                action="BATCH_DISPATCH_ITEM_INVALID",
                user_id=message.user_id,
                user_name=message.user_name,
                entity_type="screening_job_item",
                entity_id=f"{job_id}:{safe_key}",
                details={"job_id": job_id, "item_key": safe_key, "error": str(exc)},
            )
            continue
        request_payload = query.model_dump(mode="json")
        batch.append((safe_key, request_payload, query, record_hashes.get(safe_key)))
        dispatched_query_count += 1
        if len(batch) >= 500:
            dispatched_items += _flush_dispatch_batch(
                repository=repository,
                queue=queue,
                actimize=actimize,
                job_id=job_id,
                submitted_at=submitted_at,
                correlation_id=correlation_id,
                message=message,
                items=batch,
            )
            batch = []

    if batch:
        dispatched_items += _flush_dispatch_batch(
            repository=repository,
            queue=queue,
            actimize=actimize,
            job_id=job_id,
            submitted_at=submitted_at,
            correlation_id=correlation_id,
            message=message,
            items=batch,
        )

    if dispatched_items != expected_total or dispatched_query_count != expected_query_count:
        repository.update_job_total_items(job_id, dispatched_items)
        repository.upsert_job_metadata(
            job_id=job_id,
            screening_types=screening_types_for_dispatch,
            query_count=dispatched_query_count,
        )
    if dispatched_items == 0:
        repository.refresh_job_status(job_id)

    repository.add_audit_event(
        action="BATCH_DISPATCH_COMPLETED",
        user_id=message.user_id,
        user_name=message.user_name,
        entity_type="screening_job",
        entity_id=job_id,
        details={
            "job_id": job_id,
            "source_upload_id": upload_id,
            "total_items": dispatched_items,
            "query_count": dispatched_query_count,
            "screening_type_count": len(screening_types_for_dispatch),
            "skipped_existing_records": skipped_existing_records,
        },
    )


def _flush_dispatch_batch(
    *,
    repository: JobRepository,
    queue: SqsQueue,
    actimize: ActimizeClient,
    job_id: str,
    submitted_at: str,
    correlation_id: str,
    message: ScreeningQueueMessage,
    items: list[tuple[str, dict[str, object], EntityExample, str | None]],
) -> int:
    screening_types = _resolve_dispatch_screening_types(message.screening_types)
    next_items: list[tuple[str, str, dict[str, object], EntityExample, str | None]] = []
    bulk_payloads: list[tuple[str, dict[str, object]]] = []
    for item_key, payload, query, record_hash in items:
        base_props = query.properties if isinstance(query.properties, dict) else {}
        safe_business_unit_code = str(message.business_unit_code or "").strip().upper()
        for screening_type in screening_types:
            per_type_party_key = actimize.build_batch_party_key(item_key, screening_type)
            per_type_item_key = _build_screening_item_key(item_key, screening_type)
            per_type_props = dict(base_props)
            per_type_props["partyKey"] = per_type_party_key
            per_type_props["partyKeysByScreeningType"] = {screening_type: per_type_party_key}
            per_type_props["screeningType"] = screening_type
            if safe_business_unit_code:
                per_type_props["businessUnit"] = safe_business_unit_code

            per_type_query = query.model_copy(update={"properties": per_type_props})
            per_type_payload = dict(payload)
            per_type_payload["properties"] = dict(per_type_props)

            next_items.append((per_type_item_key, screening_type, per_type_payload, per_type_query, record_hash))
            bulk_payloads.append((per_type_item_key, per_type_payload))

    inserted_item_keys = repository.add_job_items_bulk(job_id, bulk_payloads)
    if not inserted_item_keys:
        return 0

    # Enqueue per-item screening tasks to allow parallelism across workers.
    pending: list[ScreeningQueueMessage] = []
    for item_key, screening_type, _payload, query, record_hash in next_items:
        if item_key not in inserted_item_keys:
            continue
        pending.append(
            ScreeningQueueMessage(
                message_type="SCREEN_ITEM",
                job_id=job_id,
                item_key=item_key,
                query=query,
                submitted_at=submitted_at,
                screening_types=[screening_type],
                mock_screening=bool(message.mock_screening),
                user_id=message.user_id,
                user_name=message.user_name,
                correlation_id=correlation_id,
                business_unit_code=message.business_unit_code,
                source_schedule_id=message.source_schedule_id,
                source_record_hash=record_hash,
                source_upload_id=message.source_upload_id,
            )
        )
        if len(pending) == 10:
            queue.enqueue_batch(pending)
            pending = []
    if pending:
        queue.enqueue_batch(pending)
    return len(inserted_item_keys)


class FixedRateLimiter:
    def __init__(self, max_tps: int) -> None:
        self.max_tps = max(max_tps, 1)
        self.min_interval = 1.0 / self.max_tps
        self.next_slot = 0.0
        self._lock = Lock()

    def wait_turn(self) -> None:
        with self._lock:
            now = time.monotonic()
            if self.next_slot == 0.0:
                self.next_slot = now
            if now < self.next_slot:
                time.sleep(self.next_slot - now)
                now = time.monotonic()
            self.next_slot = max(self.next_slot, now) + self.min_interval


def _format_execution_time(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    safe = max(int(seconds), 0)
    minutes, sec = divmod(safe, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {sec}s"
    if minutes > 0:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def _derive_completion_outcome(summary: dict[str, object]) -> str:
    total_items = int(summary.get("total_items") or 0)
    completed_items = int(summary.get("completed_items") or 0)
    failed_items = int(summary.get("failed_items") or 0)

    if total_items <= 0:
        return "Fully Completed"
    if failed_items <= 0:
        return "Fully Completed"
    if completed_items <= 0 and failed_items >= total_items:
        return "Fully Failed"
    return "Partially Completed"


def _resolve_external_api_context(exc: Exception) -> tuple[str, str, str, int | None, dict[str, object]]:
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


def _is_retryable_external_failure(status_code: int | None) -> bool:
    return status_code in _RETRYABLE_EXTERNAL_STATUS_CODES


def _is_retryable_database_failure(repository: JobRepository, exc: Exception) -> bool:
    try:
        if repository._is_retryable_postgres_connect_error(exc):  # pylint: disable=protected-access
            return True
    except Exception:  # noqa: BLE001
        pass
    lowered = str(exc or "").strip().lower()
    return any(marker in lowered for marker in _RETRYABLE_DATABASE_ERROR_MARKERS)


def _compute_item_retry_delay_s(current_attempt: int) -> int:
    base_delay = max(int(settings.screening_item_retry_initial_delay_s), 1)
    max_delay = max(int(settings.screening_item_retry_max_delay_s), base_delay)
    # Exponential backoff capped by max delay.
    return min(base_delay * (2 ** max(int(current_attempt), 0)), max_delay)


def _safe_add_audit_event(repository: JobRepository, **kwargs: Any) -> None:
    try:
        repository.add_audit_event(**kwargs)
    except Exception as exc:  # noqa: BLE001
        action = str(kwargs.get("action") or "").strip() or "UNKNOWN_AUDIT_ACTION"
        entity_type = str(kwargs.get("entity_type") or "").strip() or "-"
        entity_id = str(kwargs.get("entity_id") or "").strip() or "-"
        logger.warning(
            "audit event write skipped action=%s entity_type=%s entity_id=%s error=%s",
            action,
            entity_type,
            entity_id,
            exc,
        )


def _resolve_requester_name(message: ScreeningQueueMessage, repository: JobRepository) -> str | None:
    candidate = str(message.user_name or "").strip()
    if candidate:
        return candidate

    job_id = str(message.job_id or "").strip()
    if job_id:
        snapshot = repository.get_job_snapshot(job_id)
        if isinstance(snapshot, dict):
            snapshot_name = str(snapshot.get("user_name") or "").strip()
            if snapshot_name:
                return snapshot_name

    user_id_candidate = str(message.user_id or "").strip()
    if user_id_candidate:
        return user_id_candidate

    fallback = settings.actimize_requester_name.strip()
    return fallback or None


def _publish_schedule_notification_via_sns(
    repository: JobRepository,
    notifier: SnsNotifier,
    schedule_id: int | str,
    job_id: str,
) -> None:
    normalized_schedule_id = _normalize_schedule_id(schedule_id)
    if normalized_schedule_id is None:
        return

    if not notifier.enabled:
        return

    schedule = repository.get_daily_schedule(normalized_schedule_id) or {}
    subscription_rows = repository.list_schedule_subscriptions(schedule_id=normalized_schedule_id)
    recipient_emails = sorted(
        {
            str(row.get("email") or "").strip().lower()
            for row in subscription_rows
            if str(row.get("email") or "").strip()
        }
    )
    if not recipient_emails:
        repository.add_audit_event(
            action="SNS_NOTIFICATION_SKIPPED_NO_RECIPIENTS",
            entity_type="daily_schedule",
            entity_id=str(normalized_schedule_id),
            details={"job_id": job_id},
        )
        return

    summary = repository.build_job_completion_summary(job_id) or {}
    batch_name = str(schedule.get("batch_name") or "").strip() or str(normalized_schedule_id)
    completion_outcome = _derive_completion_outcome(summary)
    total_parties = int(summary.get("total_items") or 0)
    records_screened = int(summary.get("records_screened") or summary.get("total_items") or 0)
    completed_items = int(summary.get("completed_items") or 0)
    failed_items = int(summary.get("failed_items") or 0)
    hit_records = int(summary.get("matched_items") or 0)
    execution_seconds = summary.get("execution_seconds")
    execution_label = _format_execution_time(execution_seconds if isinstance(execution_seconds, int) else None)
    started_at = str(summary.get("started_at") or "").strip()
    completed_at = str(summary.get("completed_at") or "").strip()
    actimize_link = (settings.actimize_alert_review_url or settings.actimize_base_url or "").strip()
    subject = f"Scheduled Screening {completion_outcome} - {batch_name}"[:100]
    message_lines = [
        f"Your scheduled screening batch is {completion_outcome}.",
        "",
        f"Job Name: {batch_name}",
        f"Job ID: {job_id}",
        f"Number of parties in batch: {total_parties}",
        f"Number of alerts generated: {hit_records}",
        "",
        "Detailed Summary:",
        f"Number of records screened: {records_screened}",
        f"Successfully screened records: {completed_items}",
        f"Failed records: {failed_items}",
        f"Number of records with hits: {hit_records}",
        f"Total execution time: {execution_label}",
    ]
    if started_at:
        message_lines.append(f"Started At (UTC): {started_at}")
    if completed_at:
        message_lines.append(f"Completed At (UTC): {completed_at}")
    message_lines.extend(
        [
            "",
            "Review Alerts in Actimize:",
            actimize_link or "Not configured. Set ACTIMIZE_ALERT_REVIEW_URL in backend configuration.",
        ]
    )
    message = "\n".join(message_lines)

    failed_emails: list[str] = []
    for email in recipient_emails:
        try:
            sync_result = notifier.ensure_email_subscription(schedule_id=str(normalized_schedule_id), email=email)
            message_id = notifier.publish_schedule_completion(
                schedule_id=str(normalized_schedule_id),
                title=subject,
                message=message,
                summary=None,
                email=email,
            )
            repository.add_audit_event(
                action="SNS_NOTIFICATION_PUBLISHED",
                entity_type="daily_schedule",
                entity_id=str(normalized_schedule_id),
                details={
                    "job_id": job_id,
                    "batch_name": batch_name,
                    "email": email,
                    "message_id": message_id,
                    "records_screened": records_screened,
                    "hit_records": hit_records,
                    "completion_outcome": completion_outcome,
                    "execution_seconds": execution_seconds,
                    "actimize_link": actimize_link,
                    "topic_arn": sync_result.get("topic_arn"),
                    "subscription_arn": sync_result.get("subscription_arn"),
                    "pending_confirmation": bool(sync_result.get("pending_confirmation")),
                },
            )
        except Exception as exc:  # noqa: BLE001
            failed_emails.append(email)
            repository.add_audit_event(
                action="SNS_NOTIFICATION_PUBLISH_FAILED",
                entity_type="daily_schedule",
                entity_id=str(normalized_schedule_id),
                details={
                    "job_id": job_id,
                    "batch_name": batch_name,
                    "email": email,
                    "error": str(exc),
                },
            )
            logger.exception(
                "failed to publish SNS schedule notification for schedule_id=%s job_id=%s email=%s: %s",
                normalized_schedule_id,
                job_id,
                email,
                exc,
            )

    repository.add_audit_event(
        action="SNS_NOTIFICATION_BATCH_COMPLETED",
        entity_type="daily_schedule",
        entity_id=str(normalized_schedule_id),
        details={
            "job_id": job_id,
            "batch_name": batch_name,
            "recipient_count": len(recipient_emails),
            "failed_count": len(failed_emails),
            "failed_emails": failed_emails,
        },
    )


def _receive_message_batch(queue: SqsQueue, max_messages: int) -> list[dict[str, Any]]:
    target = max(int(max_messages), 1)
    received: list[dict[str, Any]] = []
    while len(received) < target:
        to_fetch = min(10, target - len(received))
        wait_time = 20 if not received else 0
        chunk = queue.receive(max_messages=to_fetch, wait_time_seconds=wait_time)
        if not chunk:
            break
        received.extend(chunk)
        if len(chunk) < to_fetch:
            break
    return received


def _process_received_message(
    *,
    raw: dict[str, Any],
    queue: SqsQueue,
    repository: JobRepository,
    notifier: SnsNotifier,
    actimize: ActimizeClient,
    limiter: FixedRateLimiter,
) -> None:
    receipt_handle = raw.get("ReceiptHandle")
    if not receipt_handle:
        return
    message_id = str(raw.get("MessageId") or "").strip() or str(receipt_handle)
    delete_message = True
    _safe_add_audit_event(
        repository,
        action="SQS_MESSAGE_RECEIVED",
        entity_type="sqs_message",
        entity_id=message_id,
        details={
            "queue_name": settings.aws_sqs_queue_name,
            "receipt_handle": receipt_handle,
        },
    )

    try:
        message = queue.decode(raw)
    except Exception as exc:  # noqa: BLE001
        logger.exception("invalid message payload: %s", exc)
        _safe_add_audit_event(
            repository,
            action="SQS_MESSAGE_DECODE_FAILED",
            entity_type="sqs_message",
            entity_id=message_id,
            details={
                "queue_name": settings.aws_sqs_queue_name,
                "receipt_handle": receipt_handle,
                "body": raw.get("Body"),
                "error": str(exc),
            },
        )
        queue.delete(str(receipt_handle))
        return

    normalized_job_id = "" if message.job_id is None else str(message.job_id).strip()
    if not normalized_job_id:
        logger.error("invalid message payload: missing job_id")
        _safe_add_audit_event(
            repository,
            action="SQS_MESSAGE_INVALID_JOB_ID",
            entity_type="sqs_message",
            entity_id=message_id,
            details={
                "queue_name": settings.aws_sqs_queue_name,
                "receipt_handle": receipt_handle,
                "body": raw.get("Body"),
                "job_id": message.job_id,
            },
        )
        queue.delete(str(receipt_handle))
        return
    if normalized_job_id != message.job_id:
        message = message.model_copy(update={"job_id": normalized_job_id})

    resolved_requester_name = _resolve_requester_name(message, repository)
    if resolved_requester_name != str(message.user_name or "").strip():
        message = message.model_copy(update={"user_name": resolved_requester_name})

    if str(message.message_type or "").strip().upper() == "JOB_DISPATCH":
        _safe_add_audit_event(
            repository,
            action="BATCH_DISPATCH_MESSAGE_PICKED",
            user_id=message.user_id,
            user_name=message.user_name,
            entity_type="screening_job",
            entity_id=message.job_id,
            details={
                "job_id": message.job_id,
                "source_upload_id": message.source_upload_id,
                "queue_name": settings.aws_sqs_queue_name,
                "message_id": message_id,
            },
        )
        try:
            _handle_job_dispatch(
                repository=repository,
                queue=queue,
                actimize=actimize,
                message=message,
                receipt_handle=str(receipt_handle),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("batch dispatch failed: %s", exc)
            _safe_add_audit_event(
                repository,
                action="BATCH_DISPATCH_FAILED",
                user_id=message.user_id,
                user_name=message.user_name,
                entity_type="screening_job",
                entity_id=message.job_id,
                details={
                    "job_id": message.job_id,
                    "source_upload_id": message.source_upload_id,
                    "error": str(exc),
                },
            )
            repository.mark_job_failed(message.job_id, str(exc))
        finally:
            queue.delete(str(receipt_handle))
        return

    correlation_id = str(message.correlation_id or "").strip() or str(uuid4())
    retry_attempt = max(int(message.retry_attempt or 0), 0)
    safe_business_unit_code = str(message.business_unit_code or "").strip().upper()
    if safe_business_unit_code:
        query_props = message.query.properties if isinstance(message.query.properties, dict) else {}
        next_props = dict(query_props)
        next_props["businessUnit"] = safe_business_unit_code
        message = message.model_copy(update={"query": message.query.model_copy(update={"properties": next_props})})
    request_payload = message.query.model_dump(mode="json")
    screen_item_visibility_timeout_s = max(int(settings.screening_item_visibility_timeout_s), 300)
    try:
        current_item_status = repository.get_job_item_status(message.job_id, message.item_key)
    except Exception as exc:  # noqa: BLE001
        if _is_retryable_database_failure(repository, exc):
            delete_message = False
            logger.warning(
                "transient db read failure before screening job=%s key=%s correlation_id=%s; leaving message for retry: %s",
                message.job_id,
                message.item_key,
                correlation_id,
                exc,
            )
            return
        raise

    if current_item_status in {JobStatus.completed.value, JobStatus.failed.value}:
        logger.info(
            "screening item skipped job=%s key=%s existing_status=%s correlation_id=%s",
            message.job_id,
            message.item_key,
            current_item_status,
            correlation_id,
        )
        try:
            _safe_add_audit_event(
                repository,
                action="SCREENING_ITEM_SKIPPED_ALREADY_TERMINAL",
                user_id=message.user_id,
                user_name=message.user_name,
                entity_type="screening_job",
                entity_id=message.job_id,
                details={
                    "item_key": message.item_key,
                    "existing_status": current_item_status,
                    "correlation_id": correlation_id,
                },
            )
        except Exception as audit_exc:  # noqa: BLE001
            logger.warning(
                "failed to write terminal-item audit event job=%s key=%s correlation_id=%s: %s",
                message.job_id,
                message.item_key,
                correlation_id,
                audit_exc,
            )
        queue.delete(str(receipt_handle))
        return

    try:
        # Keep SCREEN_ITEM invisible long enough to avoid SQS redelivery while processing.
        queue.change_visibility(receipt_handle, timeout_seconds=screen_item_visibility_timeout_s)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "failed to extend visibility for job=%s key=%s timeout_s=%s: %s",
            message.job_id,
            message.item_key,
            screen_item_visibility_timeout_s,
            exc,
        )
    logger.info(
        "screening item started job=%s key=%s correlation_id=%s retry_attempt=%s screening_types=%s mock=%s schedule_id=%s",
        message.job_id,
        message.item_key,
        correlation_id,
        retry_attempt,
        message.screening_types,
        message.mock_screening,
        message.source_schedule_id,
    )

    try:
        limiter.wait_turn()
        result = actimize.screen_many_types(
            message.query,
            message.screening_types,
            message.mock_screening,
            requester_name=message.user_name,
        )
        repository.mark_item_completed(message.job_id, message.item_key, result)
        result_count = 0
        if isinstance(result, dict):
            by_type = result.get("responses_by_screening_type")
            if isinstance(by_type, dict):
                for response_payload in by_type.values():
                    if not isinstance(response_payload, dict):
                        continue
                    response_results = response_payload.get("results")
                    if isinstance(response_results, list):
                        result_count += len(response_results)
            else:
                result_items = result.get("results", [])
                if isinstance(result_items, list):
                    result_count = len(result_items)
        logger.info(
            "screening item succeeded job=%s key=%s correlation_id=%s result_count=%s",
            message.job_id,
            message.item_key,
            correlation_id,
            result_count,
        )
        if message.source_schedule_id is not None and message.source_record_hash:
            repository.mark_schedule_record_screened(
                schedule_id=message.source_schedule_id,
                record_hash=message.source_record_hash,
                job_id=message.job_id,
            )
            created_notifications = repository.maybe_publish_schedule_job_notification(
                job_id=message.job_id,
                schedule_id=message.source_schedule_id,
            )
            if created_notifications > 0:
                _publish_schedule_notification_via_sns(
                    repository=repository,
                    notifier=notifier,
                    schedule_id=message.source_schedule_id,
                    job_id=message.job_id,
                )
                logger.info(
                    "published %s schedule notifications for job=%s schedule=%s",
                    created_notifications,
                    message.job_id,
                    message.source_schedule_id,
                )
    except Exception as exc:  # noqa: BLE001
        if _is_retryable_database_failure(repository, exc):
            delete_message = False
            logger.warning(
                "transient database failure while processing screening item job=%s key=%s correlation_id=%s; leaving message for retry: %s",
                message.job_id,
                message.item_key,
                correlation_id,
                exc,
            )
            return
        logger.exception(
            "screening failed for job=%s key=%s: %s",
            message.job_id,
            message.item_key,
            exc,
        )
        provider, operation, endpoint, status_code, api_details = _resolve_external_api_context(exc)

        logger.error(
            "screening item failed job=%s key=%s correlation_id=%s retry_attempt=%s provider=%s operation=%s endpoint=%s status_code=%s screening_types=%s mock=%s schedule_id=%s request=%s details=%s error=%s",
            message.job_id,
            message.item_key,
            correlation_id,
            retry_attempt,
            provider,
            operation,
            endpoint,
            status_code,
            message.screening_types,
            message.mock_screening,
            message.source_schedule_id,
            json.dumps(request_payload, ensure_ascii=True, sort_keys=True),
            json.dumps(api_details or {}, ensure_ascii=True, sort_keys=True),
            str(exc),
        )

        max_retry_attempts = max(int(settings.screening_item_retry_max_attempts), 0)
        if _is_retryable_external_failure(status_code) and retry_attempt < max_retry_attempts:
            next_attempt = retry_attempt + 1
            delay_seconds = _compute_item_retry_delay_s(retry_attempt)
            retry_message = message.model_copy(
                update={
                    "retry_attempt": next_attempt,
                    "correlation_id": correlation_id,
                }
            )
            try:
                queue.enqueue(retry_message, delay_seconds=delay_seconds)
            except Exception as requeue_exc:  # noqa: BLE001
                logger.exception(
                    "failed to requeue screening item job=%s key=%s correlation_id=%s: %s",
                    message.job_id,
                    message.item_key,
                    correlation_id,
                    requeue_exc,
                )
                _safe_add_audit_event(
                    repository,
                    action="SCREENING_ITEM_REQUEUE_FAILED",
                    user_id=message.user_id,
                    user_name=message.user_name,
                    entity_type="screening_job",
                    entity_id=message.job_id,
                    details={
                        "item_key": message.item_key,
                        "correlation_id": correlation_id,
                        "provider": provider,
                        "operation": operation,
                        "endpoint": endpoint,
                        "status_code": status_code,
                        "retry_attempt": retry_attempt,
                        "next_retry_attempt": next_attempt,
                        "delay_seconds": delay_seconds,
                        "max_retry_attempts": max_retry_attempts,
                        "requeue_error": str(requeue_exc),
                    },
                )
                try:
                    repository.mark_item_failed(
                        message.job_id,
                        message.item_key,
                        f"{exc}; retry requeue failed: {requeue_exc}",
                    )
                except Exception as mark_failed_exc:  # noqa: BLE001
                    if _is_retryable_database_failure(repository, mark_failed_exc):
                        delete_message = False
                        logger.warning(
                            "transient database failure while marking failed job=%s key=%s correlation_id=%s; leaving message for retry: %s",
                            message.job_id,
                            message.item_key,
                            correlation_id,
                            mark_failed_exc,
                        )
                        return
                    delete_message = False
                    logger.exception(
                        "non-retryable database failure while marking failed job=%s key=%s correlation_id=%s; leaving message for retry",
                        message.job_id,
                        message.item_key,
                        correlation_id,
                    )
                    return
                if message.source_schedule_id is not None:
                    created_notifications = repository.maybe_publish_schedule_job_notification(
                        job_id=message.job_id,
                        schedule_id=message.source_schedule_id,
                    )
                    if created_notifications > 0:
                        _publish_schedule_notification_via_sns(
                            repository=repository,
                            notifier=notifier,
                            schedule_id=message.source_schedule_id,
                            job_id=message.job_id,
                        )
                return
            _safe_add_audit_event(
                repository,
                action="SCREENING_ITEM_REQUEUED",
                user_id=message.user_id,
                user_name=message.user_name,
                entity_type="screening_job",
                entity_id=message.job_id,
                details={
                    "item_key": message.item_key,
                    "correlation_id": correlation_id,
                    "provider": provider,
                    "operation": operation,
                    "endpoint": endpoint,
                    "status_code": status_code,
                    "retry_attempt": retry_attempt,
                    "next_retry_attempt": next_attempt,
                    "delay_seconds": delay_seconds,
                    "max_retry_attempts": max_retry_attempts,
                },
            )
            logger.warning(
                "requeued screening item job=%s key=%s correlation_id=%s status_code=%s attempt=%s/%s delay_s=%s",
                message.job_id,
                message.item_key,
                correlation_id,
                status_code,
                next_attempt,
                max_retry_attempts,
                delay_seconds,
            )
            return

        try:
            repository.mark_item_failed(message.job_id, message.item_key, str(exc))
        except Exception as mark_failed_exc:  # noqa: BLE001
            if _is_retryable_database_failure(repository, mark_failed_exc):
                delete_message = False
                logger.warning(
                    "transient database failure while marking failed job=%s key=%s correlation_id=%s; leaving message for retry: %s",
                    message.job_id,
                    message.item_key,
                    correlation_id,
                    mark_failed_exc,
                )
                return
            delete_message = False
            logger.exception(
                "non-retryable database failure while marking failed job=%s key=%s correlation_id=%s; leaving message for retry",
                message.job_id,
                message.item_key,
                correlation_id,
            )
            return
        if message.source_schedule_id is not None:
            created_notifications = repository.maybe_publish_schedule_job_notification(
                job_id=message.job_id,
                schedule_id=message.source_schedule_id,
            )
            if created_notifications > 0:
                _publish_schedule_notification_via_sns(
                    repository=repository,
                    notifier=notifier,
                    schedule_id=message.source_schedule_id,
                    job_id=message.job_id,
                )
                logger.info(
                    "published %s schedule notifications for failed job=%s schedule=%s",
                    created_notifications,
                    message.job_id,
                    message.source_schedule_id,
                )
    finally:
        if delete_message:
            queue.delete(str(receipt_handle))
        else:
            logger.info(
                "screening item message retained for retry job=%s key=%s message_id=%s",
                message.job_id if 'message' in locals() else "-",
                message.item_key if 'message' in locals() else "-",
                message_id,
            )


def run() -> None:
    queue = SqsQueue()
    queue.ensure_queue()
    repository = JobRepository(
        settings.app_db_path,
        settings.app_db_url,
    )
    notifier = SnsNotifier()
    service = ScreeningService(repository=repository, queue=queue, notifier=notifier)
    actimize = ActimizeClient(repository=repository)
    limiter = FixedRateLimiter(settings.screening_tps)
    last_schedule_check = 0.0
    last_cleanup_run = 0.0
    health_state = WorkerHealthState(settings.worker_health_max_age_s)
    health_server = _start_worker_health_server(health_state)

    max_parallel_messages = max(settings.screening_parallel_messages, 1)
    logger.info(
        "worker started with max TPS=%s max parallel messages=%s",
        settings.screening_tps,
        max_parallel_messages,
    )
    health_state.touch()
    try:
        with ThreadPoolExecutor(max_workers=max_parallel_messages) as executor:
            while True:
                health_state.touch()
                messages = _receive_message_batch(queue, max_parallel_messages)
                if messages:
                    futures = [
                        executor.submit(
                            _process_received_message,
                            raw=raw,
                            queue=queue,
                            repository=repository,
                            notifier=notifier,
                            actimize=actimize,
                            limiter=limiter,
                        )
                        for raw in messages
                    ]
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("unexpected worker message failure: %s", exc)

                now_monotonic = time.monotonic()
                if now_monotonic - last_schedule_check >= max(settings.daily_screening_check_interval_s, 5):
                    trigger_due_daily_schedules(repository, service, notifier)
                    last_schedule_check = now_monotonic
                if now_monotonic - last_cleanup_run >= max(settings.operational_cleanup_interval_s, 60):
                    deleted = repository.purge_old_operational_data(
                        audit_event_retention_days=settings.audit_event_retention_days,
                        api_access_log_retention_days=settings.api_access_log_retention_days,
                        external_api_error_retention_days=settings.external_api_error_retention_days,
                    )
                    if any(v > 0 for v in deleted.values()):
                        repository.add_audit_event(
                            action="OPERATIONAL_DATA_PURGED",
                            entity_type="retention_policy",
                            details=deleted,
                        )
                        logger.info("operational data cleanup completed: %s", deleted)
                    last_cleanup_run = now_monotonic
                health_state.touch()
    finally:
        health_server.shutdown()
        health_server.server_close()


def trigger_due_daily_schedules(repository: JobRepository, service: ScreeningService, notifier: SnsNotifier) -> None:
    now_utc = datetime.now(timezone.utc)
    due_schedules = repository.list_due_daily_schedules(now_utc.isoformat())
    for schedule in due_schedules:
        next_run_at = JobRepository.compute_next_run_at(
            now_utc=now_utc,
            timezone_name=schedule["timezone"],
            run_hour=schedule["run_hour"],
            run_minute=schedule["run_minute"],
            schedule_frequency=schedule.get("schedule_frequency", "DAILY"),
        )

        claimed = repository.claim_daily_schedule_run(
            schedule_id=schedule["schedule_id"],
            expected_next_run_at=schedule["next_run_at"],
            last_run_at=now_utc.isoformat(),
            next_run_at=next_run_at,
        )
        if not claimed:
            continue

        try:
            correlation_id = str(uuid4())
            payload = MatchJobRequest(
                queries=schedule["queries"],
                screening_types=schedule["screening_types"],
                mock_screening=bool(schedule["mock_screening"]),
                business_unit_code=schedule.get("business_unit_code"),
                daily_screening=False,
                schedule_id=schedule["schedule_id"],
                source_upload_id=schedule.get("source_upload_id"),
                batch_name=schedule["batch_name"],
                correlation_id=correlation_id,
                user_id=schedule.get("user_id"),
                user_name=schedule.get("user_name"),
            )
            accepted = service.submit_job(payload)
            logger.info(
                "daily schedule triggered: schedule_id=%s batch=%s job_id=%s next_run_at=%s",
                schedule["schedule_id"],
                schedule["batch_name"],
                accepted.job_id,
                next_run_at,
            )
            if accepted.total_items == 0:
                notifications = repository.maybe_publish_schedule_job_notification(
                    job_id=accepted.job_id,
                    schedule_id=schedule["schedule_id"],
                )
                if notifications > 0:
                    _publish_schedule_notification_via_sns(
                        repository=repository,
                        notifier=notifier,
                        schedule_id=schedule["schedule_id"],
                        job_id=accepted.job_id,
                    )
                    logger.info(
                        "published %s schedule notifications for no-new-records job=%s schedule=%s",
                        notifications,
                        accepted.job_id,
                        schedule["schedule_id"],
                    )
            repository.add_audit_event(
                action="DAILY_SCHEDULE_TRIGGERED",
                user_id=schedule.get("user_id"),
                user_name=schedule.get("user_name"),
                entity_type="daily_schedule",
                entity_id=schedule["schedule_id"],
                details={"job_id": accepted.job_id, "batch_name": schedule["batch_name"], "correlation_id": correlation_id},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "failed to trigger daily schedule schedule_id=%s batch=%s: %s",
                schedule["schedule_id"],
                schedule["batch_name"],
                exc,
            )


if __name__ == "__main__":
    run()

