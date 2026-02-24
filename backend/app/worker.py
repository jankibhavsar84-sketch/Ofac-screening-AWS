from __future__ import annotations

import logging
import time

from .actimize import ActimizeClient
from .config import settings
from .queue import SqsQueue
from .repository import JobRepository

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
    repository = JobRepository(settings.app_db_path)
    actimize = ActimizeClient()
    limiter = FixedRateLimiter(settings.screening_tps)

    logger.info("worker started with max TPS=%s", settings.screening_tps)

    while True:
        messages = queue.receive(max_messages=10, wait_time_seconds=20)
        if not messages:
            continue

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
                result = actimize.screen_single(message.query)
                repository.mark_item_completed(message.job_id, message.item_key, result)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "screening failed for job=%s key=%s: %s",
                    message.job_id,
                    message.item_key,
                    exc,
                )
                repository.mark_item_failed(message.job_id, message.item_key, str(exc))
            finally:
                queue.delete(receipt_handle)


if __name__ == "__main__":
    run()

