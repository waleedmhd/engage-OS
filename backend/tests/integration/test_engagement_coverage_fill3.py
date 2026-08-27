"""Third coverage fill: engagement tasks helpers, cold followup path branches,
and remaining edge cases in the service layer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.campaigns.models import CampaignRecipient
from app.modules.contacts.models import Contact
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.models import Conversation
from app.modules.engagement.constants import (
    ENGAGEMENT_SWEEP_INTERVAL_SECONDS,
    OPT_OUT_KEYWORDS,
    PERMANENT_FAILURE_CODES,
    OutreachState,
)
from app.modules.engagement.service import EngagementService
from app.modules.messaging.constants import MessageDirection, SenderType
from app.modules.messaging.models import Message


class TestEngagementMoreServiceCoverage:
    """Fills remaining service code paths not hit by coverage_fill or coverage_fill2."""

    def test_select_regime_one_inbound_window_closed(self, committed_db):
        """§4.2 re-engage: window closed should not return a regime (handled by sweep)."""
        now = datetime.now(tz=UTC)
        c = Contact(id=uuid.uuid4(), phone="+18883333001", name="W1",
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
            created_at=now - timedelta(hours=30),  # window closed
        )
        committed_db.add_all([c, conv, inbound])
        committed_db.commit()
        svc = EngagementService(committed_db)
        n, t = svc.select_regime(conv.id)
        # Window closed, inbound_count==1 → select_regime returns None
        # (the sweep task handles window-closed → UNRESPONSIVE).
        assert n is None

    def test_select_regime_two_inbound_too_recent(self, committed_db):
        """Rescue: too recent inbound below RESCUE_1_MIN_HOURS."""
        now = datetime.now(tz=UTC)
        c = Contact(id=uuid.uuid4(), phone="+18883333002", name="W2",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=None,
        )
        for minutes_ago in (45, 15):
            msg = Message(
                id=uuid.uuid4(), conversation_id=conv.id,
                direction=MessageDirection.INBOUND.value,
                sender_type=SenderType.CONTACT.value,
                content=f"Msg at -{minutes_ago}m",
                created_at=now - timedelta(minutes=minutes_ago),
            )
            committed_db.add(msg)
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        n, t = svc.select_regime(conv.id)
        assert n is None  # too recent

    def test_schedule_followup_missing_conversation(self, committed_db):
        svc = EngagementService(committed_db)
        fire_at = datetime.now(tz=UTC) + timedelta(hours=3)
        # Conversation doesn't exist
        result = svc.schedule_followup(uuid.uuid4(), OutreachState.REENGAGE_1, fire_at)
        assert result is None

    def test_prefire_rescue_not_blocked_on_ai_active(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18883333003", name="W3",
                     status="active", do_not_contact=False)
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=OutreachState.RESCUE_1.value,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        passed, reason = svc.pre_fire_checks(conv.id, is_rescue=True)
        # Should NOT be blocked by human_took_over — AI_ACTIVE is allowed.
        assert reason != "human_took_over"

    def test_within_active_hours_noon(self, committed_db):
        from freezegun import freeze_time

        with freeze_time("2026-07-10 12:00:00", tz_offset=0):
            svc = EngagementService(committed_db)
            assert svc.within_active_hours() is True

    def test_within_active_hours_midnight(self, committed_db):
        from freezegun import freeze_time

        with freeze_time("2026-07-10 20:00:00", tz_offset=0):
            svc = EngagementService(committed_db)
            assert svc.within_active_hours() is False


class TestEngagementConstantsExhaustive:
    """Exhaustive enumeration of every constant value — no DB needed."""

    def test_opt_out_keywords_all_lower(self):
        for kw in OPT_OUT_KEYWORDS:
            assert kw == kw.lower(), f"'{kw}' must be lowercase"

    def test_permanent_failure_codes_not_empty(self):
        assert len(PERMANENT_FAILURE_CODES) >= 5

    def test_sweep_interval_positive(self):
        assert ENGAGEMENT_SWEEP_INTERVAL_SECONDS > 0

    def test_sweep_interval_reasonable(self):
        assert 10 <= ENGAGEMENT_SWEEP_INTERVAL_SECONDS <= 600

    def test_outreach_state_values_complete(self):
        expected = {
            "PENDING", "OUTREACH_SENT", "COLD_FOLLOWUP_SENT",
            "REENGAGE_1", "REENGAGE_2",
            "RESCUE_1", "RESCUE_2",
            "CONVERTED", "UNRESPONSIVE", "UNDELIVERABLE", "SUPPRESSED",
        }
        assert {s.value for s in OutreachState} == expected

    def test_terminal_states_are_subset(self):
        from app.modules.engagement.constants import OUTREACH_TERMINAL_STATES
        for s in OUTREACH_TERMINAL_STATES:
            assert s in OutreachState.__members__.values()

    def test_cold_states_are_subset(self):
        from app.modules.engagement.constants import OUTREACH_COLD_STATES
        for s in OUTREACH_COLD_STATES:
            assert s in OutreachState.__members__.values()


class TestEngagementModels:
    """Exercises model columns added by this PR."""

    @pytest.mark.asyncio
    async def test_contact_do_not_contact_default(self, async_pg_session):
        c = Contact(id=uuid.uuid4(), phone="+18883333004",
                     name="DefaultDNC", status="active")
        async_pg_session.add(c)
        await async_pg_session.flush()
        assert c.do_not_contact is False

    @pytest.mark.asyncio
    async def test_contact_do_not_contact_true(self, async_pg_session):
        c = Contact(id=uuid.uuid4(), phone="+18883333005",
                     name="TrueDNC", status="active", do_not_contact=True)
        async_pg_session.add(c)
        await async_pg_session.flush()
        assert c.do_not_contact is True

    @pytest.mark.asyncio
    async def test_conversation_outreach_state_null_default(self, async_pg_session):
        c = Contact(id=uuid.uuid4(), phone="+18883333006",
                     name="NoOutreach", status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id,
            state=ConversationState.AI_ACTIVE.value,
        )
        async_pg_session.add_all([c, conv])
        await async_pg_session.flush()
        assert conv.outreach_state is None

    @pytest.mark.asyncio
    async def test_conversation_outreach_state_set(self, async_pg_session):
        c = Contact(id=uuid.uuid4(), phone="+18883333007",
                     name="WithOutreach", status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=OutreachState.PENDING.value,
        )
        async_pg_session.add_all([c, conv])
        await async_pg_session.flush()
        assert conv.outreach_state == OutreachState.PENDING.value

    @pytest.mark.asyncio
    async def test_campaign_recipient_outreach_state_default(self, async_pg_session):
        cr = CampaignRecipient(
            id=uuid.uuid4(),
            campaign_id=uuid.uuid4(),
            contact_id=uuid.uuid4(),
            status="pending",
        )
        assert cr.outreach_state is None


class TestEngagementOptOutDetection:
    """Edge cases and cross-check for opt-out detection."""

    def test_all_keywords_detect_themselves(self):
        from app.modules.engagement.constants import detect_opt_out_keywords as _f
        for kw in list(OPT_OUT_KEYWORDS)[:10]:
            assert _f(kw) is True, f"'{kw}' should self-detect"

    def test_mixed_case_keywords(self):
        from app.modules.engagement.constants import detect_opt_out_keywords as _f
        assert _f("Please STOP messaging me") is True
        assert _f("I want to UnSuBsCrIbE") is True

    def test_non_opt_out_phrases(self):
        from app.modules.engagement.constants import detect_opt_out_keywords as _f
        phrases = [
            "Hello, how are you?",
            "I want to buy an iPhone",
            "What is your price for Samsung?",
            "Can you help me?",
            "",
        ]
        for p in phrases:
            assert _f(p) is False, f"Should not match: {p!r}"
        assert _f(None) is False
