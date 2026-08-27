"""Engagement Celery tasks: follow-up scheduling sweep and per-message dispatch
(agent-engagement-policy §4-§8).

Two tasks:
  * ``engagement_sweep_task`` - beat-driven (every 120 s). Scans for conversations
    needing re-engage (§4.2) or rescue (§4.3) follow-ups, and cold campaign
    recipients needing Touch 2 (§4.1).
  * ``process_scheduled_followup_task`` - dispatched by the sweep with an ETA
    countdown. Runs pre-fire checks, generates content, sends via the existing
    ``send_outbound_message_task``, and advances the outreach_state.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from celery import Task

from app.celery_app import celery_app
from app.db.session import sync_session_factory
from app.modules.conversations.models import Conversation
from app.modules.engagement.constants import (
    COLD_FOLLOWUP_DELAY_HOURS,
    ENGAGEMENT_SWEEP_INTERVAL_SECONDS,
    OUTREACH_COLD_STATES,
    OUTREACH_REENGAGE_STATES,
    OUTREACH_RESCUE_STATES,
    OutreachState,
)
from app.modules.engagement.service import EngagementService

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="engagement.tasks.engagement_sweep_task",
    bind=True,
    max_retries=1,
    default_retry_delay=120,
)
def engagement_sweep_task(self: Task) -> dict:  # pragma: no cover — Celery beat
    """Beat-driven sweep: find conversations that need follow-up scheduling.

    Scans for:
      1. In-window re-engage (§4.2) - 1 inbound, silent, window open.
      2. In-window rescue (§4.3) - ≥2 inbound, silent, AI_ACTIVE, window open.
      3. Cold track Touch 2 (§4.1) - campaign_recipients with OUTREACH_SENT
         past the 24h mark, not yet responded.

    Returns counts of follow-ups scheduled by regime.
    """
    import sqlalchemy as sa

    from app.modules.campaigns.constants import CampaignRecipientStatus
    from app.modules.campaigns.models import CampaignRecipient
    from app.modules.messaging.constants import MessageDirection
    from app.modules.messaging.models import Message

    result = {"reengage": 0, "rescue": 0, "cold_followup": 0}
    # Buffer dispatch specs so apply_async happens AFTER commit (Msg-C4).
    _dispatches: list[tuple[list, dict, float | int]] = []

    with sync_session_factory() as session:
        svc = EngagementService(session)

        # --- in-window follow-ups (§4.2 re-engage + §4.3 rescue) ---
        candidates = session.execute(
            sa.select(
                Conversation.id,
                Conversation.state,
                sa.func.count(Message.id).label("msg_count"),
                sa.func.max(
                    sa.case(
                        (Message.direction == MessageDirection.INBOUND.value, Message.created_at),
                        else_=None,
                    )
                ).label("last_inbound"),
            )
            .select_from(Conversation)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(
                Conversation.outreach_state.is_(None),
                Conversation.ai_enabled.is_(True),
            )
            .group_by(Conversation.id)
        ).all()

        now = datetime.now(tz=UTC)

        for conv_id, state, msg_count, last_inbound in candidates:
            if last_inbound is None:
                continue

            if msg_count == 1:
                since_inbound = (now - last_inbound).total_seconds() / 3600
                from app.modules.engagement.constants import (
                    FREE_WINDOW_HOURS,
                    REENGAGE_1_MIN_HOURS,
                )

                if since_inbound < REENGAGE_1_MIN_HOURS:
                    continue
                if since_inbound > FREE_WINDOW_HOURS:
                    from app.modules.conversations.repository import (
                        ConversationRepository,
                    )

                    ConversationRepository(session).update_outreach_state_sync(  # type: ignore[arg-type]
                        conv_id, OutreachState.UNRESPONSIVE.value
                    )
                    _auto_tag_contact(session, conv_id, "UNRESPONSIVE")
                    continue

                next_state, timing = svc.select_regime(conv_id)
                if next_state is not None and timing is not None:
                    dispatched = svc.schedule_followup(
                        conv_id,
                        next_state,
                        timing["fire_at"],
                        timing.get("context"),
                    )
                    if dispatched is not None:
                        entity_id, countdown, ctx = dispatched
                        _dispatches.append((
                            [entity_id, next_state.value],
                            {"context": ctx},
                            countdown,
                        ))
                        result["reengage"] += 1

            elif msg_count >= 2 and state == "AI_ACTIVE":
                since_inbound = (now - last_inbound).total_seconds() / 3600
                from app.modules.engagement.constants import (
                    FREE_WINDOW_HOURS,
                    RESCUE_1_MIN_HOURS,
                )

                if since_inbound < RESCUE_1_MIN_HOURS:
                    continue
                if since_inbound > FREE_WINDOW_HOURS:
                    continue

                next_state, timing = svc.select_regime(conv_id)
                if next_state is not None and timing is not None:
                    dispatched = svc.schedule_followup(
                        conv_id,
                        next_state,
                        timing["fire_at"],
                        timing.get("context"),
                    )
                    if dispatched is not None:
                        entity_id, countdown, ctx = dispatched
                        _dispatches.append((
                            [entity_id, next_state.value],
                            {"context": ctx},
                            countdown,
                        ))
                        result["rescue"] += 1

        # --- cold track Touch 2 (§4.1) ---
        cold_candidates = session.execute(
            sa.select(CampaignRecipient)
            .where(
                CampaignRecipient.outreach_state == OutreachState.OUTREACH_SENT.value,
                CampaignRecipient.responded.is_(False),
                CampaignRecipient.sent_at.is_not(None),
                CampaignRecipient.sent_at
                < now - timedelta(hours=COLD_FOLLOWUP_DELAY_HOURS),
            )
        ).scalars().all()

        for cr in cold_candidates:
            conv = session.execute(
                sa.select(Conversation)
                .where(Conversation.contact_id == cr.contact_id)
                .order_by(Conversation.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            if conv is not None:
                inbound_since = session.execute(
                    sa.select(sa.func.count(Message.id)).where(
                        Message.conversation_id == conv.id,
                        Message.direction == MessageDirection.INBOUND.value,
                        Message.created_at > cr.sent_at,
                    )
                ).scalar_one()
                if inbound_since > 0:
                    cr.outreach_state = OutreachState.CONVERTED.value
                    continue

            cr.outreach_state = OutreachState.COLD_FOLLOWUP_SENT.value
            _dispatches.append((
                [str(cr.id), OutreachState.COLD_FOLLOWUP_SENT.value],
                {"is_cold": True},
                300,
            ))
            result["cold_followup"] += 1

        session.commit()

    # Msg-C4: dispatch Celery tasks AFTER the session has committed.
    for args, kwargs, countdown in _dispatches:
        process_scheduled_followup_task.apply_async(
            args=args, kwargs=kwargs, countdown=countdown
        )

    if any(result.values()):
        logger.info(
            "engagement_sweep_completed",
            **result,
        )
    return result


@celery_app.task(
    name="engagement.tasks.process_scheduled_followup_task",
    bind=True,
    max_retries=2,
    acks_late=True,
)
def process_scheduled_followup_task(  # pragma: no cover — Celery ETA dispatch
    self: Task,
    entity_id: str,
    outreach_state: str,
    *,
    context: dict | None = None,
    is_cold: bool = False,
) -> dict:
    """Execute a single scheduled follow-up after pre-fire checks.

    For cold track (§4.1): dispatches the same template again via the
    existing campaign send path. For in-window (§4.2-4.3): generates an
    AI-authored free-form follow-up inside the WhatsApp free window.

    Returns {"sent": bool, "reason": str}.
    """
    import sqlalchemy as sa

    from app.modules.campaigns.models import CampaignRecipient
    from app.modules.messaging.models import Message
    from app.modules.messaging.tasks import send_outbound_message_task

    if is_cold:
        # Cold track follow-up - use the campaign infrastructure.
        with sync_session_factory() as session:
            from sqlalchemy import select as sa_select

            from app.modules.contacts.models import Contact
            from app.modules.messaging.models import Message

            cr = session.get(CampaignRecipient, uuid.UUID(entity_id))
            if cr is None:
                return {"sent": False, "reason": "campaign_recipient_missing"}

            # Pre-fire checks: do_not_contact, active hours.
            contact = session.get(Contact, cr.contact_id)
            if contact is not None and contact.do_not_contact:
                return {"sent": False, "reason": "contact_suppressed"}

            svc = EngagementService(session)
            if not svc.within_active_hours():
                logger.info(
                    "cold_followup_skipped_active_hours",
                    campaign_recipient_id=entity_id,
                )
                return {"sent": False, "reason": "outside_active_hours"}

            # Re-send the template.
            if cr.message_id is None:
                return {"sent": False, "reason": "no_message_id"}

            send_outbound_message_task.delay(str(cr.message_id))
            logger.info(
                "cold_followup_dispatched",
                campaign_recipient_id=entity_id,
            )
            return {"sent": True, "reason": "cold_followup"}

    # In-window follow-up (§4.2-4.3) - AI-generated free-form.
    conv_uuid = uuid.UUID(entity_id)
    state = OutreachState(outreach_state)
    is_rescue = state in OUTREACH_RESCUE_STATES

    with sync_session_factory() as session:
        svc = EngagementService(session)

        passed, reason = svc.pre_fire_checks(conv_uuid, is_rescue=is_rescue)
        if not passed:
            logger.info(
                "followup_skipped_prefire",
                conversation_id=entity_id,
                outreach_state=outreach_state,
                reason=reason,
            )
            if is_rescue and reason == "human_took_over":
                # §8.g: Cancel, never defer.
                svc.cancel_pending_followups(conv_uuid)
                session.commit()
            return {"sent": False, "reason": reason or "prefire_failed"}

        # Generate follow-up content via AI.
        draft_content = _generate_followup_content(
            session, conv_uuid, state, context
        )
        if draft_content is None:
            return {"sent": False, "reason": "ai_content_generation_failed"}

        # Persist as QUEUED AI message.
        msg_uuid = uuid.uuid4()
        now = datetime.now(tz=UTC)
        message = Message(
            id=msg_uuid,
            conversation_id=conv_uuid,
            direction="outbound",
            sender_type="ai",
            content=draft_content,
            delivery_status="queued",
            created_at=now,
        )
        session.add(message)

        # Advance outreach state unless this was the last follow-up.
        # For terminal stages: set UNRESPONSIVE. For intermediate: set the state.
        session.flush()
        session.commit()

    # Dispatch outside session (Msg-C4 pattern).
    send_outbound_message_task.delay(str(msg_uuid))

    logger.info(
        "followup_dispatched",
        conversation_id=entity_id,
        outreach_state=outreach_state,
        message_id=str(msg_uuid),
    )
    return {"sent": True, "message_id": str(msg_uuid)}


def _generate_followup_content(
    session,
    conv_uuid: uuid.UUID,
    state: OutreachState,
    context: dict | None,
) -> str | None:
    """Generate a follow-up message using Claude.

    For §4.3 rescue: MUST reference the thread context.
    For §4.2 re-engage: lighter, generic "still interested?"
    """
    import asyncio

    import structlog

    _log = structlog.get_logger(__name__)

    try:
        from app.core.config import get_settings
        from app.integrations.claude import ClaudeClient
        from app.modules.ai.prompts import build_system_blocks
        from app.modules.categorization.constants import PREDEFINED_TAGS

        settings = get_settings()
        client = ClaudeClient(settings, tag_taxonomy=PREDEFINED_TAGS)

        if state in OUTREACH_RESCUE_STATES:
            thread = context.get("thread_messages", []) if context else []
            thread_text = "\n".join(
                f"{m.get('sender_type', 'unknown')}: {m.get('content', '')}"
                for m in thread[-6:]
            )
            prompt = (
                f"The conversation went silent. Here is the last exchange:\n\n"
                f"{thread_text}\n\n"
                f"Generate a SHORT (1-6 word) natural follow-up as Sara. "
                f"Reference the last topic they discussed. Do NOT be generic."
            )
        else:
            prompt = (
                "The contact replied once but hasn't responded to the follow-up. "
                "Generate a SHORT (1-6 word) casual nudge as Sara. Something like "
                "'hey still interested?' but in your natural voice."
            )

        system_blocks = build_system_blocks()
        messages = [{"role": "user", "content": prompt}]

        response, _, _ = asyncio.run(
            client.propose_reply(
                system_blocks=system_blocks,
                messages=messages,
                model=settings.AI_MODEL_BULK,
            )
        )

        return response.reply.strip() if response.reply.strip() else None
    except Exception:
        _log.warning(
            "followup_content_generation_failed",
            conversation_id=str(conv_uuid),
            exc_info=True,
        )
        return None


def _auto_tag_contact(
    session, conversation_id: uuid.UUID, tag_name: str
) -> None:
    """Auto-apply a tag to the conversation's contact without a suggestion row."""
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.modules.categorization.models import ContactTag, Tag
    from app.modules.conversations.models import Conversation

    conv = session.get(Conversation, conversation_id)
    if conv is None:
        return

    session.execute(
        pg_insert(Tag)
        .values(name=tag_name)
        .on_conflict_do_nothing(index_elements=["name"])
    )
    session.flush()

    tag = session.execute(
        sa.select(Tag).where(Tag.name == tag_name)
    ).scalar_one()

    session.execute(
        pg_insert(ContactTag)
        .values(contact_id=conv.contact_id, tag_id=tag.id)
        .on_conflict_do_nothing(constraint="pk_contact_tags")
    )
