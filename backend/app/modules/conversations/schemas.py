"""Conversation request/response schemas (DSD §6.2)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.modules.conversations.constants import ConversationState


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contact_id: uuid.UUID
    state: str
    ai_enabled: bool
    locked_by: uuid.UUID | None = None
    lock_expires_at: datetime | None = None
    last_message_at: datetime | None = None
    contact: ConversationContactSummary | None = Field(default=None, init=False)
    allowed_transitions: list[str] = Field(default_factory=list)


class ConversationListResponse(BaseModel):
    """Legacy list shape — retained for backwards compatibility with tests
    or callers that depend on the older flat envelope. New callers should
    consume Page[ConversationListItem] from GET /conversations."""

    items: list[ConversationResponse] = []
    total: int = 0


class ConversationAssignRequest(BaseModel):
    agent_id: uuid.UUID


class ConversationTransitionRequest(BaseModel):
    target_state: ConversationState = Field(..., description="Target state")

    @field_validator("target_state", mode="before")
    @classmethod
    def normalise_state(cls, v: object) -> object:
        return v.upper() if isinstance(v, str) else v


# Phase 4.5 router uses the shorter name.
AssignRequest = ConversationAssignRequest


# --------------------------------------------------------------- inbox DTOs


class ConversationContactSummary(BaseModel):
    """Slim contact projection embedded in inbox items.

    Avoids returning the full ContactResponse — agents browsing the inbox
    don't need revenue / LTV / counters per row, and dropping them keeps
    the payload tight on large pages.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None = None
    phone: str
    assigned_agent_id: uuid.UUID | None = None
    ai_assigned: bool = False

    @field_serializer("phone")
    @classmethod
    def _format_phone(cls, phone: str) -> str:
        from app.core.phone import format_phone_for_display

        return format_phone_for_display(phone)


class ConversationLastMessage(BaseModel):
    """Last-message preview shown in the inbox row."""

    id: uuid.UUID
    direction: str
    content: str  # truncated server-side to 140 chars
    created_at: datetime


class ConversationTagSummary(BaseModel):
    """Slim tag projection for inbox row chips (id/name/color only)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str | None = None


class NeedsHumanCountResponse(BaseModel):
    awaiting_approval: int = 0
    human_assigned: int = 0
    total: int = 0


class ConversationListItem(BaseModel):
    """Inbox-shaped row: conversation state + contact summary + last-message preview.

    Built by `ConversationRepository.list_inbox()` via a LATERAL join so the
    whole page lands in a single round trip.
    """

    id: uuid.UUID
    state: str
    ai_enabled: bool
    locked_by: uuid.UUID | None = None
    lock_expires_at: datetime | None = None
    last_message_at: datetime | None = None
    unread: bool = False
    contact: ConversationContactSummary
    last_message: ConversationLastMessage | None = None
    tags: list[ConversationTagSummary] = []


# ============================================================ bulk actions

_BULK_IDS_MAX = 100


class BulkConversationPatch(BaseModel):
    """Mutation payload for POST /conversations/bulk-update.

    All fields optional; at least one must be set.
    """

    state: ConversationState | None = None
    add_tag_ids: list[uuid.UUID] | None = None
    remove_tag_ids: list[uuid.UUID] | None = None

    @field_validator("state", mode="before")
    @classmethod
    def _normalise_state(cls, v: object) -> object:
        return v.upper() if isinstance(v, str) else v

    def is_empty(self) -> bool:
        return self.model_dump(exclude_unset=True) == {}


class BulkConversationUpdateRequest(BaseModel):
    ids: list[uuid.UUID] = Field(..., min_length=1, max_length=_BULK_IDS_MAX)
    patch: BulkConversationPatch

    @field_validator("ids")
    @classmethod
    def _dedup_ids(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        seen: set[uuid.UUID] = set()
        out: list[uuid.UUID] = []
        for cid in v:
            if cid not in seen:
                seen.add(cid)
                out.append(cid)
        return out

    @field_validator("patch")
    @classmethod
    def _patch_not_empty(cls, v: BulkConversationPatch) -> BulkConversationPatch:
        if v.is_empty():
            raise ValueError("patch must contain at least one field")
        return v


# Reuse the bulk response shapes from contacts — same structure, same semantics.
from app.modules.contacts.schemas import BulkActionFailure, BulkActionResponse  # noqa: E402
