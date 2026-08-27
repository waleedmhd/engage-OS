"""User management request/response schemas (admin surface)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.modules.auth.constants import UserRole

# Shared password constraints — same rule for create and reset.
PasswordStr = Annotated[
    str, StringConstraints(min_length=8, max_length=128, strip_whitespace=False)
]

NameStr = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str | None = None
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    name: NameStr | None = None
    role: UserRole
    password: PasswordStr


class UserUpdateRequest(BaseModel):
    """Partial update. All fields optional; at least one required."""

    model_config = ConfigDict(extra="forbid")

    name: NameStr | None = Field(default=None)
    email: EmailStr | None = Field(default=None)
    role: UserRole | None = Field(default=None)
    is_active: bool | None = Field(default=None)


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: PasswordStr


class UserSectionsResponse(BaseModel):
    sections: list[str]


class UserSectionsUpdateRequest(BaseModel):
    """Replace the user's accessible sections with the given list."""

    model_config = ConfigDict(extra="forbid")

    sections: list[str]
