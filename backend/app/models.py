from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


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
    engine_message: str | None = None
    error_text: str | None = None
    responses_by_screening_type: dict[str, dict[str, Any]] | None = None


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
    schedule_id: int | None = None
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
    job_id: str | int
    status: JobStatus
    submitted_at: str
    total_items: int
    business_unit_code: str | None = None
    daily_schedule_id: int | None = None
    screened_item_keys: list[str] = Field(default_factory=list)


class MatchJobProgress(BaseModel):
    job_id: str | int
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
    schedule_id: int
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


class DailyScheduleInfoPage(BaseModel):
    items: list[DailyScheduleInfo] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 10
    total_pages: int = 1


class DailyScheduleBatchRunStatus(BaseModel):
    job_id: str | int
    schedule_id: int
    batch_name: str
    schedule_frequency: str | None = None
    source_file_name: str | None = None
    source_upload_id: str | None = None
    status: str
    run_status: str
    total_items: int
    completed_items: int
    failed_items: int
    pending_items: int
    processing_items: int
    submitted_at: str
    updated_at: str
    user_id: str | None = None
    user_name: str | None = None


class DailyScheduleBatchRunStatusPage(BaseModel):
    items: list[DailyScheduleBatchRunStatus] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 10
    total_pages: int = 1


class ScreeningQueueMessage(BaseModel):
    # Backwards-compatible with older queue messages that didn't include message_type.
    # message_type="SCREEN_ITEM" is a standard per-record screening task.
    # message_type="JOB_DISPATCH" is a lightweight control message that expands/enqueues
    # per-record tasks in the worker (used to avoid API timeouts on large batches).
    message_type: str = "SCREEN_ITEM"
    job_id: str | int
    item_key: str | None = None
    query: EntityExample | None = None
    submitted_at: str
    screening_types: list[str] = Field(default_factory=list)
    mock_screening: bool = False
    user_id: str | None = None
    user_name: str | None = None
    correlation_id: str | None = None
    business_unit_code: str | None = None
    source_schedule_id: int | None = None
    source_record_hash: str | None = None
    source_upload_id: str | None = None
    retry_attempt: int = 0

    @field_validator("source_schedule_id", mode="before")
    @classmethod
    def _coerce_source_schedule_id(cls, value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        raw = str(value).strip()
        if not raw:
            return None
        return int(raw)

    @model_validator(mode="after")
    def _validate_shape(self) -> "ScreeningQueueMessage":
        safe_type = str(self.message_type or "").strip().upper() or "SCREEN_ITEM"
        self.message_type = safe_type
        self.retry_attempt = max(int(self.retry_attempt or 0), 0)

        if safe_type == "JOB_DISPATCH":
            # JOB_DISPATCH messages must not carry a query payload and may omit item_key.
            self.item_key = (self.item_key or "").strip() or None
            self.query = None
            return self

        # Default: SCREEN_ITEM
        if not (self.item_key or "").strip():
            raise ValueError("item_key is required for SCREEN_ITEM messages")
        if self.query is None:
            raise ValueError("query is required for SCREEN_ITEM messages")
        return self


class BatchUploadRowMeta(BaseModel):
    key: str
    display_name: str
    ui_type: str


class BatchUploadAccepted(BaseModel):
    job_id: str | int
    status: JobStatus
    submitted_at: str
    total_items: int
    business_unit_code: str | None = None
    daily_schedule_id: int | None = None
    screened_item_keys: list[str] = Field(default_factory=list)
    source_upload_id: str | None = None
    file_name: str
    s3_uri: str | None = None
    schedule_frequency: str | None = None
    row_meta: list[BatchUploadRowMeta] = Field(default_factory=list)


class ActimizeAlertCallbackRequest(BaseModel):
    unique_key: str
    alert_id: str
    screening_cd: str | None = None
    status_cd: str
    update_timestamp: str | None = None
    source_system_cd: str | None = None
    tenant_cd: str | None = None

    @model_validator(mode="after")
    def _validate_and_normalize(self) -> "ActimizeAlertCallbackRequest":
        self.unique_key = str(self.unique_key or "").strip()
        self.alert_id = str(self.alert_id or "").strip()
        self.screening_cd = str(self.screening_cd or "").strip() or None
        self.status_cd = str(self.status_cd or "").strip().upper()
        self.update_timestamp = str(self.update_timestamp or "").strip() or None
        self.source_system_cd = str(self.source_system_cd or "").strip() or None
        self.tenant_cd = str(self.tenant_cd or "").strip() or None

        if not self.unique_key:
            raise ValueError("unique_key is required")
        if not self.alert_id:
            raise ValueError("alert_id is required")
        if self.status_cd not in {"F", "T"}:
            raise ValueError("status_cd must be F or T")
        return self


class ActimizeAlertCallbackAccepted(BaseModel):
    status: str = "ACCEPTED"
    callback_id: int
    unique_key: str
    alert_id: str
    status_cd: str
    matched_items: int = 0
    processed_at: str


class BusinessUnit(BaseModel):
    business_unit_code: str
    business_unit_name: str
    is_active: bool = True


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
    schedule_id: int
    user_id: str | None = None
    user_name: str | None = None
    email: str
    is_active: bool = True
    created_at: str


class ScreeningTypeOption(BaseModel):
    value: str
    label: str
    screening_type: str
    search_definition_id: str
    search_definition_name: str = ""
    display_order: int = 1000


class AuditEvent(BaseModel):
    event_id: int
    created_at: str
    user_id: str | None = None
    user_name: str | None = None
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AuditEventPage(BaseModel):
    items: list[AuditEvent] = Field(default_factory=list)
    total: int = 0
    limit: int
    offset: int


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
