"""Categorization request/response schemas (DSD §6.2).

Pydantic v2: ORM responses use ConfigDict(from_attributes=True).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

TagNameStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
TagDescStr = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=2000)
]


class TagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    color: str | None = None
    created_at: datetime


class TagWithUsageResponse(TagResponse):
    """Tag plus its current usage count (contacts using it)."""

    usage_count: int


class TagListResponse(BaseModel):
    items: list[TagWithUsageResponse]
    total: int
    limit: int
    offset: int


class TagCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: TagNameStr
    description: TagDescStr | None = None
    color: str | None = Field(default=None)

    @field_validator("color")
    @classmethod
    def _check_color(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not _COLOR_RE.match(v):
            raise ValueError("color must match ^#[0-9A-Fa-f]{6}$")
        return v


class TagUpdateRequest(BaseModel):
    """Partial update. All fields optional; service rejects empty body."""

    model_config = ConfigDict(extra="forbid")

    name: TagNameStr | None = None
    description: TagDescStr | None = None
    color: str | None = Field(default=None)

    @field_validator("color")
    @classmethod
    def _check_color(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not _COLOR_RE.match(v):
            raise ValueError("color must match ^#[0-9A-Fa-f]{6}$")
        return v


class TagSuggestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contact_id: uuid.UUID
    tag_id: uuid.UUID
    confidence: float | None = None
    reason: str | None = None
    status: str
    reviewed_by: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class TagSuggestionDecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class TagSuggestionListFilters(BaseModel):
    """Query-param filters for GET /tag-suggestions. Bound via Depends()."""

    status: str | None = None
    contact_id: uuid.UUID | None = None


class ContactTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    contact_id: uuid.UUID
    tag_id: uuid.UUID
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
