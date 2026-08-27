"""Wire-format and normalized event schemas for Meta WhatsApp Cloud API.

The webhook router and Celery tasks operate exclusively on the *normalized*
shapes here — never the raw envelope — so business code is decoupled from
Meta's payload structure.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NormalizedContactCard(BaseModel):
    """A contact card embedded in an inbound contacts message."""
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    phones: list[str] = Field(default_factory=list)


class NormalizedInboundMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    meta_message_id: str
    from_phone: str
    to_phone_number_id: str
    timestamp: datetime
    message_type: str
    text: str | None = None
    media_id: str | None = None
    media_mime_type: str | None = None
    caption: str | None = None
    contact_name: str | None = None
    context_message_id: str | None = None
    contact_card: NormalizedContactCard | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class NormalizedStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    meta_message_id: str
    status: str
    timestamp: datetime
    recipient_phone: str | None = None
    error_code: int | None = None
    error_message: str | None = None
    pricing_category: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class NormalizedWebhook(BaseModel):
    model_config = ConfigDict(extra="ignore")

    inbound_messages: list[NormalizedInboundMessage] = Field(default_factory=list)
    status_updates: list[NormalizedStatusUpdate] = Field(default_factory=list)


class MetaSendResponse(BaseModel):
    """Subset of the Meta send-message response we care about."""

    model_config = ConfigDict(extra="ignore")

    messaging_product: str | None = None
    contacts: list[dict[str, Any]] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
