"""Engagement service: regime selection, pre-fire checks, follow-up scheduling,
and lifecycle management (agent-engagement-policy §2-§8).

Sync-only - called from Celery tasks via ``sync_session_factory``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.orm import Session as SyncSession

from app.modules.conversations.constants import ConversationState
from app.modules.conversations.models import Conversation
from app.modules.engagement.constants import (
    DEFAULT_ACTIVE_HOURS_END,
    DEFAULT_ACTIVE_HOURS_START,
    FREE_WINDOW_HOURS,
    OUTREACH_REENGAGE_STATES,
    OUTREACH_RESCUE_STATES,
    OUTREACH_TERMINAL_STATES,
    REENGAGE_1_MAX_HOURS,
    REENGAGE_1_MIN_HOURS,
    REENGAGE_2_TARGET_HOURS,
    RESCUE_1_MAX_HOURS,
    RESCUE_1_MIN_HOURS,
    RESCUE_2_MAX_HOURS,
    RESCUE_2_MIN_HOURS,
    OutreachState,
)
from app.modules.settings.constants import SETTING_OPS_TIMEZONE

logger = structlog.get_logger(__name__)

# Conversation states where AI is NOT in charge - rescue follow-ups must be
# cancelled if the thread is in any of these at fire time (§4.3, §7, §8.g).
_RESCUE_BLOCKED_STATES: frozenset[str] = frozenset({
    ConversationState.HUMAN_ASSIGNED.value,
    ConversationState.AWAITING_APPROVAL.value,
    ConversationState.AI_PAUSED.value,
    ConversationState.CLOSED.value,
})


class EngagementService:
    """Sync service for outreach lifecycle management.

    Called from Celery tasks. All methods receive the caller's session.
    """

    def __init__(self, session: SyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ regime

    def select_regime(
        self,
        conversation_id: uuid.UUID,
    ) -> tuple[OutreachState | None, dict | None]:
        """Return the follow-up regime and timing for a conversation.

        Returns (next_state, timing) or (None, None) when no follow-up is due.
        Timing dict carries ``fire_at`` (datetime) and ``context`` (dict for
        the follow-up task - thread state for rescue).

        Regime discriminators (§4):
          - 0 inbound + window closed → §4.1 Cold (template)
          - 1 inbound + window open → §4.2 Re-engage (free)
          - ≥2 inbound + window open + AI_ACTIVE → §4.3 Rescue (free)
        """
        import sqlalchemy as sa

        from app.modules.messaging.constants import MessageDirection
        from app.modules.messaging.models import Message

        conv = self._session.get(Conversation, conversation_id)
        if conv is None:
            return None, None

        # Guard: already mid-cadence or terminal.
        if conv.outreach_state is not None:
            return None, None

        # Count inbound messages for regime selection.
        inbound_count = self._session.execute(
            sa.select(sa.func.count(Message.id)).where(
                Message.conversation_id == conversation_id,
                Message.direction == MessageDirection.INBOUND.value,
            )
        ).scalar_one()

        # Find last inbound timestamp.
        last_inbound = self._session.execute(
            sa.select(Message.created_at)
            .where(
                Message.conversation_id == conversation_id,
                Message.direction == MessageDirection.INBOUND.value,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        now = datetime.now(tz=UTC)
        window_open = (
            last_inbound is not None
            and (now - last_inbound).total_seconds() < FREE_WINDOW_HOURS * 3600
        )

        if inbound_count == 0:
            # §4.1 Cold: handled via campaign_recipients, not here.
            return None, None

        if inbound_count == 1 and window_open:
            # §4.2 Re-engage: exactly 1 inbound, window still open.
            # Check if we're past the minimum re-engage delay.
            if last_inbound is None:
                return None, None
            since_inbound_h = (now - last_inbound).total_seconds() / 3600
            if since_inbound_h < REENGAGE_1_MIN_HOURS:
                return None, None

            # Determine which follow-up stage.
            followup_stage = self._resolve_followup_stage(
                conversation_id
            )
            if followup_stage is None:
                return None, None

            if followup_stage == 1:
                # REENGAGE_1: fire 3-6h after last inbound.
                delay_h = REENGAGE_1_MIN_HOURS + (
                    (REENGAGE_1_MAX_HOURS - REENGAGE_1_MIN_HOURS) / 2
                )
                fire_at = last_inbound + timedelta(hours=delay_h)
                return OutreachState.REENGAGE_1, {
                    "fire_at": fire_at,
                    "context": {"inbound_count": 1},
                }
            else:
                # REENGAGE_2: fire as late in window as possible (~23h).
                fire_at = last_inbound + timedelta(hours=REENGAGE_2_TARGET_HOURS)
                window_closes = last_inbound + timedelta(hours=FREE_WINDOW_HOURS)
                if fire_at > window_closes:
                    fire_at = window_closes - timedelta(minutes=30)
                return OutreachState.REENGAGE_2, {
                    "fire_at": fire_at,
                    "context": {"inbound_count": 1},
                }

        if inbound_count >= 2 and window_open:
            # §4.3 Rescue: ≥2 inbound, window open, AI_ACTIVE required.
            if conv.state != ConversationState.AI_ACTIVE.value:
                return None, None
            if last_inbound is None:
                return None, None
            since_inbound_h = (now - last_inbound).total_seconds() / 3600
            if since_inbound_h < RESCUE_1_MIN_HOURS:
                return None, None

            followup_stage = self._resolve_followup_stage(
                conversation_id
            )
            if followup_stage is None:
                return None, None

            # Load last thread context for the rescue message.
            thread_context = self._load_thread_context(conversation_id)

            if followup_stage == 1:
                delay_h = RESCUE_1_MIN_HOURS + (
                    (RESCUE_1_MAX_HOURS - RESCUE_1_MIN_HOURS) / 2
                )
                fire_at = last_inbound + timedelta(hours=delay_h)
                return OutreachState.RESCUE_1, {
                    "fire_at": fire_at,
                    "context": thread_context,
                }
            else:
                delay_h = RESCUE_2_MIN_HOURS + (
                    (RESCUE_2_MAX_HOURS - RESCUE_2_MIN_HOURS) / 2
                )
                fire_at = last_inbound + timedelta(hours=delay_h)
                return OutreachState.RESCUE_2, {
                    "fire_at": fire_at,
                    "context": thread_context,
                }

        return None, None

    def _resolve_followup_stage(
        self,
        conversation_id: uuid.UUID,
    ) -> int | None:
        """Determine whether this is follow-up 1 or 2 based on audit history.

        Returns 1 for the first follow-up, 2 for the second, None if both
        have already been sent.
        """
        import sqlalchemy as sa

        from app.modules.audit.models import AuditLog

        # Count how many follow-ups have been sent for this conversation
        # by checking audit logs for outreach_state transitions.
        sent_count = self._session.execute(
            sa.select(sa.func.count(AuditLog.id)).where(
                AuditLog.entity_type == "conversation",
                AuditLog.entity_id == str(conversation_id),
                AuditLog.action.like("engagement.followup_%"),
            )
        ).scalar_one()

        if sent_count >= 2:
            return None

        return sent_count + 1  # 1 or 2

    # ------------------------------------------------------------- pre-fire

    def pre_fire_checks(
        self,
        conversation_id: uuid.UUID,
        *,
        is_rescue: bool = False,
    ) -> tuple[bool, str | None]:
        """Run all pre-fire checks before dispatching a scheduled follow-up (§8).

        Returns (passed, reason). Checks in order:
          (a) no inbound since scheduling
          (b) not suppressed/opted-out
          (c) for rescue: thread still AI_ACTIVE (§4.3 hard rule — checked
              before clock-based gates because a human takeover means cancel
              immediately regardless of window or active hours)
          (d) within window (for §4.2-4.3)
          (e) active hours
        """
        import sqlalchemy as sa

        from app.modules.contacts.models import Contact
        from app.modules.messaging.constants import MessageDirection
        from app.modules.messaging.models import Message

        conv = self._session.get(Conversation, conversation_id)
        if conv is None:
            return False, "conversation_missing"

        # (b) Contact not suppressed.
        contact = self._session.get(Contact, conv.contact_id)
        if contact is not None and contact.do_not_contact:
            return False, "contact_suppressed"

        # (c) Rescue: conversation must still be AI_ACTIVE (§4.3, §8.g).
        # This is a hard rule checked before clock-based gates — a human
        # takeover means cancel immediately regardless of window/active hours.
        if is_rescue and conv.state in _RESCUE_BLOCKED_STATES:
            return False, "human_took_over"

        # (a) No inbound since the follow-up was scheduled.
        # The outreach_state was set when the follow-up was scheduled;
        # check that no inbound message arrived after that point.
        if conv.outreach_state is not None:
            # The state being non-null means a follow-up was scheduled.
            # Check for inbound messages after the conversation's last outbound.
            last_outbound = self._session.execute(
                sa.select(Message.created_at)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.direction == MessageDirection.OUTBOUND.value,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            if last_outbound is not None:
                newer_inbound = self._session.execute(
                    sa.select(sa.func.count(Message.id)).where(
                        Message.conversation_id == conversation_id,
                        Message.direction == MessageDirection.INBOUND.value,
                        Message.created_at > last_outbound,
                    )
                ).scalar_one()
                if newer_inbound > 0:
                    return False, "inbound_since_scheduled"

        # (c) Window check for re-engage/rescue.
        if conv.outreach_state in (
            {s.value for s in OUTREACH_REENGAGE_STATES}
            | {s.value for s in OUTREACH_RESCUE_STATES}
        ):
            last_inbound = self._session.execute(
                sa.select(Message.created_at)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.direction == MessageDirection.INBOUND.value,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            if last_inbound is not None:
                now = datetime.now(tz=UTC)
                window_remaining = (
                    FREE_WINDOW_HOURS * 3600
                    - (now - last_inbound).total_seconds()
                )
                if window_remaining <= 0:
                    return False, "window_closed"

        # (e) Active hours gate.
        if not self.within_active_hours():
            return False, "outside_active_hours"

        return True, None

    def within_active_hours(self) -> bool:
        """Return True if the current time is within the configured active hours."""
        now_utc = datetime.now(tz=UTC)

        # Default: UTC. Read ops.timezone setting if available.
        try:
            from sqlalchemy import select
            from app.modules.settings.models import AppSetting

            stmt = (
                select(AppSetting)
                .where(
                    AppSetting.key == SETTING_OPS_TIMEZONE,
                    AppSetting.scope == "global",
                )
            )
            row = self._session.execute(stmt).scalar_one_or_none()
            import zoneinfo

            tz_name = "UTC"
            if row is not None and isinstance(row.value, dict):
                tz_name = row.value.get("tz", "UTC")
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            hour = now_utc.hour
            return DEFAULT_ACTIVE_HOURS_START <= hour < DEFAULT_ACTIVE_HOURS_END

        now_local = now_utc.astimezone(tz)
        hour = now_local.hour
        return DEFAULT_ACTIVE_HOURS_START <= hour < DEFAULT_ACTIVE_HOURS_END

    # --------------------------------------------------------------- schedule

    def schedule_followup(
        self,
        conversation_id: uuid.UUID,
        outreach_state: OutreachState,
        fire_at: datetime,
        context: dict | None = None,
    ) -> tuple[str, float, dict | None] | None:
        """Schedule a follow-up by setting outreach_state atomically.

        Returns (entity_id, countdown_seconds, context) so the CALLER can
        dispatch ``process_scheduled_followup_task`` via ``apply_async`` after
        the session commits (Msg-C4: service never dispatches Celery tasks).

        Returns None if scheduling failed (dedup - another follow-up was
        already in flight).
        """
        from app.modules.conversations.models import Conversation
        from app.modules.conversations.repository import ConversationRepository

        # Atomic dedup: only schedule if no follow-up is already in flight.
        conv = self._session.get(Conversation, conversation_id)
        if conv is None or conv.outreach_state is not None:
            logger.info(
                "followup_schedule_dedup",
                conversation_id=str(conversation_id),
            )
            return None

        repo = ConversationRepository(self._session)  # type: ignore[arg-type]
        repo.update_outreach_state_sync(
            conversation_id,
            outreach_state.value,
        )

        countdown = max(0, (fire_at - datetime.now(tz=UTC)).total_seconds())

        logger.info(
            "followup_scheduled",
            conversation_id=str(conversation_id),
            outreach_state=outreach_state.value,
            fire_at=fire_at.isoformat(),
            countdown_seconds=countdown,
        )
        return str(conversation_id), countdown, (context or {})

    # ---------------------------------------------------------- cancel / reply

    def cancel_pending_followups(self, conversation_id: uuid.UUID) -> int:
        """Cancel all pending follow-ups. Returns number of transitions applied."""
        from app.modules.conversations.repository import ConversationRepository

        repo = ConversationRepository(self._session)  # type: ignore[arg-type]
        conv = self._session.get(Conversation, conversation_id)
        if conv is None or conv.outreach_state is None:
            return 0

        if conv.outreach_state in {s.value for s in OUTREACH_TERMINAL_STATES}:
            return 0

        rows = repo.update_outreach_state_sync(
            conversation_id,
            OutreachState.CONVERTED.value,
        )
        return rows

    def on_first_reply(self, conversation_id: uuid.UUID) -> None:
        """Handle first reply: cancel cold follow-ups, hand to conversation engine.

        Transitions any non-terminal outreach state to CONVERTED (§7: reply trumps cadence).
        """
        from app.modules.conversations.repository import ConversationRepository

        conv = self._session.get(Conversation, conversation_id)
        if conv is None:
            return

        if conv.outreach_state is None:
            return

        if conv.outreach_state in {s.value for s in OUTREACH_TERMINAL_STATES}:
            return

        repo = ConversationRepository(self._session)  # type: ignore[arg-type]
        repo.update_outreach_state_sync(
            conversation_id,
            OutreachState.CONVERTED.value,
        )

        logger.info(
            "outreach_converted_on_reply",
            conversation_id=str(conversation_id),
            from_state=conv.outreach_state,
        )

    # ----------------------------------------------------------- helpers

    def _load_thread_context(
        self, conversation_id: uuid.UUID
    ) -> dict:
        """Load the last exchange for context-based rescue follow-ups (§4.3)."""
        import sqlalchemy as sa

        from app.modules.messaging.models import Message

        rows = self._session.execute(
            sa.select(Message.direction, Message.sender_type, Message.content)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(6)
        ).all()

        messages: list[dict] = []
        for direction, sender_type, content in reversed(rows):
            messages.append({
                "direction": direction,
                "sender_type": sender_type,
                "content": content,
            })

        return {"thread_messages": messages}
