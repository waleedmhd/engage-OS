"""Assignment request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LockRequest(BaseModel):
    agent_id: uuid.UUID


class LockResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: uuid.UUID
    locked_by: uuid.UUID
    expires_at: datetime
