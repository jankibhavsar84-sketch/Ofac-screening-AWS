from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import boto3

from .config import settings


class SnsNotifier:
    def __init__(self) -> None:
        self.enabled = bool(settings.aws_sns_notifications_enabled)
        self.topic_prefix = self._sanitize_topic_prefix(settings.aws_sns_schedule_topic_prefix)
        self.ses_sender_email = str(settings.aws_ses_sender_email or "").strip()
        client_kwargs: dict[str, Any] = {
            "region_name": settings.aws_region,
        }
        # Prefer ECS task-role credentials unless explicit keys are provided.
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_endpoint_url:
            client_kwargs["endpoint_url"] = settings.aws_endpoint_url
        self.sns_client = boto3.client(service_name="sns", **client_kwargs)
        self.ses_client = boto3.client(service_name="sesv2", **client_kwargs)

    @property
    def _use_ses(self) -> bool:
        # Prefer direct SES email delivery whenever sender identity is configured.
        # This avoids SNS email subscription confirmation requirements.
        return bool(self.ses_sender_email)

    @staticmethod
    def _sanitize_topic_prefix(raw: str | None) -> str:
        safe = re.sub(r"[^A-Za-z0-9_-]", "-", str(raw or "").strip()).strip("-")
        return safe or "ofac-screening-schedule"

    def _topic_name_for_schedule(self, schedule_id: str) -> str:
        safe_schedule_id = str(schedule_id or "").strip()
        if not safe_schedule_id:
            raise ValueError("schedule_id is required")
        digest = hashlib.sha1(safe_schedule_id.encode("utf-8")).hexdigest()[:18]
        name = f"{self.topic_prefix}-{digest}"
        return name[:256]

    def _topic_name_for_email(self, email: str) -> str:
        safe_email = str(email or "").strip().lower()
        if not safe_email:
            raise ValueError("email is required")
        digest = hashlib.sha1(safe_email.encode("utf-8")).hexdigest()[:18]
        name = f"{self.topic_prefix}-email-{digest}"
        return name[:256]

    def ensure_schedule_topic(self, schedule_id: str) -> str:
        if self._use_ses:
            return ""
        name = self._topic_name_for_schedule(schedule_id)
        created = self.sns_client.create_topic(Name=name)
        topic_arn = str(created.get("TopicArn") or "").strip()
        if not topic_arn:
            raise RuntimeError(f"Failed to create SNS topic for schedule {schedule_id}")
        return topic_arn

    def ensure_email_topic(self, email: str) -> str:
        if self._use_ses:
            return ""
        name = self._topic_name_for_email(email)
        created = self.sns_client.create_topic(Name=name)
        topic_arn = str(created.get("TopicArn") or "").strip()
        if not topic_arn:
            raise RuntimeError(f"Failed to create SNS topic for email {email}")
        return topic_arn

    def _iter_topic_subscriptions(self, topic_arn: str) -> list[dict[str, Any]]:
        if self._use_ses or not topic_arn:
            return []
        token: str | None = None
        subscriptions: list[dict[str, Any]] = []
        while True:
            kwargs: dict[str, Any] = {"TopicArn": topic_arn}
            if token:
                kwargs["NextToken"] = token
            page = self.sns_client.list_subscriptions_by_topic(**kwargs)
            subscriptions.extend(page.get("Subscriptions", []) or [])
            token = page.get("NextToken")
            if not token:
                break
        return subscriptions

    def ensure_email_subscription(self, schedule_id: str, email: str) -> dict[str, Any]:
        safe_email = str(email or "").strip().lower()
        if not safe_email:
            raise ValueError("email is required")
        if self._use_ses:
            return {
                "topic_arn": None,
                "subscription_arn": None,
                "pending_confirmation": False,
                "created": False,
            }

        # Email subscriptions are keyed by recipient (not schedule) so users do not
        # receive a fresh SNS confirmation request every time a new schedule is created.
        topic_arn = self.ensure_email_topic(safe_email)
        existing_sub_arn: str | None = None
        pending = False
        for sub in self._iter_topic_subscriptions(topic_arn):
            protocol = str(sub.get("Protocol") or "").strip().lower()
            endpoint = str(sub.get("Endpoint") or "").strip().lower()
            if protocol != "email" or endpoint != safe_email:
                continue
            sub_arn_raw = str(sub.get("SubscriptionArn") or "").strip()
            if sub_arn_raw and sub_arn_raw != "PendingConfirmation":
                existing_sub_arn = sub_arn_raw
                pending = False
            else:
                existing_sub_arn = None
                pending = True
            break

        if existing_sub_arn or pending:
            return {
                "topic_arn": topic_arn,
                "subscription_arn": existing_sub_arn,
                "pending_confirmation": pending,
                "created": False,
            }

        response = self.sns_client.subscribe(
            TopicArn=topic_arn,
            Protocol="email",
            Endpoint=safe_email,
            ReturnSubscriptionArn=True,
        )
        sub_arn = str(response.get("SubscriptionArn") or "").strip()
        is_pending = (not sub_arn) or sub_arn == "PendingConfirmation"
        return {
            "topic_arn": topic_arn,
            "subscription_arn": None if is_pending else sub_arn,
            "pending_confirmation": is_pending,
            "created": True,
        }

    def unsubscribe_email(self, schedule_id: str, email: str) -> int:
        safe_email = str(email or "").strip().lower()
        if not safe_email:
            return 0
        if self._use_ses:
            return 0
        topic_arn = self.ensure_email_topic(safe_email)
        removed = 0
        for sub in self._iter_topic_subscriptions(topic_arn):
            protocol = str(sub.get("Protocol") or "").strip().lower()
            endpoint = str(sub.get("Endpoint") or "").strip().lower()
            if protocol != "email" or endpoint != safe_email:
                continue
            sub_arn = str(sub.get("SubscriptionArn") or "").strip()
            if not sub_arn or sub_arn == "PendingConfirmation":
                continue
            self.sns_client.unsubscribe(SubscriptionArn=sub_arn)
            removed += 1
        return removed

    def publish_schedule_completion(
        self,
        schedule_id: str,
        title: str,
        message: str,
        summary: dict[str, Any] | None = None,
        email: str | None = None,
    ) -> str:
        safe_subject = str(title or "").strip() or "Scheduled screening completed"
        safe_subject = safe_subject[:100]
        base_message = str(message or "").strip()
        details = ""
        if isinstance(summary, dict) and summary:
            details = f"\n\nSummary:\n{json.dumps(summary, indent=2, sort_keys=True)}"
        final_message = f"{base_message}{details}".strip()
        if self._use_ses:
            if not email:
                raise ValueError("email is required when SES notification delivery is enabled")
            response = self.ses_client.send_email(
                FromEmailAddress=self.ses_sender_email,
                Destination={"ToAddresses": [str(email).strip()]},
                Content={
                    "Simple": {
                        "Subject": {"Data": safe_subject, "Charset": "UTF-8"},
                        "Body": {"Text": {"Data": final_message, "Charset": "UTF-8"}},
                    }
                },
            )
            message_id = str(response.get("MessageId") or "").strip()
            if not message_id:
                raise RuntimeError("SES send_email returned no MessageId")
            return message_id

        topic_arn = self.ensure_email_topic(email) if email else self.ensure_schedule_topic(schedule_id)
        response = self.sns_client.publish(
            TopicArn=topic_arn,
            Subject=safe_subject,
            Message=final_message,
        )
        message_id = str(response.get("MessageId") or "").strip()
        if not message_id:
            raise RuntimeError("SNS publish returned no MessageId")
        return message_id
