from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from pathlib import Path
from threading import Lock
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import boto3

from app.actimize import ActimizeClient, ExternalApiCallError
from app.batch_upload_parser import BatchUploadValidationError, parse_batch_upload
from app.config import settings
from app.models import EntityExample, MatchJobRequest, ScreeningQueueMessage
from app.queue import SqsQueue
from app.repository import JobRepository
from app.screening_service import ScreeningService
from app.sns_notifier import SnsNotifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("screening-worker")
_RETRYABLE_EXTERNAL_STATUS_CODES = {429, 500, 502, 503, 504}


def _write_worker_heartbeat(path: str) -> None:
    safe_path = str(path or "").strip()
    if not safe_path:
        return
    try:
        heartbeat_path = Path(safe_path)
        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        heartbeat_path.write_text(f"{time.time():.6f}", encoding="ascii")
    except Exception:  # noqa: BLE001
        # Health check heartbeat failures should not crash worker processing.
        return


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
        parsed = json.loads(raw)
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


def _handle_job_dispatch(
    *,
    repository: JobRepository,
    queue: SqsQueue,
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

    if message.source_schedule_id:
        parsed, record_hashes, skipped_existing_records = repository.filter_unscreened_schedule_queries(
            message.source_schedule_id,
            parsed,
        )

    expected_total = len(parsed)
    repository.update_job_total_items(job_id, expected_total)
    repository.upsert_job_metadata(job_id=job_id, query_count=expected_total)
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
            "skipped_existing_records": skipped_existing_records,
            "queue_name": settings.aws_sqs_queue_name,
        },
    )

    submitted_at = str(message.submitted_at or "").strip() or datetime.now(timezone.utc).isoformat()
    correlation_id = str(message.correlation_id or "").strip() or str(uuid4())

    # Expand and enqueue in chunks to keep memory bounded.
    batch: list[tuple[str, dict[str, object], EntityExample, str | None]] = []
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
        dispatched_items += 1
        if len(batch) >= 500:
            _flush_dispatch_batch(
                repository=repository,
                queue=queue,
                job_id=job_id,
                submitted_at=submitted_at,
                correlation_id=correlation_id,
                message=message,
                items=batch,
            )
            batch = []

    if batch:
        _flush_dispatch_batch(
            repository=repository,
            queue=queue,
            job_id=job_id,
            submitted_at=submitted_at,
            correlation_id=correlation_id,
            message=message,
            items=batch,
        )

    if dispatched_items != expected_total:
        repository.update_job_total_items(job_id, dispatched_items)
        repository.upsert_job_metadata(job_id=job_id, query_count=dispatched_items)
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
            "skipped_existing_records": skipped_existing_records,
        },
    )


