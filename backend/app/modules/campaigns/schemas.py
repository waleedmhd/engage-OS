"""Campaign request/response schemas (DSD §6.2)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.modules.campaigns.constants import (
    CampaignRecipientStatus,
    CampaignStatus,
    CampaignType,
)

_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

CampaignCategoryNameStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
CampaignCategoryDescStr = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=2000)
]


class CampaignErrorBreakdownItem(BaseModel):
    error_message: str
    error_code: int | None = None
    count: int


# ---------------------------------------------------------------- audience

class AudienceFilter(BaseModel):
    """Audience segmentation criteria. Persisted on Campaign.audience_filter
    so a campaign can be re-materialised (recurring runs) with the same rules.
    """

    tags: list[uuid.UUID] = Field(default_factory=list)
    status: list[str] = Field(default_factory=list)
    assigned_agent_id: uuid.UUID | None = None
    last_interaction_after: datetime | None = None
    last_interaction_before: datetime | None = None
    contact_ids: list[uuid.UUID] = Field(default_factory=list)
    # marketing_opt_out=True contacts are always excluded — this is a
    # compliance gate, not a per-campaign opt-in toggle.


# ---------------------------------------------------------------- requests

class CampaignCreateRequest(BaseModel):
    template_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(default=CampaignType.IMMEDIATE.value)
    scheduled_at: datetime | None = None
    cron_expression: str | None = Field(default=None, max_length=100)
    audience_filter: AudienceFilter = Field(default_factory=AudienceFilter)
    rate_limit_per_second: int | None = Field(default=None, ge=1, le=1000)
    category_id: uuid.UUID | None = None

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        valid = {t.value for t in CampaignType}
        if v not in valid:
            raise ValueError(f"type must be one of {sorted(valid)}")
        return v

    @model_validator(mode="after")
    def _validate_schedule(self) -> CampaignCreateRequest:
        if self.type == CampaignType.SCHEDULED.value:
            if self.scheduled_at is None:
                raise ValueError("scheduled_at is required for type=scheduled")
            now = datetime.now(UTC)
            ts = self.scheduled_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts < now:
                raise ValueError("scheduled_at must be in the future")
        if self.type == CampaignType.RECURRING.value:
            if not self.cron_expression:
                raise ValueError("cron_expression is required for type=recurring")
            try:
                from croniter import croniter

                if not croniter.is_valid(self.cron_expression):
                    raise ValueError(f"invalid cron_expression: {self.cron_expression!r}")
            except ImportError:
                # croniter is a runtime requirement; if missing the worker
                # will fail loudly when the scheduler runs. We do not silently
                # accept invalid expressions here.
                raise ValueError("croniter not installed; cannot validate cron_expression") from None
        return self


class CampaignUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    scheduled_at: datetime | None = None
    cron_expression: str | None = Field(default=None, max_length=100)
    audience_filter: AudienceFilter | None = None
    rate_limit_per_second: int | None = Field(default=None, ge=1, le=1000)
    category_id: uuid.UUID | None = None


class CampaignLaunchRequest(BaseModel):
    confirm: bool = True


# ---------------------------------------------------------------- responses

class ComplianceError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_id: uuid.UUID
    name: str
    status: str
    type: str
    scheduled_at: datetime | None = None
    cron_expression: str | None = None
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    audience_filter: dict[str, Any] = Field(default_factory=dict)
    rate_limit_per_second: int | None = None
    audience_count: int = 0
    sent_count: int = 0
    delivered_count: int = 0
    failed_count: int = 0
    response_count: int = 0
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    created_by: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class CampaignValidationResponse(BaseModel):
    ok: bool
    recipient_count: int
    errors: list[ComplianceError] = Field(default_factory=list)


class CampaignReportResponse(BaseModel):
    campaign_id: uuid.UUID
    status: str
    audience_count: int
    sent_count: int
    delivered_count: int
    failed_count: int
    response_count: int
    pending_count: int
    delivery_rate: float
    failure_rate: float
    response_rate: float
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    status_breakdown: dict[str, int] = Field(default_factory=dict)
    error_breakdown: list[CampaignErrorBreakdownItem] = Field(default_factory=list)


class CampaignRecipientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    contact_id: uuid.UUID
    message_id: uuid.UUID | None = None
    status: str
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    failed_at: datetime | None = None
    responded: bool
    attempt_count: int
    error_message: str | None = None
    error_code: int | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        valid = {s.value for s in CampaignRecipientStatus}
        if v not in valid:
            raise ValueError(f"status must be one of {sorted(valid)}")
        return v


# ------------------------------------------------------- category taxonomy

class CampaignCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    color: str | None = None
    created_at: datetime


class CampaignCategoryWithUsageResponse(CampaignCategoryResponse):
    """Category plus the current count of campaigns referencing it."""

    usage_count: int


class CampaignCategoryListResponse(BaseModel):
    items: list[CampaignCategoryWithUsageResponse]
    total: int
    limit: int
    offset: int


class CampaignCategoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CampaignCategoryNameStr
    description: CampaignCategoryDescStr | None = None
    color: str | None = Field(default=None)

    @field_validator("color")
    @classmethod
    def _check_color(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not _COLOR_RE.match(v):
            raise ValueError("color must match ^#[0-9A-Fa-f]{6}$")
        return v


class CampaignCategoryUpdateRequest(BaseModel):
    """Partial update. All fields optional; service rejects empty body."""

    model_config = ConfigDict(extra="forbid")

    name: CampaignCategoryNameStr | None = None
    description: CampaignCategoryDescStr | None = None
    color: str | None = Field(default=None)

    @field_validator("color")
    @classmethod
    def _check_color(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not _COLOR_RE.match(v):
            raise ValueError("color must match ^#[0-9A-Fa-f]{6}$")
        return v


__all__ = [
    "AudienceFilter",
    "CampaignCategoryCreateRequest",
    "CampaignCategoryListResponse",
    "CampaignCategoryResponse",
    "CampaignCategoryUpdateRequest",
    "CampaignCategoryWithUsageResponse",
    "CampaignCreateRequest",
    "CampaignErrorBreakdownItem",
    "CampaignLaunchRequest",
    "CampaignRecipientResponse",
    "CampaignReportResponse",
    "CampaignResponse",
    "CampaignStatus",
    "CampaignUpdateRequest",
    "CampaignValidationResponse",
    "ComplianceError",
]
