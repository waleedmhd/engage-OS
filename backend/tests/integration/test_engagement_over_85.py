"""One more test to definitively push coverage above 85% — hit the
_resolve_followup_stage branch where sent_count >= 2 returns None."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.audit.models import AuditLog
from app.modules.contacts.models import Contact
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.models import Conversation
from app.modules.engagement.constants import OutreachState
from app.modules.engagement.service import EngagementService
from app.modules.messaging.constants import MessageDirection, SenderType
from app.modules.messaging.models import Message


class TestExhaustedFollowups:
    def test_resolve_followup_stage_returns_none_after_two_sent(self, committed_db):
        """Insert 2 audit logs → sent_count == 2 → _resolve_followup_stage
        returns None → select_regime returns (None, None)."""
        now = datetime.now(tz=UTC)
        c = Contact(id=uuid.uuid4(), phone="+18889999001", name="XF1",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value, outreach_state=None,
        )
        inbound = Message(
            id=uuid.uuid4(), conversation_id=conv.id,
            direction=MessageDirection.INBOUND.value,
            sender_type=SenderType.CONTACT.value, content="Hello",
            created_at=now - timedelta(hours=5),
        )
        committed_db.add_all([c, conv, inbound])

        # Two prior follow-ups already sent — exhausted.
        for _ in (1, 2):
            committed_db.add(AuditLog(
                id=uuid.uuid4(),
                actor_type="system",
                action=f"engagement.followup_dispatched",
                entity_type="conversation",
                entity_id=conv.id,
                after_state={"outreach_state": OutreachState.REENGAGE_1.value},
            ))
        committed_db.commit()

        svc = EngagementService(committed_db)
        n, t = svc.select_regime(conv.id)
        assert n is None  # no more follow-ups — all exhausted
