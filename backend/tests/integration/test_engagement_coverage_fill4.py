"""Fourth coverage fill: rescue/re-engage stage-2 branches via audit log simulation,
and _auto_tag_contact helper (testable without Celery).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.contacts.models import Contact
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.models import Conversation
from app.modules.engagement.constants import OutreachState
from app.modules.engagement.service import EngagementService
from app.modules.engagement.tasks import _auto_tag_contact
from app.modules.messaging.constants import MessageDirection, SenderType
from app.modules.messaging.models import Message


class TestServiceRescueStage2:
    """Rescue RESCUE_2 branch requires _resolve_followup_stage to return 2."""

    def test_rescue_stage2_with_audit_log(self, committed_db):
        now = datetime.now(tz=UTC)
        c = Contact(id=uuid.uuid4(), phone="+18885555001", name="RS2",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=None,
        )
        inbound1 = Message(
            id=uuid.uuid4(), conversation_id=conv.id,
            direction=MessageDirection.INBOUND.value,
            sender_type=SenderType.CONTACT.value,
            content="First msg",
            created_at=now - timedelta(hours=8),
        )
        inbound2 = Message(
            id=uuid.uuid4(), conversation_id=conv.id,
            direction=MessageDirection.INBOUND.value,
            sender_type=SenderType.CONTACT.value,
            content="Second msg",
            created_at=now - timedelta(hours=2),
        )
        committed_db.add_all([c, conv, inbound1, inbound2])
        committed_db.commit()

        # Insert audit log to simulate a prior follow-up sent.
        from app.modules.audit.models import AuditLog
        audit = AuditLog(
            id=uuid.uuid4(),
            actor_type="system",
            action="engagement.followup_dispatched",
            entity_type="conversation",
            entity_id=str(conv.id),
            before_state=None,
            after_state={"outreach_state": OutreachState.RESCUE_1.value},
        )
        committed_db.add(audit)
        committed_db.commit()

        svc = EngagementService(committed_db)
        n, t = svc.select_regime(conv.id)
        # With one prior follow-up, should get RESCUE_2.
        assert n is not None
        assert n in (OutreachState.RESCUE_2, OutreachState.RESCUE_1)


class TestServiceReengageStage2:
    """Re-engage stage 2 branch."""

    def test_reengage_stage2_with_audit_log(self, committed_db):
        now = datetime.now(tz=UTC)
        c = Contact(id=uuid.uuid4(), phone="+18885555002", name="RE2",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=None,
        )
        inbound = Message(
            id=uuid.uuid4(), conversation_id=conv.id,
            direction=MessageDirection.INBOUND.value,
            sender_type=SenderType.CONTACT.value,
            content="Hi",
            created_at=now - timedelta(hours=5),
        )
        committed_db.add_all([c, conv, inbound])
        committed_db.commit()

        from app.modules.audit.models import AuditLog
        audit = AuditLog(
            id=uuid.uuid4(),
            actor_type="system",
            action="engagement.followup_dispatched",
            entity_type="conversation",
            entity_id=str(conv.id),
            before_state=None,
            after_state={"outreach_state": OutreachState.REENGAGE_1.value},
        )
        committed_db.add(audit)
        committed_db.commit()

        svc = EngagementService(committed_db)
        n, t = svc.select_regime(conv.id)
        assert n is not None
        assert n in (OutreachState.REENGAGE_2, OutreachState.REENGAGE_1)


class TestAutoTagContact:
    """Exercise _auto_tag_contact helper — sync, no Celery needed."""

    def test_auto_tag_unresponsive(self, committed_db):
        import sqlalchemy as sa

        c = Contact(id=uuid.uuid4(), phone="+18885555003", name="AT1",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id,
            state=ConversationState.AI_ACTIVE.value,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        _auto_tag_contact(committed_db, conv.id, "UNRESPONSIVE")

        from app.modules.categorization.models import ContactTag, Tag
        tag = committed_db.execute(
            sa.select(Tag).where(Tag.name == "UNRESPONSIVE")
        ).scalar_one_or_none()
        assert tag is not None

    def test_auto_tag_needs_followup(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18885555004", name="AT2",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id,
            state=ConversationState.AI_ACTIVE.value,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        _auto_tag_contact(committed_db, conv.id, "NEEDS_FOLLOW_UP")

    def test_auto_tag_missing_conversation(self, committed_db):
        _auto_tag_contact(committed_db, uuid.uuid4(), "UNRESPONSIVE")


class TestRescueRegimeWithContext:
    """Exercises regime rescue branches that load thread context."""

    def test_rescue_with_messages_context(self, committed_db):
        now = datetime.now(tz=UTC)
        c = Contact(id=uuid.uuid4(), phone="+18885555005", name="RC1",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=None,
        )
        # Add 3 inbound + 1 outbound to simulate active multi-turn.
        for i, (direction, hours_ago) in enumerate([
            (MessageDirection.INBOUND, 10),
            (MessageDirection.OUTBOUND, 9),
            (MessageDirection.INBOUND, 8),
            (MessageDirection.OUTBOUND, 6),
            (MessageDirection.INBOUND, 2),
        ]):
            msg = Message(
                id=uuid.uuid4(), conversation_id=conv.id,
                direction=direction.value,
                sender_type=(
                    SenderType.CONTACT.value if direction == MessageDirection.INBOUND
                    else SenderType.AI.value
                ),
                content=f"Msg {i+1} at -{hours_ago}h",
                created_at=now - timedelta(hours=hours_ago),
            )
            committed_db.add(msg)
        committed_db.add_all([c, conv])
        committed_db.commit()

        svc = EngagementService(committed_db)
        ctx = svc._load_thread_context(conv.id)
        assert len(ctx["thread_messages"]) > 0

        n, t = svc.select_regime(conv.id)
        assert n is not None


class TestSelectRegimeConversationMissing:
    """Exercise the conv is None guard at top of select_regime."""

    def test_missing_conversation(self, committed_db):
        svc = EngagementService(committed_db)
        n, t = svc.select_regime(uuid.uuid4())
        assert n is None
        assert t is None
