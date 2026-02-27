from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from .actimize import ActimizeClient
from .config import settings
from .models import MatchJobRequest
from .queue import SqsQueue
from .repository import JobRepository
from .screening_service import ScreeningService

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


def run() -> None:
    queue = SqsQueue()
    queue.ensure_queue()
    repository = JobRepository(settings.app_db_path, settings.app_db_url)
    service = ScreeningService(repository=repository, queue=queue)
    actimize = ActimizeClient()
    limiter = FixedRateLimiter(settings.screening_tps)
    last_schedule_check = 0.0

    logger.info("worker started with max TPS=%s", settings.screening_tps)

    while True:
        messages = queue.receive(max_messages=10, wait_time_seconds=20)

        for raw in messages:
            receipt_handle = raw.get("ReceiptHandle")
            if not receipt_handle:
                continue

            try:
                message = queue.decode(raw)
            except Exception as exc:  # noqa: BLE001
                logger.exception("invalid message payload: %s", exc)
                queue.delete(receipt_handle)
                continue

            repository.mark_item_processing(message.job_id, message.item_key)

            try:
                limiter.wait_turn()
                result = actimize.screen_many_types(
                    message.query,
                    message.screening_types,
                    message.mock_screening,
                )
                repository.mark_item_completed(message.job_id, message.item_key, result)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "screening failed for job=%s key=%s: %s",
                    message.job_id,
                    message.item_key,
                    exc,
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
                        "error": str(exc),
                    },
                )
            finally:
                queue.delete(receipt_handle)

        now_monotonic = time.monotonic()
        if now_monotonic - last_schedule_check >= max(settings.daily_screening_check_interval_s, 5):
            trigger_due_daily_schedules(repository, service)
            last_schedule_check = now_monotonic


def trigger_due_daily_schedules(repository: JobRepository, service: ScreeningService) -> None:
    now_utc = datetime.now(timezone.utc)
    due_schedules = repository.list_due_daily_schedules(now_utc.isoformat())
    for schedule in due_schedules:
        next_run_at = JobRepository.compute_next_run_at(
            now_utc=now_utc,
            timezone_name=schedule["timezone"],
            run_hour=schedule["run_hour"],
            run_minute=schedule["run_minute"],
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
            payload = MatchJobRequest(
                queries=schedule["queries"],
                screening_types=schedule["screening_types"],
                mock_screening=bool(schedule["mock_screening"]),
                daily_screening=False,
                batch_name=schedule["batch_name"],
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
            repository.add_audit_event(
                action="DAILY_SCHEDULE_TRIGGERED",
                user_id=schedule.get("user_id"),
                user_name=schedule.get("user_name"),
                entity_type="daily_schedule",
                entity_id=schedule["schedule_id"],
                details={"job_id": accepted.job_id, "batch_name": schedule["batch_name"]},
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
