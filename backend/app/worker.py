from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from .actimize import ActimizeClient, ExternalApiCallError
from .config import settings
from .models import MatchJobRequest
from .queue import SqsQueue
from .repository import JobRepository
from .screening_service import ScreeningService
from .sns_notifier import SnsNotifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("screening-worker")


class FixedRateLimiter:
    def __init__(self, max_tps: int) -> None:
        self.max_tps = max(max_tps, 1)
        self.min_interval = 1.0 / self.max_tps
        self.next_slot = 0.0

    def wait_turn(self) -> None:
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


def _publish_schedule_notification_via_sns(
    repository: JobRepository,
    notifier: SnsNotifier,
    schedule_id: str,
    job_id: str,
) -> None:
    if not notifier.enabled:
        return

    schedule = repository.get_daily_schedule(schedule_id) or {}
    summary = repository.build_job_completion_summary(job_id) or {}
    batch_name = str(schedule.get("batch_name") or "").strip() or schedule_id
    records_screened = int(summary.get("records_screened") or summary.get("total_items") or 0)
    hit_records = int(summary.get("matched_items") or 0)
    execution_seconds = summary.get("execution_seconds")
    execution_label = _format_execution_time(execution_seconds if isinstance(execution_seconds, int) else None)
    started_at = str(summary.get("started_at") or "").strip()
    completed_at = str(summary.get("completed_at") or "").strip()
    actimize_link = (settings.actimize_alert_review_url or settings.actimize_base_url or "").strip()
    subject = f"Scheduled Screening Completed - {batch_name}"[:100]
    message_lines = [
        "Your scheduled screening batch has completed.",
        "",
        f"Batch Name: {batch_name}",
        f"Job ID: {job_id}",
        f"Number of records screened: {records_screened}",
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

    try:
        message_id = notifier.publish_schedule_completion(
            schedule_id=schedule_id,
            title=subject,
            message=message,
            summary=None,
        )
        repository.add_audit_event(
            action="SNS_NOTIFICATION_PUBLISHED",
            entity_type="daily_schedule",
            entity_id=schedule_id,
            details={
                "job_id": job_id,
                "batch_name": batch_name,
                "message_id": message_id,
                "records_screened": records_screened,
                "hit_records": hit_records,
                "execution_seconds": execution_seconds,
                "actimize_link": actimize_link,
            },
        )
    except Exception as exc:  # noqa: BLE001
        repository.add_audit_event(
            action="SNS_NOTIFICATION_PUBLISH_FAILED",
            entity_type="daily_schedule",
            entity_id=schedule_id,
            details={
                "job_id": job_id,
                "batch_name": batch_name,
                "error": str(exc),
            },
        )
        logger.exception(
            "failed to publish SNS schedule notification for schedule_id=%s job_id=%s: %s",
            schedule_id,
            job_id,
            exc,
        )


def run() -> None:
    queue = SqsQueue()
    queue.ensure_queue()
    repository = JobRepository(settings.app_db_path, settings.app_db_url)
    notifier = SnsNotifier()
    service = ScreeningService(repository=repository, queue=queue, notifier=notifier)
    actimize = ActimizeClient()
    limiter = FixedRateLimiter(settings.screening_tps)
    last_schedule_check = 0.0
    last_cleanup_run = 0.0

    logger.info("worker started with max TPS=%s", settings.screening_tps)

    while True:
        messages = queue.receive(max_messages=10, wait_time_seconds=20)

        for raw in messages:
            receipt_handle = raw.get("ReceiptHandle")
            if not receipt_handle:
                continue
            message_id = str(raw.get("MessageId") or "").strip() or receipt_handle
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
                queue.delete(receipt_handle)
                continue
            correlation_id = str(message.correlation_id or "").strip() or str(uuid4())
            repository.add_audit_event(
                action="SQS_MESSAGE_PICKED",
                user_id=message.user_id,
                user_name=message.user_name,
                entity_type="screening_queue_item",
                entity_id=f"{message.job_id}:{message.item_key}",
                details={
                    "queue_name": settings.aws_sqs_queue_name,
                    "message_id": message_id,
                    "job_id": message.job_id,
                    "item_key": message.item_key,
                    "source_schedule_id": message.source_schedule_id,
                    "correlation_id": correlation_id,
                },
            )

            repository.mark_item_processing(message.job_id, message.item_key)
            request_payload = message.query.model_dump(mode="json")
            repository.add_audit_event(
                action="ASYNC_SCREENING_API_CALL_STARTED",
                user_id=message.user_id,
                user_name=message.user_name,
                entity_type="screening_item",
                entity_id=f"{message.job_id}:{message.item_key}",
                details={
                    "job_id": message.job_id,
                    "item_key": message.item_key,
                    "provider": settings.actimize_provider,
                    "operation": "screen_many_types",
                    "screening_types": message.screening_types,
                    "mock_screening": message.mock_screening,
                    "source_schedule_id": message.source_schedule_id,
                    "correlation_id": correlation_id,
                    "request": request_payload,
                },
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
                repository.add_audit_event(
                    action="ASYNC_SCREENING_API_CALL_SUCCEEDED",
                    user_id=message.user_id,
                    user_name=message.user_name,
                    entity_type="screening_item",
                    entity_id=f"{message.job_id}:{message.item_key}",
                    details={
                        "job_id": message.job_id,
                        "item_key": message.item_key,
                        "provider": settings.actimize_provider,
                        "operation": "screen_many_types",
                        "screening_types": message.screening_types,
                        "mock_screening": message.mock_screening,
                        "source_schedule_id": message.source_schedule_id,
                        "correlation_id": correlation_id,
                        "result_count": result_count,
                        "result": result,
                    },
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

                repository.add_external_api_error(
                    provider=provider,
                    operation=operation,
                    endpoint=endpoint,
                    status_code=status_code,
                    user_id=message.user_id,
                    user_name=message.user_name,
                    job_id=message.job_id,
                    item_key=message.item_key,
                    error_text=str(exc),
                    details={
                        "query": request_payload,
                        "screening_types": message.screening_types,
                        "mock_screening": message.mock_screening,
                        "source_schedule_id": message.source_schedule_id,
                        "correlation_id": correlation_id,
                        **api_details,
                    },
                )
                alert = repository.maybe_emit_high_risk_external_api_failure_alert(
                    provider=provider,
                    operation=operation,
                    threshold=settings.high_risk_external_api_error_threshold,
                    window_minutes=settings.high_risk_external_api_error_window_minutes,
                    correlation_id=correlation_id,
                )
                if alert and alert.get("new_alert_created"):
                    logger.warning(
                        "high risk external API failure alert: provider=%s operation=%s total=%s window_minutes=%s threshold=%s",
                        alert.get("provider"),
                        alert.get("operation"),
                        alert.get("total_errors"),
                        alert.get("window_minutes"),
                        alert.get("threshold"),
                    )
                repository.add_audit_event(
                    action="ASYNC_SCREENING_API_CALL_FAILED",
                    user_id=message.user_id,
                    user_name=message.user_name,
                    entity_type="screening_item",
                    entity_id=f"{message.job_id}:{message.item_key}",
                    details={
                        "job_id": message.job_id,
                        "item_key": message.item_key,
                        "provider": provider,
                        "operation": operation,
                        "endpoint": endpoint,
                        "status_code": status_code,
                        "screening_types": message.screening_types,
                        "mock_screening": message.mock_screening,
                        "source_schedule_id": message.source_schedule_id,
                        "correlation_id": correlation_id,
                        "request": request_payload,
                        "error": str(exc),
                        **api_details,
                    },
                )
                repository.mark_item_failed(message.job_id, message.item_key, str(exc))
                repository.add_audit_event(
                    action="ASYNC_SCREENING_ITEM_FAILED",
                    user_id=message.user_id,
                    user_name=message.user_name,
                    entity_type="screening_item",
                    entity_id=f"{message.job_id}:{message.item_key}",
                    details={
                        "job_id": message.job_id,
                        "item_key": message.item_key,
                        "correlation_id": correlation_id,
                        "error": str(exc),
                    },
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
                        logger.info(
                            "published %s schedule notifications for failed job=%s schedule=%s",
                            created_notifications,
                            message.job_id,
                            message.source_schedule_id,
                        )
            finally:
                queue.delete(receipt_handle)

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
