from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3

from .config import settings

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_SAFE_PATH_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(filename: str) -> str:
    raw = Path(filename or "").name.strip()
    if not raw:
        return "upload.csv"
    sanitized = _SAFE_FILENAME_RE.sub("_", raw).strip("._")
    return sanitized or "upload.csv"


def _safe_segment(value: str, fallback: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return fallback
    sanitized = _SAFE_PATH_SEGMENT_RE.sub("_", raw).strip("._")
    return sanitized or fallback


class S3FileStore:
    def __init__(self) -> None:
        client_kwargs: dict[str, Any] = {
            "service_name": "s3",
            "region_name": settings.aws_region,
        }
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_endpoint_url:
            client_kwargs["endpoint_url"] = settings.aws_endpoint_url

        self.client = boto3.client(**client_kwargs)
        self.bucket = settings.aws_s3_upload_bucket
        self.prefix = settings.aws_s3_upload_prefix.strip("/ ")
        self._bucket_checked = False

    def is_enabled(self) -> bool:
        return bool(self.bucket)

    def ensure_bucket(self) -> None:
        if not self.bucket or self._bucket_checked:
            return

        try:
            self.client.head_bucket(Bucket=self.bucket)
            self._bucket_checked = True
            return
        except Exception:
            pass

        create_kwargs: dict[str, Any] = {"Bucket": self.bucket}
        region = (settings.aws_region or "").strip()
        if region and region != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        try:
            self.client.create_bucket(**create_kwargs)
            self._bucket_checked = True
        except Exception:
            # Do not fail here; put_object may still work if bucket already exists
            # but caller lacks create/head permissions.
            self._bucket_checked = False

    def upload_source_file(
        self,
        *,
        job_id: str,
        user_id: str,
        original_filename: str,
        body: bytes,
        content_type: str | None = None,
    ) -> dict[str, str]:
        if not self.bucket:
            raise RuntimeError("AWS_S3_UPLOAD_BUCKET is not configured")
        if not body:
            raise RuntimeError("Cannot upload empty file")
        self.ensure_bucket()

        safe_job_id = _safe_segment(job_id, "unknown_job")
        safe_user_id = _safe_segment(user_id, "unknown_user")
        safe_name = _safe_filename(original_filename)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        key = f"{self.prefix}/{safe_user_id}/{safe_job_id}/{timestamp}_{safe_name}"

        put_kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": body,
        }
        if content_type and content_type.strip():
            put_kwargs["ContentType"] = content_type.strip()

        self.client.put_object(**put_kwargs)
        return {
            "bucket": self.bucket,
            "key": key,
            "s3_uri": f"s3://{self.bucket}/{key}",
            "file_name": safe_name,
        }
