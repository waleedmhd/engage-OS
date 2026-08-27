"""Auth request/response schemas."""

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    name: str | None = None
    is_active: bool
    accessible_sections: list[str] = []


# Phase 4.5 router/service expect these names. Same shape as the originals;
# aliases preserved so both old and new callers work.
LoginResponse = TokenResponse
RefreshResponse = TokenResponse
UserResponse = CurrentUserResponse
