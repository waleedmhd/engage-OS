"""Messaging request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MediaAssetBrief(BaseModel):
    """Compact media asset info embedded in MessageResponse."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    media_type: str
    file_path: str
    mime_type: str | None = None
    duration_seconds: float | None = None


class ContextMessageBrief(BaseModel):
    """Minimal info about the message being replied to or forwarded from."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content: str
    msg_type: str = "text"


class SendMessageRequest(BaseModel):
    """Phase 4.5: router uses .content (was .body in the placeholder)."""

    conversation_id: uuid.UUID
    content: str
    template_name: str | None = None
    media_asset_id: uuid.UUID | None = None
    context_message_id: uuid.UUID | None = None
    msg_type: str | None = None         # 'contact' for contact cards
    contact_name: str | None = None     # for contact cards
    contact_phones: list[str] | None = None  # for contact cards


class MessageResponse(BaseModel):
    """ORM-validatable. Msg-M8: created_at and meta_message_id are required by
    the frontend for ordering and dedup."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    direction: str
    sender_type: str
    content: str
    delivery_status: str
    msg_type: str = "text"
    meta_message_id: str | None = None
    created_at: datetime | None = None
    media: list[MediaAssetBrief] = []
    context_message_id: uuid.UUID | None = None
    context_message: ContextMessageBrief | None = None
    last_error: str | None = None
    error_code: int | None = None


class ForwardMessageRequest(BaseModel):
    """Forward a message to another conversation."""

    target_conversation_id: uuid.UUID


class BulkForwardRequest(BaseModel):
    message_ids: list[uuid.UUID]
    target_conversation_id: uuid.UUID


class BulkDeleteRequest(BaseModel):
    message_ids: list[uuid.UUID]
    scope: str = "for_me"  # 'for_me' | 'for_everyone'


class BulkActionResponse(BaseModel):
    count: int
    errors: list[str] = []


class MessageListResponse(BaseModel):
    items: list[MessageResponse] = []
    total: int = 0


# Phase 4.5 router uses these names. Same shape as the originals.
MessageSendRequest = SendMessageRequest
SendMessageResponse = MessageResponse


class StartConversationRequest(BaseModel):
    """Initiate an outbound conversation with a contact using an approved template."""

    contact_id: uuid.UUID
    template_id: uuid.UUID


class StartConversationResponse(BaseModel):
    """Returned by POST /messages/start — the resolved conversation + queued message."""

    conversation_id: uuid.UUID
    message: MessageResponse
