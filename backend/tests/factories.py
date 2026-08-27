"""Test data factories.

Lightweight builders for the ORM models — factory-boy when available, plain
helpers otherwise. Every factory accepts a `session` and persists via flush
(commit is the caller's responsibility, matching architectural invariant #4).
"""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from app.modules.ai.models import AIEvent
from app.modules.auth.constants import UserRole
from app.modules.auth.models import RefreshToken, User
from app.modules.campaigns.constants import (
    CampaignRecipientStatus,
    CampaignStatus,
    CampaignType,
)
from app.modules.campaigns.models import Campaign, CampaignRecipient
from app.modules.contacts.constants import ContactStatus
from app.modules.contacts.models import Contact
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.models import Conversation
from app.modules.messaging.constants import (
    MessageDeliveryStatus,
    MessageDirection,
    SenderType,
)
from app.modules.messaging.models import Message
from app.modules.templates.constants import TemplateCategory, TemplateStatus
from app.modules.templates.models import Template


# ---------------------------------------------------------------- helpers
def _phone(n: int | None = None) -> str:
    n = n if n is not None else secrets.randbelow(10_000_000_000)
    return f"+1555{n:010d}"


def _email(prefix: str = "u") -> str:
    return f"{prefix}-{secrets.token_hex(4)}@test.local"


# ---------------------------------------------------------------- factories
def make_user(
    session,
    *,
    email: str | None = None,
    role: str = UserRole.AGENT.value,
    is_active: bool = True,
    hashed_password: str = "$2b$12$" + "a" * 53,  # bcrypt-shaped placeholder
    name: str = "Test User",
) -> User:
    u = User(
        id=uuid.uuid4(),
        email=email or _email(),
        name=name,
        hashed_password=hashed_password,
        role=role,
        is_active=is_active,
    )
    session.add(u)
    session.flush()
    return u


def make_contact(
    session,
    *,
    phone: str | None = None,
    name: str | None = "Contact Person",
    assigned_agent: User | None = None,
    status: str = ContactStatus.ACTIVE.value,
    marketing_opt_out: bool = False,
) -> Contact:
    c = Contact(
        id=uuid.uuid4(),
        phone=phone or _phone(),
        name=name,
        status=status,
        marketing_opt_out=marketing_opt_out,
        assigned_agent_id=assigned_agent.id if assigned_agent else None,
    )
    session.add(c)
    session.flush()
    return c


def make_conversation(
    session,
    *,
    contact: Contact,
    state: str = ConversationState.NEW.value,
    ai_enabled: bool = True,
    locked_by: User | None = None,
    lock_expires_in_seconds: int | None = None,
) -> Conversation:
    lock_expires_at = None
    if lock_expires_in_seconds is not None:
        lock_expires_at = datetime.now(UTC) + timedelta(seconds=lock_expires_in_seconds)
    conv = Conversation(
        id=uuid.uuid4(),
        contact_id=contact.id,
        state=state,
        ai_enabled=ai_enabled,
        locked_by=locked_by.id if locked_by else None,
        lock_expires_at=lock_expires_at,
    )
    session.add(conv)
    session.flush()
    return conv


def make_message(
    session,
    *,
    conversation: Conversation,
    direction: str = MessageDirection.INBOUND.value,
    sender_type: str = SenderType.CONTACT.value,
    content: str = "hello",
    meta_message_id: str | None = None,
    delivery_status: str = MessageDeliveryStatus.PENDING.value,
) -> Message:
    m = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        direction=direction,
        sender_type=sender_type,
        content=content,
        meta_message_id=meta_message_id or f"wamid.{secrets.token_hex(8)}",
        delivery_status=delivery_status,
    )
    session.add(m)
    session.flush()
    return m


def make_refresh_token(
    session,
    *,
    user: User,
    token_hash: str | None = None,
    expires_in_days: int = 7,
    revoked: bool = False,
) -> RefreshToken:
    rt = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=token_hash or secrets.token_hex(32),
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
        revoked=revoked,
    )
    session.add(rt)
    session.flush()
    return rt


def make_template(
    session,
    *,
    name: str | None = None,
    status: str = TemplateStatus.APPROVED.value,
    category: str = TemplateCategory.MARKETING.value,
    language: str = "en",
    meta_template_id: str | None = "meta_test_template",
) -> Template:
    t = Template(
        id=uuid.uuid4(),
        name=name or f"tmpl_{secrets.token_hex(4)}",
        status=status,
        category=category,
        language=language,
        meta_template_id=meta_template_id,
    )
    session.add(t)
    session.flush()
    return t


def make_campaign(
    session,
    *,
    template: Template,
    name: str = "Test Campaign",
    status: str = CampaignStatus.DRAFT.value,
    type: str = CampaignType.IMMEDIATE.value,
    audience_filter: dict | None = None,
    rate_limit_per_second: int | None = None,
    cron_expression: str | None = None,
    next_run_at: datetime | None = None,
    scheduled_at: datetime | None = None,
    created_by: User | None = None,
) -> Campaign:
    c = Campaign(
        id=uuid.uuid4(),
        template_id=template.id,
        name=name,
        status=status,
        type=type,
        audience_filter=audience_filter if audience_filter is not None else {},
        validation_errors=[],
        rate_limit_per_second=rate_limit_per_second,
        cron_expression=cron_expression,
        next_run_at=next_run_at,
        scheduled_at=scheduled_at,
        created_by=created_by.id if created_by else None,
    )
    session.add(c)
    session.flush()
    return c


def make_campaign_recipient(
    session,
    *,
    campaign: Campaign,
    contact: Contact,
    status: str = CampaignRecipientStatus.PENDING.value,
    message_id: uuid.UUID | None = None,
    meta_message_id: str | None = None,
    error_message: str | None = None,
) -> CampaignRecipient:
    r = CampaignRecipient(
        id=uuid.uuid4(),
        campaign_id=campaign.id,
        contact_id=contact.id,
        status=status,
        message_id=message_id,
        meta_message_id=meta_message_id,
        error_message=error_message,
    )
    session.add(r)
    session.flush()
    return r


def make_ai_event(
    session,
    *,
    conversation: Conversation,
    request: dict | None = None,
    response: dict | None = None,
    intent: str | None = None,
    confidence: float | None = None,
    latency_ms: int | None = None,
    cost_estimate: float | None = None,
    error: str | None = None,
) -> AIEvent:
    e = AIEvent(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        request=request if request is not None else {},
        response=response if response is not None else {},
        intent=intent,
        confidence=confidence,
        latency_ms=latency_ms,
        cost_estimate=cost_estimate,
        error=error,
    )
    session.add(e)
    session.flush()
    return e


__all__ = [
    "make_ai_event",
    "make_campaign",
    "make_campaign_recipient",
    "make_contact",
    "make_conversation",
    "make_message",
    "make_refresh_token",
    "make_template",
    "make_user",
]