def _flush_dispatch_batch(
    *,
    repository: JobRepository,
    queue: SqsQueue,
    job_id: str,
    submitted_at: str,
    correlation_id: str,
    message: ScreeningQueueMessage,
    items: list[tuple[str, dict[str, object], EntityExample, str | None]],
) -> None:
    next_items: list[tuple[str, dict[str, object], EntityExample, str | None]] = []
    bulk_payloads: list[tuple[str, dict[str, object]]] = []
    for item_key, payload, query, record_hash in items:
        props = query.properties if isinstance(query.properties, dict) else {}
        has_party_key = bool(str(props.get("partyKey") or "").strip() or str(props.get("party_key") or "").strip())
        if item_key and not has_party_key:
            next_props = dict(props)
            next_props["partyKey"] = item_key
            query = query.model_copy(update={"properties": next_props})

            payload_props = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
            payload_props = dict(payload_props)
            payload_props["partyKey"] = item_key
            payload = dict(payload)
            payload["properties"] = payload_props

        safe_business_unit_code = str(message.business_unit_code or "").strip().upper()
        if safe_business_unit_code:
            next_props = dict(query.properties if isinstance(query.properties, dict) else {})
            next_props["businessUnit"] = safe_business_unit_code
            query = query.model_copy(update={"properties": next_props})

            payload_props = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
            payload_props = dict(payload_props)
            payload_props["businessUnit"] = safe_business_unit_code
            payload = dict(payload)
            payload["properties"] = payload_props

        next_items.append((item_key, payload, query, record_hash))
        bulk_payloads.append((item_key, payload))

    repository.add_job_items_bulk(job_id, bulk_payloads)

    # Enqueue per-item screening tasks to allow parallelism across workers.
    pending: list[ScreeningQueueMessage] = []
    for item_key, _payload, query, record_hash in next_items:
        pending.append(
            ScreeningQueueMessage(
                message_type="SCREEN_ITEM",
                job_id=job_id,
                item_key=item_key,
                query=query,
                submitted_at=submitted_at,
                screening_types=list(message.screening_types or []),
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


def _compute_item_retry_delay_s(current_attempt: int) -> int:
    base_delay = max(int(settings.screening_item_retry_initial_delay_s), 1)
    max_delay = max(int(settings.screening_item_retry_max_delay_s), base_delay)
    # Exponential backoff capped by max delay.
    return min(base_delay * (2 ** max(int(current_attempt), 0)), max_delay)


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
    schedule_id: str,
    job_id: str,
) -> None:
    if not notifier.enabled:
        return

    schedule = repository.get_daily_schedule(schedule_id) or {}
    subscription_rows = repository.list_schedule_subscriptions(schedule_id=schedule_id)
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
            entity_id=schedule_id,
            details={"job_id": job_id},
        )
        return

    summary = repository.build_job_completion_summary(job_id) or {}
    batch_name = str(schedule.get("batch_name") or "").strip() or schedule_id
    completion_outcome = _derive_completion_outcome(summary)
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
        f"Batch Name: {batch_name}",
        f"Job ID: {job_id}",
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
            sync_result = notifier.ensure_email_subscription(schedule_id=schedule_id, email=email)
            message_id = notifier.publish_schedule_completion(
                schedule_id=schedule_id,
                title=subject,
                message=message,
                summary=None,
                email=email,
            )
            repository.add_audit_event(
                action="SNS_NOTIFICATION_PUBLISHED",
                entity_type="daily_schedule",
                entity_id=schedule_id,
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
                entity_id=schedule_id,
                details={
                    "job_id": job_id,
                    "batch_name": batch_name,
                    "email": email,
                    "error": str(exc),
                },
            )
            logger.exception(
                "failed to publish SNS schedule notification for schedule_id=%s job_id=%s email=%s: %s",
                schedule_id,
                job_id,
                email,
                exc,
            )

    repository.add_audit_event(
        action="SNS_NOTIFICATION_BATCH_COMPLETED",
        entity_type="daily_schedule",
        entity_id=schedule_id,
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
    repository.add_audit_event(
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
        repository.add_audit_event(
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

    resolved_requester_name = _resolve_requester_name(message, repository)
    if resolved_requester_name != str(message.user_name or "").strip():
        message = message.model_copy(update={"user_name": resolved_requester_name})

    if str(message.message_type or "").strip().upper() == "JOB_DISPATCH":
        repository.add_audit_event(
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
                message=message,
                receipt_handle=str(receipt_handle),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("batch dispatch failed: %s", exc)
            repository.add_audit_event(
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
        result_items = result.get("results", []) if isinstance(result, dict) else []
        result_count = len(result_items) if isinstance(result_items, list) else 0
        logger.info(
            "screening item succeeded job=%s key=%s correlation_id=%s result_count=%s",
            message.job_id,
            message.item_key,
            correlation_id,
            result_count,
        )
        if message.source_schedule_id and message.source_record_hash:
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
                repository.add_audit_event(
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
                repository.mark_item_failed(
                    message.job_id,
                    message.item_key,
                    f"{exc}; retry requeue failed: {requeue_exc}",
                )
                if message.source_schedule_id:
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
            repository.add_audit_event(
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

        repository.mark_item_failed(message.job_id, message.item_key, str(exc))
        if message.source_schedule_id:
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
        queue.delete(str(receipt_handle))


def run() -> None:
    queue = SqsQueue()
    queue.ensure_queue()
    repository = JobRepository(settings.app_db_path, settings.app_db_url)
    notifier = SnsNotifier()
    service = ScreeningService(repository=repository, queue=queue, notifier=notifier)
    actimize = ActimizeClient(repository=repository)
    limiter = FixedRateLimiter(settings.screening_tps)
    last_schedule_check = 0.0
    last_cleanup_run = 0.0

    max_parallel_messages = max(settings.screening_parallel_messages, 1)
    logger.info(
        "worker started with max TPS=%s max parallel messages=%s",
        settings.screening_tps,
        max_parallel_messages,
    )
    _write_worker_heartbeat(settings.worker_heartbeat_path)

    with ThreadPoolExecutor(max_workers=max_parallel_messages) as executor:
        while True:
            _write_worker_heartbeat(settings.worker_heartbeat_path)
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
            _write_worker_heartbeat(settings.worker_heartbeat_path)


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

