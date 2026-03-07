from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EntityExample(BaseModel):
    schema: str
    properties: dict[str, Any]


class ScoredEntity(BaseModel):
    id: str
    caption: str
    schema: str
    score: float | None = None
    match: bool
    datasets: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)


class EntityMatches(BaseModel):
    results: list[ScoredEntity]
    total: dict[str, Any]
    query: EntityExample
    status: int = 200


class EntityMatchResponse(BaseModel):
    responses: dict[str, EntityMatches]
    limit: int = 5


class MatchJobRequest(BaseModel):
    queries: dict[str, EntityExample]
    screening_types: list[str] = Field(default_factory=list)
    mock_screening: bool = False
    business_unit_code: str | None = None
    daily_screening: bool = False
    schedule_frequency: str = "DAILY"
    schedule_run_at: str | None = None
    schedule_id: str | None = None
    source_upload_id: str | None = None
    batch_name: str | None = None
    correlation_id: str | None = None
    user_id: str | None = None
    user_name: str | None = None


class JobStatus(str, Enum):
    queued = "QUEUED"
    processing = "PROCESSING"
    completed = "COMPLETED"
    failed = "FAILED"


class MatchJobAccepted(BaseModel):
    job_id: str
    status: JobStatus
    submitted_at: str
    total_items: int
    business_unit_code: str | None = None
    daily_schedule_id: str | None = None
    screened_item_keys: list[str] = Field(default_factory=list)


class MatchJobProgress(BaseModel):
    job_id: str
    status: JobStatus
    submitted_at: str
    total_items: int
    completed_items: int
    failed_items: int
    pending_items: int
    processing_items: int
    responses: dict[str, EntityMatches] | None = None
    limit: int | None = None


class DailyScheduleInfo(BaseModel):
    schedule_id: str
    batch_name: str
    user_id: str | None = None
    user_name: str | None = None
    business_unit_code: str | None = None
    screening_types: list[str] = Field(default_factory=list)
    schedule_frequency: str = "DAILY"
    timezone: str
    run_hour: int
    run_minute: int
    created_at: str
    last_run_at: str | None = None
    next_run_at: str
    total_items: int
    is_active: bool = True
    source_file_name: str | None = None
    source_s3_uri: str | None = None
    source_upload_id: str | None = None


class ScreeningQueueMessage(BaseModel):
    job_id: str
    item_key: str
    query: EntityExample
    submitted_at: str
    screening_types: list[str] = Field(default_factory=list)
    mock_screening: bool = False
    user_id: str | None = None
    user_name: str | None = None
    correlation_id: str | None = None
    source_schedule_id: str | None = None
    source_record_hash: str | None = None


class BatchUploadAccepted(BaseModel):
    job_id: str
    status: JobStatus
    submitted_at: str
    total_items: int
    business_unit_code: str | None = None
    daily_schedule_id: str | None = None
    screened_item_keys: list[str] = Field(default_factory=list)
    source_upload_id: str | None = None
    file_name: str
    s3_uri: str | None = None
    schedule_frequency: str | None = None


class BusinessUnit(BaseModel):
    business_unit_code: str
    business_unit_name: str
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None


class BusinessUnitUpsertRequest(BaseModel):
    business_unit_code: str
    business_unit_name: str


class BusinessUnitUpdateRequest(BaseModel):
    business_unit_code: str | None = None
    business_unit_name: str


class UserBusinessUnitMapping(BaseModel):
    user_id: str
    user_name: str | None = None
    business_unit_codes: list[str] = Field(default_factory=list)


class UserBusinessUnitUpdateRequest(BaseModel):
    user_name: str | None = None
    business_unit_codes: list[str] = Field(default_factory=list)


class AdminUserOption(BaseModel):
    user_id: str
    display_name: str


class ScheduleSubscription(BaseModel):
    subscription_id: str
    schedule_id: str
    user_id: str | None = None
    user_name: str | None = None
    email: str
    is_active: bool = True
    created_at: str


class AuditEvent(BaseModel):
    event_id: int
    created_at: str
    user_id: str | None = None
    user_name: str | None = None
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
