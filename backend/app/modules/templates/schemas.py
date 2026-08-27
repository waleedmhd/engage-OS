"""Template request/response schemas (DSD §6.2)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.templates.constants import TemplateCategory


class TemplateSubmitRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: TemplateCategory = TemplateCategory.UTILITY
    language: str = Field(default="en", min_length=2, max_length=16)
    body: str = Field(min_length=1, max_length=4096)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, v: str) -> str:
        # Meta requires lowercase snake_case template names.
        normalized = v.strip().lower().replace(" ", "_").replace("-", "_")
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


class TemplateImportResult(BaseModel):
    imported: int
    updated: int


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    meta_template_id: str | None
    name: str
    status: str
    category: str
    language: str
    body: str | None
    created_at: datetime
    updated_at: datetime
