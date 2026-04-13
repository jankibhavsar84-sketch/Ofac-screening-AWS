from __future__ import annotations

import json
from typing import Any

import boto3

from .config import settings
from .models import ScreeningQueueMessage


class SqsQueue:
    def __init__(self) -> None:
        client_kwargs: dict[str, Any] = {
            "service_name": "sqs",
            "region_name": settings.aws_region,
        }
        # Prefer ECS task-role credentials unless explicit keys are provided.
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_endpoint_url:
            client_kwargs["endpoint_url"] = settings.aws_endpoint_url
        self.client = boto3.client(**client_kwargs)
        self.queue_url: str | None = None

    def ensure_queue(self) -> str:
        if self.queue_url:
            return self.queue_url
        created = self.client.create_queue(QueueName=settings.aws_sqs_queue_name)
        self.queue_url = str(created["QueueUrl"])
        return self.queue_url

    def enqueue(self, message: ScreeningQueueMessage, delay_seconds: int = 0) -> None:
        queue_url = self.ensure_queue()
        params: dict[str, Any] = {
            "QueueUrl": queue_url,
            "MessageBody": message.model_dump_json(),
        }
        safe_delay = max(0, min(int(delay_seconds), 900))
        if safe_delay:
            params["DelaySeconds"] = safe_delay
        self.client.send_message(**params)

    def enqueue_batch(self, messages: list[ScreeningQueueMessage]) -> None:
        if not messages:
            return
        queue_url = self.ensure_queue()
        # SQS SendMessageBatch supports up to 10 messages per request.
        entries = [
            {"Id": str(i), "MessageBody": msg.model_dump_json()}
            for i, msg in enumerate(messages[:10])
        ]
        resp = self.client.send_message_batch(QueueUrl=queue_url, Entries=entries)
        failed = resp.get("Failed") or []
        if failed:
            first = failed[0]
            raise RuntimeError(f"SQS batch enqueue failed: {first}")

    def change_visibility(self, receipt_handle: str, timeout_seconds: int) -> None:
        queue_url = self.ensure_queue()
        self.client.change_message_visibility(
            QueueUrl=queue_url,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=max(int(timeout_seconds), 0),
        )

    def receive(self, max_messages: int = 10, wait_time_seconds: int = 20) -> list[dict[str, Any]]:
        queue_url = self.ensure_queue()
        response = self.client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_time_seconds,
            VisibilityTimeout=60,
        )
        return response.get("Messages", [])

    def decode(self, raw_message: dict[str, Any]) -> ScreeningQueueMessage:
        body = raw_message.get("Body", "{}")
        if isinstance(body, str):
            payload = json.loads(body)
        else:
            payload = body
        return ScreeningQueueMessage.model_validate(payload)

    def delete(self, receipt_handle: str) -> None:
        queue_url = self.ensure_queue()
        self.client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
