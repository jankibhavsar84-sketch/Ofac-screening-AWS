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
    score: float
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
    daily_screening: bool = False
    batch_name: str | None = None
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
    daily_schedule_id: str | None = None


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
    screening_types: list[str] = Field(default_factory=list)
    timezone: str
    run_hour: int
    run_minute: int
    created_at: str
    last_run_at: str | None = None
    next_run_at: str
    total_items: int
    is_active: bool = True


class ScreeningQueueMessage(BaseModel):
    job_id: str
    item_key: str
    query: EntityExample
    submitted_at: str
    screening_types: list[str] = Field(default_factory=list)
    mock_screening: bool = False
    user_id: str | None = None
    user_name: str | None = None


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
