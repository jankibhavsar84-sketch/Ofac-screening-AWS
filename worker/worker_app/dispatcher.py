from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import time

from app.actimize import ActimizeClient
from app.config import settings
from app.queue import SqsQueue
from app.repository import JobRepository
from app.screening_service import ScreeningService
from app.sns_notifier import SnsNotifier
from worker_app.worker import (
    FixedRateLimiter,
    WorkerHealthState,
    _process_received_message,
    _receive_message_batch,
    _start_worker_health_server,
    trigger_due_daily_schedules,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("screening-dispatcher")


def run() -> None:
    dispatch_queue = SqsQueue(settings.aws_dispatch_sqs_queue_name)
    screening_queue = SqsQueue(settings.aws_screening_sqs_queue_name)
    if dispatch_queue.queue_name == screening_queue.queue_name:
        raise RuntimeError(
            "Dispatch queue and screening queue must be different. "
            "Configure AWS_DISPATCH_SQS_QUEUE_NAME and AWS_SCREENING_SQS_QUEUE_NAME."
        )

    dispatch_queue.ensure_queue()
    screening_queue.ensure_queue()

    repository = JobRepository(
        settings.app_db_path,
        settings.app_db_url,
    )
    notifier = SnsNotifier()
    service = ScreeningService(
        repository=repository,
        queue=screening_queue,
        notifier=notifier,
        dispatch_queue=dispatch_queue,
    )
    actimize = ActimizeClient(repository=repository)
    limiter = FixedRateLimiter(settings.screening_tps)
    last_schedule_check = 0.0
    last_cleanup_run = 0.0
    health_state = WorkerHealthState(settings.worker_health_max_age_s)
    health_server = _start_worker_health_server(health_state)

    max_parallel_messages = max(settings.screening_parallel_messages, 1)
    logger.info(
        "dispatcher started; dispatch_queue=%s screening_queue=%s max parallel messages=%s",
        dispatch_queue.queue_name,
        screening_queue.queue_name,
        max_parallel_messages,
    )
    health_state.touch()

    try:
        with ThreadPoolExecutor(max_workers=max_parallel_messages) as executor:
            while True:
                health_state.touch()
                messages = _receive_message_batch(dispatch_queue, max_parallel_messages)
                if messages:
                    futures = [
                        executor.submit(
                            _process_received_message,
                            raw=raw,
                            queue=dispatch_queue,
                            screening_queue=screening_queue,
                            repository=repository,
                            notifier=notifier,
                            actimize=actimize,
                            limiter=limiter,
                            dispatch_only=True,
                        )
                        for raw in messages
                    ]
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("unexpected dispatcher message failure: %s", exc)

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


if __name__ == "__main__":
    run()
