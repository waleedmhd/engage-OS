"""Final margin: exercises the uncovered select_regime guard (line 119) and
the re-engage window-closed branch in pre_fire_checks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.contacts.models import Contact
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.models import Conversation
from app.modules.engagement.constants import OutreachState
from app.modules.engagement.service import EngagementService
from app.modules.messaging.constants import MessageDirection, SenderType
from app.modules.messaging.models import Message


class TestFinalMargin:
    def test_reengage_with_outbound_only_no_inbound(self, committed_db):
        """When a conversation has outbound messages but zero inbound, the
        last_inbound is None — exercises the guard at line 119."""
        now = datetime.now(tz=UTC)
        c = Contact(id=uuid.uuid4(), phone="+18889998000", name="OB1",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value, outreach_state=None,
        )
        # Insert only an outbound message — no inbound at all.
        outbound = Message(
            id=uuid.uuid4(), conversation_id=conv.id,
            direction=MessageDirection.OUTBOUND.value,
            sender_type=SenderType.AI.value, content="Hello",
            created_at=now - timedelta(hours=2),
        )
        committed_db.add_all([c, conv, outbound])
        committed_db.commit()

        svc = EngagementService(committed_db)
        n, t = svc.select_regime(conv.id)
        assert n is None  # zero inbound — cold track only

    def test_prefire_window_not_closed_with_recent_inbound(self, committed_db):
        """Exercise the window-open path (c) in pre_fire_checks — inbound is
        older than the outbound (no inbound_since), still within 24h window."""
        now = datetime.now(tz=UTC)
        c = Contact(id=uuid.uuid4(), phone="+18889998001", name="WC1",
                     status="active", do_not_contact=False)
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=OutreachState.REENGAGE_1.value,
        )
        # Outbound sent recently, inbound is older — no "inbound since" trigger.
        outbound = Message(
            id=uuid.uuid4(), conversation_id=conv.id,
            direction=MessageDirection.OUTBOUND.value,
            sender_type=SenderType.AI.value, content="F1",
            created_at=now - timedelta(hours=2),
        )
        inbound = Message(
            id=uuid.uuid4(), conversation_id=conv.id,
            direction=MessageDirection.INBOUND.value,
            sender_type=SenderType.CONTACT.value, content="Hello",
            created_at=now - timedelta(hours=4),  # older than outbound
        )
        committed_db.add_all([c, conv, outbound, inbound])
        committed_db.commit()

        from freezegun import freeze_time
        with freeze_time("2026-07-10 12:00:00", tz_offset=0):
            svc = EngagementService(committed_db)
            passed, reason = svc.pre_fire_checks(conv.id)
            # Window is open, active hours too — should NOT fail on window.
            assert reason != "window_closed"

    def test_prefire_window_closed_with_old_inbound(self, committed_db):
        """pre_fire_checks (c): inbound older than 24h → window_closed.

        Uses explicit datetime anchored at the same freeze point so there is
        no wall-clock/frozen-clock mismatch."""
        from freezegun import freeze_time

        # Anchor: freeze at 2026-07-10 12:00 UTC (= 16:00 GMT+4, active hours).
        # Messages created at 2026-07-09 10:00 UTC — 26h before frozen time.
        msg_ts = datetime(2026, 7, 9, 10, 0, 0, tzinfo=UTC)
        frozen = "2026-07-10 12:00:00"

        c = Contact(id=uuid.uuid4(), phone="+18889998002", name="WC2",
                     status="active", do_not_contact=False)
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=OutreachState.REENGAGE_1.value,
        )
        outbound = Message(
            id=uuid.uuid4(), conversation_id=conv.id,
            direction=MessageDirection.OUTBOUND.value,
            sender_type=SenderType.AI.value, content="F1",
            created_at=msg_ts,
        )
        inbound = Message(
            id=uuid.uuid4(), conversation_id=conv.id,
            direction=MessageDirection.INBOUND.value,
            sender_type=SenderType.CONTACT.value, content="Old",
            created_at=msg_ts,
        )
        committed_db.add_all([c, conv, outbound, inbound])
        committed_db.commit()

        with freeze_time(frozen, tz_offset=0):
            svc = EngagementService(committed_db)
            passed, reason = svc.pre_fire_checks(conv.id)
            assert passed is False
            assert reason == "window_closed"
