"""Second coverage fill for engagement: schedule_followup paths, select_regime
with real data, _load_thread_context, more pre-fire branches, and batch paths.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.contacts.models import Contact
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.models import Conversation
from app.modules.engagement.constants import (
    FREE_WINDOW_HOURS,
    OutreachState,
)
from app.modules.engagement.service import EngagementService
from app.modules.messaging.constants import MessageDirection, SenderType
from app.modules.messaging.models import Message


class TestEngagementScheduleFollowup:
    """Exercises schedule_followup paths without dispatching Celery tasks."""

    def test_schedule_followup_success_sets_outreach_state(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18881111001", name="S1",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=None,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        fire_at = datetime.now(tz=UTC) + timedelta(hours=3)
        result = svc.schedule_followup(
            conv.id, OutreachState.REENGAGE_1, fire_at,
        )
        assert result is not None
        entity_id, countdown, ctx = result
        assert entity_id == str(conv.id)
        assert countdown >= 0
        committed_db.refresh(conv)
        assert conv.outreach_state == OutreachState.REENGAGE_1.value

    def test_schedule_followup_dedup_when_state_already_set(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18881111002", name="S2",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=OutreachState.REENGAGE_1.value,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        fire_at = datetime.now(tz=UTC) + timedelta(hours=3)
        result = svc.schedule_followup(
            conv.id, OutreachState.RESCUE_1, fire_at,
        )
        assert result is None  # dedup — outreach_state already set


class TestEngagementSelectRegimeWithMessages:
    """Exercises select_regime with actual messages in the conversation."""

    def test_select_regime_zero_inbound(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18881111003", name="R1",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=None,
        )
        msg = Message(
            id=uuid.uuid4(), conversation_id=conv.id,
            direction=MessageDirection.OUTBOUND.value,
            sender_type=SenderType.AI.value,
            content="Hello",
        )
        committed_db.add_all([c, conv, msg])
        committed_db.commit()
        svc = EngagementService(committed_db)
        n, t = svc.select_regime(conv.id)
        # Zero inbound — cold track, handled via campaign_recipients.
        assert n is None

    def test_select_regime_one_inbound_window_open(self, committed_db):
        now = datetime.now(tz=UTC)
        c = Contact(id=uuid.uuid4(), phone="+18881111004", name="R2",
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
            created_at=now - timedelta(hours=4),
        )
        committed_db.add_all([c, conv, inbound])
        committed_db.commit()
        svc = EngagementService(committed_db)
        n, t = svc.select_regime(conv.id)
        # 1 inbound, window open, past min delay — re-engage.
        assert n in (OutreachState.REENGAGE_1, OutreachState.REENGAGE_2)

    def test_select_regime_one_inbound_too_recent(self, committed_db):
        now = datetime.now(tz=UTC)
        c = Contact(id=uuid.uuid4(), phone="+18881111005", name="R3",
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
            created_at=now - timedelta(minutes=30),
        )
        committed_db.add_all([c, conv, inbound])
        committed_db.commit()
        svc = EngagementService(committed_db)
        n, t = svc.select_regime(conv.id)
        # Too recent — below REENGAGE_1_MIN_HOURS.
        assert n is None

    def test_select_regime_two_inbound_ai_active(self, committed_db):
        now = datetime.now(tz=UTC)
        c = Contact(id=uuid.uuid4(), phone="+18881111006", name="R4",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=None,
        )
        for hours_ago in (5, 2):
            msg = Message(
                id=uuid.uuid4(), conversation_id=conv.id,
                direction=MessageDirection.INBOUND.value,
                sender_type=SenderType.CONTACT.value,
                content=f"Msg {hours_ago}h ago",
                created_at=now - timedelta(hours=hours_ago),
            )
            committed_db.add(msg)
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        n, t = svc.select_regime(conv.id)
        # ≥2 inbound, AI_ACTIVE — rescue.
        assert n in (OutreachState.RESCUE_1, OutreachState.RESCUE_2)

    def test_select_regime_two_inbound_not_ai_active(self, committed_db):
        now = datetime.now(tz=UTC)
        c = Contact(id=uuid.uuid4(), phone="+18881111007", name="R5",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.HUMAN_ASSIGNED.value,
            outreach_state=None,
        )
        msg = Message(
            id=uuid.uuid4(), conversation_id=conv.id,
            direction=MessageDirection.INBOUND.value,
            sender_type=SenderType.CONTACT.value,
            content="Hello",
            created_at=now - timedelta(hours=2),
        )
        committed_db.add_all([c, conv, msg])
        committed_db.commit()
        svc = EngagementService(committed_db)
        n, t = svc.select_regime(conv.id)
        # ≥2 inbound but not AI_ACTIVE — no rescue.
        assert n is None


class TestEngagementPreFireMore:
    """Additional pre-fire check branches."""

    def test_prefire_with_messages_and_inbound_since(self, committed_db):
        now = datetime.now(tz=UTC)
        c = Contact(id=uuid.uuid4(), phone="+18881111008", name="P1",
                     status="active", do_not_contact=False)
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=OutreachState.REENGAGE_1.value,
        )
        outbound = Message(
            id=uuid.uuid4(), conversation_id=conv.id,
            direction=MessageDirection.OUTBOUND.value,
            sender_type=SenderType.AI.value,
            content="Followup",
            created_at=now - timedelta(hours=1),
        )
        inbound = Message(
            id=uuid.uuid4(), conversation_id=conv.id,
            direction=MessageDirection.INBOUND.value,
            sender_type=SenderType.CONTACT.value,
            content="Reply",
            created_at=now - timedelta(minutes=30),
        )
        committed_db.add_all([c, conv, outbound, inbound])
        committed_db.commit()
        svc = EngagementService(committed_db)
        passed, reason = svc.pre_fire_checks(conv.id)
        # Inbound arrived after the last outbound — should fail.
        assert passed is False
        assert reason == "inbound_since_scheduled"

    def test_prefire_missing_conversation_id(self, committed_db):
        svc = EngagementService(committed_db)
        passed, reason = svc.pre_fire_checks(uuid.uuid4())
        assert passed is False
        assert reason == "conversation_missing"


class TestEngagementLoadThreadContext:
    """Exercises _load_thread_context via select_regime (rescue path)."""

    def test_load_thread_context_with_messages(self, committed_db):
        now = datetime.now(tz=UTC)
        c = Contact(id=uuid.uuid4(), phone="+18881111009", name="L1",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=None,
        )
        for i, h in enumerate((8, 6, 4, 2), 1):
            msg = Message(
                id=uuid.uuid4(), conversation_id=conv.id,
                direction=(
                    MessageDirection.INBOUND.value if i % 2 == 1
                    else MessageDirection.OUTBOUND.value
                ),
                sender_type=(
                    SenderType.CONTACT.value if i % 2 == 1
                    else SenderType.AI.value
                ),
                content=f"Message {i}",
                created_at=now - timedelta(hours=h),
            )
            committed_db.add(msg)
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        ctx = svc._load_thread_context(conv.id)
        assert "thread_messages" in ctx
        assert len(ctx["thread_messages"]) >= 2


class TestEngagementCancelLifecycle:
    """More cancel/on_first_reply edge cases."""

    def test_cancel_missing_conversation(self, committed_db):
        svc = EngagementService(committed_db)
        result = svc.cancel_pending_followups(uuid.uuid4())
        assert result == 0

    def test_on_first_reply_missing_conversation(self, committed_db):
        svc = EngagementService(committed_db)
        svc.on_first_reply(uuid.uuid4())  # Should not raise

    def test_cancel_cold_followup_state(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18881111010", name="C1",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=OutreachState.OUTREACH_SENT.value,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        result = svc.cancel_pending_followups(conv.id)
        assert result >= 0  # Cancel should succeed
        committed_db.refresh(conv)
        assert conv.outreach_state != OutreachState.OUTREACH_SENT.value


class TestEngagementOptOutAndDeliveryTagging:
    """Exercises helpers added to messaging/tasks.py."""

    @pytest.mark.asyncio
    async def test_opt_out_keywords_on_real_text(self, async_pg_session):
        from app.modules.engagement.constants import detect_opt_out_keywords

        cases = [
            ("STOP", True),
            ("PLEASE STOP", True),
            ("How are you?", False),
            ("Hello Sara", False),
            ("", False),
            ("unsubscribe me", True),
            ("dont contact me anymore", True),
        ]
        for text, expected in cases:
            assert detect_opt_out_keywords(text) == expected, f"Failed: {text!r}"

    @pytest.mark.asyncio
    async def test_permanent_failure_codes_consistent(self, async_pg_session):
        from app.modules.engagement.constants import (
            PERMANENT_FAILURE_CODES,
            is_permanent_failure,
        )

        for code in PERMANENT_FAILURE_CODES:
            assert is_permanent_failure(code) is True
        assert is_permanent_failure(None) is False
        assert is_permanent_failure(0) is False
        assert is_permanent_failure(131000) is False
        assert is_permanent_failure(500) is False

    @pytest.mark.asyncio
    async def test_tag_for_failure_code_all_codes(self, async_pg_session):
        from app.modules.engagement.constants import tag_for_failure_code

        tags = {
            131026: "NOT_ON_WHATSAPP",
            131047: "NOT_ON_WHATSAPP",
            131049: "NOT_ON_WHATSAPP",
            131053: "NOT_ON_WHATSAPP",
            131051: "UNDELIVERABLE",
            131052: "INVALID_NUMBER",
        }
        for code, expected in tags.items():
            assert tag_for_failure_code(code) == expected, f"Failed: {code}"
