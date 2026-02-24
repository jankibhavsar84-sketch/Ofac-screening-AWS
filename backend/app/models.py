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


class ScreeningQueueMessage(BaseModel):
    job_id: str
    item_key: str
    query: EntityExample
    submitted_at: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

