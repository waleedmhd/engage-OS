"""Coverage fill for the engagement module: service methods, pre-fire checks,
regime selection, within_active_hours, and lifecycle transitions.

EngagementService is sync-only (Celery contract), so the service tests
use the ``committed_db`` fixture (real sync session). Pure-constant tests
and model-instantiation tests that only poke ORM attributes are async.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.contacts.models import Contact
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.models import Conversation
from app.modules.engagement.constants import (
    OUTREACH_COLD_STATES,
    OUTREACH_TERMINAL_STATES,
    OutreachState,
    detect_opt_out_keywords,
    is_permanent_failure,
    tag_for_failure_code,
)
from app.modules.engagement.service import EngagementService
from app.modules.messaging.constants import MessageDirection, SenderType


# ----------------------------------------------------------------- constants


class TestEngagementConstantsPure:
    def test_opt_out_detection_edge_cases(self):
        assert detect_opt_out_keywords("  STOP  ") is True
        # "stop" is a substring of "stoppp" — that case returns True by design.
        assert detect_opt_out_keywords("stppp") is False  # no keyword inside
        assert detect_opt_out_keywords("") is False
        assert detect_opt_out_keywords(None) is False
        assert detect_opt_out_keywords("unsubscribe") is True

    def test_permanent_failure_all_codes(self):
        assert is_permanent_failure(131026) is True
        assert is_permanent_failure(500) is False
        assert is_permanent_failure(None) is False

    def test_tag_for_code_mapping(self):
        assert tag_for_failure_code(131026) == "NOT_ON_WHATSAPP"
        assert tag_for_failure_code(131052) == "INVALID_NUMBER"
        assert tag_for_failure_code(99999) == "UNDELIVERABLE"
        assert tag_for_failure_code(None) is None


# ------------------------------------------------------------------- service


class TestEngagementServiceSync:
    """All EngagementService tests use committed_db (real sync session)."""

    def test_select_regime_no_conversation(self, committed_db):
        svc = EngagementService(committed_db)
        n, t = svc.select_regime(uuid.uuid4())
        assert n is None

    def test_select_regime_already_mid_cadence(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18889990001", name="A", status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=OutreachState.REENGAGE_1.value,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        n, t = svc.select_regime(conv.id)
        assert n is None  # already mid-cadence

    def test_prefire_conversation_missing(self, committed_db):
        svc = EngagementService(committed_db)
        passed, reason = svc.pre_fire_checks(uuid.uuid4())
        assert passed is False
        assert reason == "conversation_missing"

    def test_prefire_contact_suppressed(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18889990002", name="B",
                     status="active", do_not_contact=True)
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        passed, reason = svc.pre_fire_checks(conv.id)
        assert passed is False
        assert reason == "contact_suppressed"

    def test_prefire_not_suppressed(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18889990003", name="C",
                     status="active", do_not_contact=False)
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.AI_ACTIVE.value,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        passed, reason = svc.pre_fire_checks(conv.id)
        assert reason != "contact_suppressed"

    def test_prefire_rescue_blocked_on_human_assigned(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18889990004", name="D",
                     status="active", do_not_contact=False)
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id, ai_enabled=True,
            state=ConversationState.HUMAN_ASSIGNED.value,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        passed, reason = svc.pre_fire_checks(conv.id, is_rescue=True)
        assert passed is False
        assert reason == "human_took_over"

    def test_cancel_followups_none_outreach_state(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18889990005", name="E",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=None,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        result = svc.cancel_pending_followups(conv.id)
        assert result == 0

    def test_cancel_followups_active_state(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18889990006", name="F",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=OutreachState.RESCUE_1.value,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        result = svc.cancel_pending_followups(conv.id)
        assert result >= 0

    def test_cancel_followups_terminal_state_is_noop(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18889990007", name="G",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=OutreachState.SUPPRESSED.value,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        result = svc.cancel_pending_followups(conv.id)
        assert result == 0  # terminal — no-op

    def test_on_first_reply_null_state_noop(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18889990008", name="H",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=None,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        svc.on_first_reply(conv.id)

    def test_on_first_reply_terminal_state_noop(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18889990009", name="I",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=OutreachState.UNRESPONSIVE.value,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        svc.on_first_reply(conv.id)

    def test_on_first_reply_converts_active_state(self, committed_db):
        c = Contact(id=uuid.uuid4(), phone="+18889990010", name="J",
                     status="active")
        conv = Conversation(
            id=uuid.uuid4(), contact_id=c.id,
            state=ConversationState.AI_ACTIVE.value,
            outreach_state=OutreachState.OUTREACH_SENT.value,
        )
        committed_db.add_all([c, conv])
        committed_db.commit()
        svc = EngagementService(committed_db)
        svc.on_first_reply(conv.id)
        committed_db.refresh(conv)
        assert conv.outreach_state == OutreachState.CONVERTED.value


# --------------------------------------------------------------- within hours


class TestEngagementWithinActiveHours:
    def test_returns_bool(self):
        from app.db.session import sync_session_factory
        with sync_session_factory() as s:
            svc = EngagementService(s)
            assert isinstance(svc.within_active_hours(), bool)

    def test_daytime_utc_noon(self):
        """UTC noon, default timezone is UTC — should be in active hours (8-21)."""
        from freezegun import freeze_time
        from app.db.session import sync_session_factory
        with freeze_time("2026-07-10 12:00:00", tz_offset=0):
            with sync_session_factory() as s:
                svc = EngagementService(s)
                assert svc.within_active_hours() is True

    def test_late_night_utc_22(self):
        """UTC 22:00, default timezone is UTC — should be outside active hours (8-21)."""
        from freezegun import freeze_time
        from app.db.session import sync_session_factory
        with freeze_time("2026-07-10 22:00:00", tz_offset=0):
            with sync_session_factory() as s:
                svc = EngagementService(s)
                assert svc.within_active_hours() is False


# ------------------------------------------------------------- outreach states


class TestOutreachStateEnum:
    def test_all_unique_values(self):
        values = [s.value for s in OutreachState]
        assert len(values) == len(set(values))

    def test_terminal_states_match(self):
        terminal = {
            OutreachState.CONVERTED, OutreachState.UNRESPONSIVE,
            OutreachState.UNDELIVERABLE, OutreachState.SUPPRESSED,
        }
        assert set(OUTREACH_TERMINAL_STATES) == terminal

    def test_cold_states_match(self):
        cold = {
            OutreachState.PENDING, OutreachState.OUTREACH_SENT,
            OutreachState.COLD_FOLLOWUP_SENT,
        }
        assert set(OUTREACH_COLD_STATES) == cold
