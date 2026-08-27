"""
app/modules/messaging/tasks.py

Fixes applied:
  Msg-C1 — process_inbound_webhook_task claimed the Redis dedup key BEFORE
            calling _persist_inbound. If _persist_inbound raised (e.g.
            transient DB error, IntegrityError), the exception was swallowed
            by the dedup guard and the key remained set for 24 hours. Meta's
            retry delivery was silently discarded as a duplicate for the
            entire blackout period — messages were permanently lost with only
            a log line.

            Fix: dedup key is written ONLY AFTER successful persistence.
            If persistence fails, no key is set, so Meta's redelivery
            will be processed correctly on the next attempt.

  Msg-C2 — Same root cause for status-callback processing. A transient DB
            error during _apply_status_update set the dedup key for 6 hours,
            causing replayed status updates to be discarded for that window.

            Fix: same pattern — claim key after successful processing.

  Msg-I7  — NEW → AI_ACTIVE transition inside _persist_inbound did not
            check conversation.ai_enabled. AI-disabled conversations were
            re-enabled on any subsequent inbound message.

            Fix: transition only fires if ai_enabled is True on the
            conversation.

  Msg-I8  (see messaging/repository.py) — increment_retry is atomic.

Cross-module coupling: this module lazily imports from ``app.modules.campaigns``
(CampaignRecipient, CampaignRecipientRepository, CampaignRepository,
CampaignRecipientStatus) inside four functions (_cancel_pending_outreach_on_reply,
_attribute_inbound_to_campaigns, _propagate_to_campaign_recipient,
_backfill_campaign_recipient_meta_id). The lazy pattern keeps the import-time
dependency graph clean (campaigns→messaging is the natural direction, not the
reverse). An event-driven refactor (campaigns subscribing to MessageEvents) is
deferred — it would change the transaction boundary for campaign attribution.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from celery import Task
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.celery_app import celery_app
from app.core.exceptions import ConcurrentModificationError
from app.core.redis import get_sync_redis, redis_healthy
from app.db.session import sync_session_factory
from app.modules.categorization.models import ContactTag, Tag
from app.modules.contacts.constants import ContactStatus
from app.core.phone import canonicalize_phone
from app.modules.contacts.repository import ContactRepository
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.models import Conversation
from app.modules.messaging.constants import (
    DELIVERY_FAILURE_RETRY_DELAYS,
    MAX_DELIVERY_RETRIES,
    MessageDeliveryStatus,
    MessageDirection,
    SenderType,
)
from app.modules.messaging.repository import MessageRepository

logger = structlog.get_logger(__name__)

# Dedup TTL constants
_INBOUND_DEDUP_TTL_SECONDS = 86_400   # 24 h — matches Meta's redelivery window
_STATUS_DEDUP_TTL_SECONDS = 21_600    # 6 h

# Retry schedule for send_outbound_message_task
_MAX_RETRIES = 4
_RETRY_DELAYS = [0, 30, 120, 600]  # seconds: immediate, 30s, 2m, 10m

# DSD §11 — Redis Failure → pause outbound dispatch.
# Decision (P1.3): retry-with-backoff, NOT noop. send_outbound_message_task
# has no beat re-driver, so a noop would strand the message. We reschedule
# on a dedicated budget that is *separate* from the Meta-send retry budget
# (_MAX_RETRIES): a Redis outage must never consume a message's terminal-fail
# attempts nor mark it FAILED. The message row stays QUEUED the whole time,
# so nothing is dropped. Budget is bounded (not infinite) to avoid an
# unbounded backlog: 30x60s ~= 30 min of Redis downtime tolerated, after
# which Celery raises MaxRetriesExceeded and the row remains QUEUED for a
# later manual/scheduled re-drive (deliberately not auto-FAILED).
_REDIS_DOWN_RETRY_SECONDS = 60
_REDIS_DOWN_MAX_RETRIES = 30

# Monotonic delivery-status ordering. A callback may only advance a message
# to a strictly higher rank. `failed` sits below `delivered` so a late
# failure cannot regress an already-delivered/read message, while a failure
# on a not-yet-delivered message (queued/sent) is still recorded.
_DELIVERY_RANK = {
    MessageDeliveryStatus.DRAFT.value: 0,
    MessageDeliveryStatus.QUEUED.value: 1,
    MessageDeliveryStatus.SENT.value: 2,
    MessageDeliveryStatus.FAILED.value: 3,
    MessageDeliveryStatus.DELIVERED.value: 4,
    MessageDeliveryStatus.READ.value: 5,
}


# --------------------------------------------------- delivery-failure retry

@celery_app.task(
    name="messaging.tasks.reset_and_retry_message",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
    acks_late=True,
)
def reset_and_retry_message_task(self: Task, message_id: str, attempt: int) -> None:
    """Reset a delivery-failed message back to QUEUED and re-dispatch.

    Scheduled by _apply_status_update when a Meta status webhook reports
    ``failed``. The setting is re-checked here (it may have been toggled off
    between scheduling and execution). The message is reset in-place — same
    row — so the frontend sees FAILED → QUEUED → SENT → DELIVERED.
    """
    from app.modules.settings.constants import SETTING_OPS_DELIVERY_FAILURE_RETRY
    from app.modules.settings.repository import get_bool_setting_sync

    msg_uuid = uuid.UUID(message_id)

    with sync_session_factory() as session:
        try:
            enabled = get_bool_setting_sync(
                session, SETTING_OPS_DELIVERY_FAILURE_RETRY, default=True
            )
        except Exception:
            logger.warning(
                "delivery_retry_setting_read_failed",
                message_id=message_id,
                exc_info=True,
            )
            return

        if not enabled:
            logger.info(
                "delivery_retry_skipped_setting_disabled",
                message_id=message_id,
            )
            return

        msg_repo = MessageRepository(session)  # type: ignore[arg-type]
        message = msg_repo.get_sync(msg_uuid)

        if message is None:
            logger.warning(
                "delivery_retry_message_not_found",
                message_id=message_id,
            )
            return

        # Guard: only reset if still FAILED. A concurrent status callback
        # (e.g. a late ``delivered`` webhook) may have advanced the status
        # since this task was scheduled.
        if message.delivery_status != MessageDeliveryStatus.FAILED:
            logger.info(
                "delivery_retry_skipped_not_failed",
                message_id=message_id,
                current_status=str(message.delivery_status),
            )
            return

        # Atomic increment (DB-I8 pattern: server-side arithmetic).
        msg_repo.increment_delivery_retry_sync(msg_uuid)

        # Reset to QUEUED: clear the failure state so send_outbound_message_task
        # picks this message up again. Meta re-assigns a new wamid on the
        # successful send, so we clear meta_message_id as well.
        msg_repo.update_delivery_status_sync(
            message_id=msg_uuid,
            new_status=MessageDeliveryStatus.QUEUED,
            last_error=None,
            error_code=None,
            meta_message_id=None,
        )

        session.commit()

    # Dispatch the existing send task — now that the row is QUEUED, it will
    # be picked up and sent. Redis-down handling is covered by the send task's
    # own probe.
    send_outbound_message_task.delay(message_id)

    logger.info(
        "delivery_retry_dispatched",
        message_id=message_id,
        attempt=attempt + 1,
    )


# -------------------------------------------------------- inbound processing

@celery_app.task(
    name="messaging.tasks.process_inbound_webhook",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    acks_late=True,
)
def process_inbound_webhook_task(self: Task, payload: dict[str, Any]) -> None:
    """
    Process a normalised Meta webhook payload.

    Msg-C1/C2 fix: dedup keys are now claimed AFTER successful processing.
    The previous pattern:
        1. check dedup key (not set → proceed)
        2. SET dedup key                    ← bug: key set before work
        3. do work (may fail)
        4. if work fails, exception swallowed, key stays 24h

    New pattern:
        1. check dedup key (not set → proceed)
        2. do work
        3. if work succeeds → SET dedup key  ← key set only on success
        4. if work fails → exception raised, task retried by Celery
           Meta's redelivery will not be blocked by a stale dedup key
    """
    redis = get_sync_redis()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # --- inbound messages ---
            for msg in value.get("messages", []):
                meta_msg_id = msg.get("id")
                if not meta_msg_id:
                    continue

                dedup_key = f"dedup:inbound:{meta_msg_id}"

                # Step 1: check if already processed.
                if redis.exists(dedup_key):
                    logger.info(
                        "inbound_message_deduplicated",
                        meta_message_id=meta_msg_id,
                    )
                    continue

                # Step 2: persist (may raise — intentional, triggers Celery retry).
                try:
                    _persist_inbound(msg, value)
                except Exception as exc:
                    logger.exception(
                        "inbound_message_persist_failed",
                        meta_message_id=meta_msg_id,
                        error=str(exc),
                    )
                    # Msg-C1 fix: do NOT set dedup key — let Meta retry.
                    raise self.retry(exc=exc) from exc

                # Step 3: claim dedup key ONLY after successful persistence.
                redis.setex(dedup_key, _INBOUND_DEDUP_TTL_SECONDS, "1")
                logger.info(
                    "inbound_message_processed",
                    meta_message_id=meta_msg_id,
                )

            # --- status updates ---
            for status_update in value.get("statuses", []):
                meta_msg_id = status_update.get("id")
                new_status = status_update.get("status")
                if not meta_msg_id or not new_status:
                    continue

                dedup_key = f"dedup:status:{meta_msg_id}:{new_status}"

                # Step 1: check dedup.
                if redis.exists(dedup_key):
                    logger.info(
                        "status_update_deduplicated",
                        meta_message_id=meta_msg_id,
                        status=new_status,
                    )
                    continue

                # Step 2: apply status update (may raise).
                try:
                    _apply_status_update(meta_msg_id, new_status, status_update)
                except Exception as exc:
                    logger.exception(
                        "status_update_apply_failed",
                        meta_message_id=meta_msg_id,
                        status=new_status,
                        error=str(exc),
                    )
                    # Msg-C2 fix: do NOT set dedup key — let Meta retry.
                    raise self.retry(exc=exc) from exc

                # Step 3: claim dedup key ONLY after successful processing.
                redis.setex(dedup_key, _STATUS_DEDUP_TTL_SECONDS, "1")
                logger.info(
                    "status_update_processed",
                    meta_message_id=meta_msg_id,
                    status=new_status,
                )


def _persist_inbound(
    msg: dict[str, Any],
    value: dict[str, Any],
) -> None:
    """
    Persist an inbound message and ensure the conversation is in the
    correct state.

    Msg-I7 fix: NEW → AI_ACTIVE transition now checks conversation.ai_enabled.
    Previously, any inbound message to an AI-disabled conversation would
    silently re-enable AI by firing the transition unconditionally.

    Msg-I1/I10 fix: uses ContactRepository.upsert_by_phone for contact
    resolution — handles concurrent inbound from new contacts correctly
    and stays within the repository pattern.
    """
    # The contact for an INBOUND message is the SENDER (`msg.from`).
    # `metadata.display_phone_number` is the business's OWN number and is
    # always present — using it would collapse every customer onto a single
    # contact, so the sender must take precedence.
    raw_phone = msg.get("from") or value.get("metadata", {}).get(
        "display_phone_number"
    )
    # Canonicalize to the digits-only wa_id form before lookup. Meta already
    # reports `from` as a bare wa_id, but normalizing here keeps the inbound
    # path in lock-step with how contacts are stored (digits only) so a saved
    # contact is never missed and re-created as a name-less duplicate.
    phone = canonicalize_phone(raw_phone) if raw_phone else ""
    if not phone:
        logger.warning("inbound_message_missing_phone", msg=msg)
        return

    meta_msg_id = msg["id"]
    content = _extract_text_content(msg)
    timestamp_raw = msg.get("timestamp")
    created_at = (
        datetime.fromtimestamp(int(timestamp_raw), tz=UTC)
        if timestamp_raw
        else datetime.now(tz=UTC)
    )

    with sync_session_factory() as session:
        from app.modules.conversations.repository import ConversationRepository  # lazy — cross-module

        contact_repo = ContactRepository(session)  # type: ignore[arg-type]
        conv_repo = ConversationRepository(session)  # type: ignore[arg-type]
        msg_repo = MessageRepository(session)  # type: ignore[arg-type]

        # Msg-I10 fix: use sync upsert_by_phone (handles race correctly inside Celery).
        contact = contact_repo.upsert_by_phone_sync(phone=phone)

        # Record inbound activity for pipeline tracking (contacted → follow_up gate).
        contact_repo.touch_last_inbound_sync(contact.id)

        # Get or create open conversation.
        conv = conv_repo.get_active_for_contact_sync(contact.id)
        if conv is None:
            # Auto-apply the "Inbound Contact" tag only when this contact has
            # never had ANY conversation (open or closed) — i.e. truly first
            # user-initiated inbound message. Check before creating the new
            # conversation so the new one doesn't mask the check.
            row = session.execute(
                select(Conversation.id)
                .where(Conversation.contact_id == contact.id)
                .limit(1)
            ).first()
            has_any_conv = row is not None

            conv = conv_repo.create_for_contact_sync(contact_id=contact.id)

            # Derive ai_enabled from the contact's assignment.
            # AI-assigned contact → AI handles. Human-assigned contact →
            # human handles (AI disabled so the conversation goes directly
            # to HUMAN_ASSIGNED in the state transition below).
            if contact.ai_assigned:
                conv.ai_enabled = True
            elif contact.assigned_agent_id is not None:
                conv.ai_enabled = False

            if not has_any_conv:
                session.execute(
                    pg_insert(Tag)
                    .values(name="Inbound Contact")
                    .on_conflict_do_nothing(index_elements=["name"])
                )
                session.flush()
                inbound_tag = session.execute(
                    select(Tag).where(Tag.name == "Inbound Contact")
                ).scalar_one()
                session.execute(
                    pg_insert(ContactTag)
                    .values(contact_id=contact.id, tag_id=inbound_tag.id)
                    .on_conflict_do_nothing(constraint="pk_contact_tags")
                )

        # Msg-I7 fix: only transition to AI_ACTIVE if ai_enabled is True.
        # Conv-I2: rowcount==0 means a concurrent worker transitioned the row;
        # raise so Celery retries (next pass will see the new state).
        ai_should_run = False
        first_activated = False
        if conv.state == ConversationState.NEW and conv.ai_enabled:
            rowcount = conv_repo.update_state_sync(
                conversation_id=conv.id,
                expected_state=ConversationState.NEW,
                new_state=ConversationState.AI_ACTIVE,
            )
            if rowcount == 0:
                raise ConcurrentModificationError(
                    f"Conversation {conv.id} state changed during NEW→AI_ACTIVE transition"
                )
            ai_should_run = True
            first_activated = True
        elif conv.state == ConversationState.AI_ACTIVE and conv.ai_enabled:
            # Follow-up inbound on an already AI-handled conversation.
            ai_should_run = True
        elif conv.state == ConversationState.NEW and not conv.ai_enabled:
            # ai_enabled=False on a NEW conversation — go directly to HUMAN_ASSIGNED.
            rowcount = conv_repo.update_state_sync(
                conversation_id=conv.id,
                expected_state=ConversationState.NEW,
                new_state=ConversationState.HUMAN_ASSIGNED,
            )
            if rowcount == 0:
                raise ConcurrentModificationError(
                    f"Conversation {conv.id} state changed during NEW→HUMAN_ASSIGNED transition"
                )

        # Persist the message row. For media messages, content is the caption
        # (or a "[type]" placeholder), and msg_type is set so the frontend
        # renders the appropriate bubble.
        msg_type = _classify_msg_type(msg)
        # Reply / reaction context: resolve the referenced message to a local
        # UUID so the frontend can display the quoted/reacted-to message.
        ctx_meta_id = (msg.get("context") or {}).get("id")
        if not ctx_meta_id:
            ctx_meta_id = (msg.get("reaction") or {}).get("message_id")
        ctx_local_id = None
        if ctx_meta_id:
            ctx_msg = msg_repo.get_by_meta_id_sync(ctx_meta_id)
            if ctx_msg is not None:
                ctx_local_id = ctx_msg.id

        message = msg_repo.create_sync(
            conversation_id=conv.id,
            direction=MessageDirection.INBOUND,
            sender_type=SenderType.CONTACT,
            content=content,
            meta_message_id=meta_msg_id,
            delivery_status=MessageDeliveryStatus.DELIVERED,
            created_at=created_at,
            msg_type=msg_type,
            context_message_id=ctx_local_id,
        )

        # For media messages, download from Meta and persist a MediaAsset row.
        # Done BEFORE commit so the asset is part of the same transaction;
        # if download fails we log and continue — the message still exists
        # with its text placeholder.
        media_id = msg.get("image", {}).get("id") or \
                   msg.get("audio", {}).get("id") or \
                   msg.get("video", {}).get("id") or \
                   msg.get("document", {}).get("id")
        if media_id and msg_type != "text":
            _download_and_store_media(
                session, media_id=media_id, msg_type=msg_type,
                message_id=message.id, msg=msg,
            )

        # Campaign attribution: flag any recent campaign send to this
        # contact as having received a response.
        _attribute_inbound_to_campaigns(session, contact_id=contact.id, when=created_at)

        # Bump last_message_at so the inbox (ordered last_message_at DESC)
        # floats the conversation to the top on inbound — mirrors the
        # outbound pattern in send_outbound_message_task.
        conv_repo.touch_last_message_sync(conv.id, created_at)

        # Explicit commit — sync_session_factory does not auto-commit.
        session.commit()

        # Engagement policy §2: keyword-based opt-out detection runs BEFORE
        # AI dispatch. If the inbound message signals opt-out, suppress the
        # contact immediately (do_not_contact + DO_NOT_CONTACT tag + outreach
        # state SUPPRESSED) and skip AI processing entirely.
        from app.modules.engagement.constants import (
            OutreachState,
            detect_opt_out_keywords,
        )

        if content and detect_opt_out_keywords(content):
            contact_repo.set_do_not_contact_sync(contact.id, True)
            _apply_opt_out_tag_sync(session, contact.id)

            conv_repo.update_outreach_state_sync(
                conv.id, OutreachState.SUPPRESSED.value
            )

            session.commit()
            logger.info(
                "opt_out_detected_keyword",
                contact_id=str(contact.id),
                conversation_id=str(conv.id),
            )
            ai_should_run = False
            first_activated = False

        conv_id_str = str(conv.id)
        contact_id_str = str(contact.id)

    # Conv-I5 / P2.4: the NEW → AI_ACTIVE entry transition (DSD §4.2) fires
    # in the messaging task path (NOT via ConversationService — the sync
    # Celery split uses the guarded `update_state_sync`). Emit FIRST_ACTIVATED
    # so the event is no longer silently dropped on this path. Emitted AFTER
    # commit so subscribers/WS clients never observe a not-yet-durable state.
    if first_activated:
        from app.core.events import ConversationEvents, emit_event

        emit_event(
            ConversationEvents.FIRST_ACTIVATED,
            conversation_id=conv_id_str,
            from_state=ConversationState.NEW.value,
            to_state=ConversationState.AI_ACTIVE.value,
            actor_type="system",
        )

    # P2.1: notify the live inbox that an inbound message landed (drives the
    # dashboard re-fetch within DSD §10's <2s target). Best-effort fan-out is
    # handled inside emit_event → Redis pub/sub.
    from app.core.events import MessageEvents, emit_event

    emit_event(
        MessageEvents.RECEIVED,
        conversation_id=conv_id_str,
        contact_id=contact_id_str,
        meta_message_id=meta_msg_id,
    )

    # Engagement policy §7: any inbound reply trumps the outreach cadence.
    # Cancel pending follow-ups on the conversation and convert any cold-track
    # campaign_recipient to CONVERTED. Runs regardless of ai_should_run.
    _cancel_pending_outreach_on_reply(conv_id_str)

    # Msg-C4: the inbound row is durable (committed above) BEFORE we dispatch
    # the AI worker, so request_ai_reply_task can never observe a missing row.
    if ai_should_run and content:
        from app.modules.ai.tasks import request_ai_reply_task

        request_ai_reply_task.delay(conv_id_str, content)


def _cancel_pending_outreach_on_reply(conversation_id: str) -> None:
    """Cancel any pending follow-ups when a contact replies (§7).

    Sets outreach_state = CONVERTED on the conversation; on campaign_recipient
    rows for the same contact, sets outreach_state = CONVERTED.
    """
    import sqlalchemy as sa

    from app.modules.campaigns.models import CampaignRecipient
    from app.modules.conversations.models import Conversation
    from app.modules.engagement.constants import OUTREACH_TERMINAL_STATES, OutreachState

    conv_uuid = uuid.UUID(conversation_id)

    with sync_session_factory() as session:
        conv = session.get(Conversation, conv_uuid)
        if conv is None:
            return

        if conv.outreach_state is not None and conv.outreach_state not in {
            s.value for s in OUTREACH_TERMINAL_STATES
        }:
            session.execute(
                sa.update(Conversation)
                .where(Conversation.id == conv_uuid)
                .values(outreach_state=OutreachState.CONVERTED.value)
            )

        # Cold track: any campaign_recipient for this contact in a non-terminal
        # outreach state is also converted.
        session.execute(
            sa.update(CampaignRecipient)
            .where(
                CampaignRecipient.contact_id == conv.contact_id,
                CampaignRecipient.outreach_state.is_not(None),
                CampaignRecipient.outreach_state.notin_(
                    [s.value for s in OUTREACH_TERMINAL_STATES]
                ),
            )
            .values(outreach_state=OutreachState.CONVERTED.value)
        )

        session.commit()


def _auto_apply_delivery_tag_sync(
    session, conversation_id: uuid.UUID, tag_name: str
) -> None:
    """Auto-apply a delivery-derived tag to the conversation's contact (§6).

    No suggestion row — delivery-derived tags are system-applied.
    """
    from app.modules.conversations.models import Conversation

    conv = session.get(Conversation, conversation_id)
    if conv is None:
        return

    tag_stmt = (
        pg_insert(Tag)
        .values(name=tag_name)
        .on_conflict_do_nothing(index_elements=["name"])
    )
    session.execute(tag_stmt)
    session.flush()

    tag = session.execute(
        select(Tag).where(Tag.name == tag_name)
    ).scalar_one()
    session.execute(
        pg_insert(ContactTag)
        .values(contact_id=conv.contact_id, tag_id=tag.id)
        .on_conflict_do_nothing(constraint="pk_contact_tags")
    )


def _apply_opt_out_tag_sync(session, contact_id: uuid.UUID) -> None:
    """Auto-apply the DO_NOT_CONTACT tag without a suggestion row (§6)."""
    tag_stmt = (
        pg_insert(Tag)
        .values(name="DO_NOT_CONTACT")
        .on_conflict_do_nothing(index_elements=["name"])
    )
    session.execute(tag_stmt)
    session.flush()

    tag = session.execute(
        select(Tag).where(Tag.name == "DO_NOT_CONTACT")
    ).scalar_one()
    session.execute(
        pg_insert(ContactTag)
        .values(contact_id=contact_id, tag_id=tag.id)
        .on_conflict_do_nothing(constraint="pk_contact_tags")
    )


def _attribute_inbound_to_campaigns(
    session,
    *,
    contact_id: uuid.UUID,
    when: datetime,
) -> None:
    """Mark any campaign_recipient rows for this contact (sent within the
    attribution window) as `responded=True`, and bump the campaign's
    response_count. The window is 30 days — enough to capture realistic
    follow-ups without back-attributing months later.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from app.modules.campaigns.models import CampaignRecipient
    from app.modules.campaigns.repository import (
        CampaignRecipientRepository,
        CampaignRepository,
    )

    window_start = when - timedelta(days=30)
    rows = session.execute(
        select(CampaignRecipient.campaign_id).where(
            CampaignRecipient.contact_id == contact_id,
            CampaignRecipient.responded.is_(False),
            CampaignRecipient.sent_at.is_not(None),
            CampaignRecipient.sent_at >= window_start,
        )
    ).all()
    if not rows:
        return

    updated = CampaignRecipientRepository(session).mark_responded_for_contact_sync(
        contact_id, since=window_start
    )
    if not updated:
        return

    # Each campaign that had any recipient flipped gets +N to response_count
    # where N = number of distinct (campaign, contact) rows. In practice a
    # contact only has one row per campaign (UniqueConstraint), so the
    # increment per campaign is 1.
    campaign_repo = CampaignRepository(session)
    seen: set[uuid.UUID] = set()
    for (cid,) in rows:
        if cid in seen:
            continue
        seen.add(cid)
        campaign_repo.increment_counters_sync(cid, response_delta=1)


def _maybe_schedule_delivery_retry(
    session,
    message_id: uuid.UUID,
    delivery_retry_count: int,
) -> None:
    """Schedule a delivery-failure retry if the setting is enabled and retries
    remain. Called from _apply_status_update after a FAILED status transition
    is committed.
    """
    if delivery_retry_count >= MAX_DELIVERY_RETRIES:
        return

    from app.modules.settings.constants import SETTING_OPS_DELIVERY_FAILURE_RETRY
    from app.modules.settings.repository import get_bool_setting_sync

    try:
        enabled = get_bool_setting_sync(
            session, SETTING_OPS_DELIVERY_FAILURE_RETRY, default=True
        )
    except Exception:
        logger.warning(
            "delivery_retry_setting_read_failed",
            message_id=str(message_id),
            exc_info=True,
        )
        return

    if not enabled:
        return

    countdown = DELIVERY_FAILURE_RETRY_DELAYS[delivery_retry_count]
    reset_and_retry_message_task.apply_async(
        args=(str(message_id), delivery_retry_count),
        countdown=countdown,
    )
    logger.info(
        "delivery_retry_scheduled",
        message_id=str(message_id),
        attempt=delivery_retry_count + 1,
        countdown_seconds=countdown,
    )


def _apply_status_update(
    meta_msg_id: str,
    new_status_str: str,
    raw_update: dict[str, Any],
) -> None:
    """
    Apply a Meta delivery status callback to the corresponding message row.

    Terminal states (READ, FAILED) are protected: a stale callback cannot
    downgrade a READ message back to FAILED or SENT.
    """
    status_map = {
        "sent": MessageDeliveryStatus.SENT,
        "delivered": MessageDeliveryStatus.DELIVERED,
        "read": MessageDeliveryStatus.READ,
        "failed": MessageDeliveryStatus.FAILED,
    }
    new_status = status_map.get(new_status_str.lower())
    if new_status is None:
        logger.warning(
            "status_update_unknown_status",
            meta_message_id=meta_msg_id,
            raw_status=new_status_str,
        )
        return

    with sync_session_factory() as session:
        msg_repo = MessageRepository(session)  # type: ignore[arg-type]
        existing = msg_repo.get_by_meta_id_sync(meta_msg_id)

        if existing is None:
            logger.warning(
                "status_update_message_not_found",
                meta_message_id=meta_msg_id,
            )
            return

        # Delivery status is monotonic: a stale or out-of-order Meta
        # callback must never regress a message to a weaker state (e.g.
        # `sent` arriving after `delivered`, or `failed` after `delivered`).
        # Only apply an update that strictly advances the status rank.
        if (
            _DELIVERY_RANK.get(new_status.value, -1)
            <= _DELIVERY_RANK.get(str(existing.delivery_status), -1)
        ):
            return

        error_text: str | None = None
        error_code: int | None = None
        if new_status == MessageDeliveryStatus.FAILED:
            errors = raw_update.get("errors", [])
            if errors:
                error_text = json.dumps(errors[0])
                raw_code = errors[0].get("code")
                try:
                    error_code = int(raw_code) if raw_code is not None else None
                except (TypeError, ValueError):
                    error_code = None

        msg_repo.update_delivery_status_sync(
            message_id=existing.id,
            new_status=new_status,
            last_error=error_text,
            error_code=error_code,
        )

        # Campaign linkage: if this message is part of a campaign, flow the
        # delivery state change into campaign_recipients + counters.
        _propagate_to_campaign_recipient(
            session,
            meta_message_id=meta_msg_id,
            new_status=new_status,
            error_code=error_code,
            error_message=error_text,
        )

        # Engagement policy §3: classify permanent vs transient delivery
        # failures. Permanent failures → terminal UNDELIVERABLE + auto-tag.
        # DELIVERED → auto-apply NEEDS_FOLLOW_UP tag.
        if new_status == MessageDeliveryStatus.FAILED:
            from app.modules.engagement.constants import (
                is_permanent_failure,
                tag_for_failure_code,
            )

            if is_permanent_failure(error_code):
                _auto_apply_delivery_tag_sync(
                    session,
                    existing.conversation_id,
                    tag_for_failure_code(error_code) or "UNDELIVERABLE",
                )
                from app.modules.conversations.repository import (
                    ConversationRepository,
                )

                ConversationRepository(session).update_outreach_state_sync(  # type: ignore[arg-type]
                    existing.conversation_id,
                    "UNDELIVERABLE",
                )
        elif new_status in (MessageDeliveryStatus.DELIVERED, MessageDeliveryStatus.READ):
            if getattr(existing, "direction", None) == MessageDirection.OUTBOUND.value:
                _auto_apply_delivery_tag_sync(
                    session, existing.conversation_id, "NEEDS_FOLLOW_UP"
                )

        # Capture before commit — expire_on_commit would otherwise expire
        # the ORM attributes after session.commit().
        _msg_id = existing.id
        _delivery_retry_count = existing.delivery_retry_count

        session.commit()

        # Schedule a delivery-failure retry if this status update was a
        # FAILED transition and the feature is enabled. Done AFTER commit
        # inside the with block — session must still be open for the
        # get_bool_setting_sync call inside _maybe_schedule_delivery_retry.
        # Permanent failures are excluded — no point retrying.
        if new_status == MessageDeliveryStatus.FAILED:
            from app.modules.engagement.constants import is_permanent_failure

            if not is_permanent_failure(error_code):
                _maybe_schedule_delivery_retry(
                    session, _msg_id, _delivery_retry_count
                )


def _propagate_to_campaign_recipient(
    session,
    *,
    meta_message_id: str,
    new_status: MessageDeliveryStatus,
    error_code: int | None = None,
    error_message: str | None = None,
) -> None:
    """Translate a Meta delivery-status update into the campaign_recipient
    side of the world. No-op if the message isn't linked to a campaign.
    """
    from app.modules.campaigns.constants import CampaignRecipientStatus
    from app.modules.campaigns.repository import (
        CampaignRecipientRepository,
        CampaignRepository,
    )

    if new_status == MessageDeliveryStatus.DELIVERED:
        recipient_status = CampaignRecipientStatus.DELIVERED.value
        delivered_delta, failed_delta = 1, 0
    elif new_status == MessageDeliveryStatus.FAILED:
        recipient_status = CampaignRecipientStatus.FAILED.value
        delivered_delta, failed_delta = 0, 1
    else:
        # READ / SENT do not change campaign_recipient status (recipient was
        # marked SENT at outbound dispatch time; READ is per-message only).
        return

    recipient_repo = CampaignRecipientRepository(session)
    recipient = recipient_repo.update_delivery_status_sync(
        meta_message_id=meta_message_id,
        new_status=recipient_status,
        error_code=error_code,
        error_message=error_message,
    )
    if recipient is not None:
        CampaignRepository(session).increment_counters_sync(
            recipient.campaign_id,
            delivered_delta=delivered_delta,
            failed_delta=failed_delta,
        )


# -------------------------------------------------------- outbound dispatch

@celery_app.task(
    name="messaging.tasks.send_outbound_message",
    bind=True,
    max_retries=_MAX_RETRIES,
    acks_late=True,
)
def send_outbound_message_task(self: Task, message_id: str) -> None:
    """
    Dispatch a queued outbound message via the Meta Send API.

    Retry schedule (DSD §4.1):
      Attempt 1: immediate
      Attempt 2: 30 seconds
      Attempt 3: 2 minutes
      Attempt 4: 10 minutes

    After all retries exhausted: mark message as FAILED.
    """
    from app.core.exceptions import MetaAPIError
    from app.integrations.meta.client import MetaWhatsAppClient as MetaClient

    # DSD §11: Redis down → pause outbound dispatch. Probe BEFORE any work
    # so the reschedule is fully idempotent (no Meta call, no DB write yet).
    # We do NOT mark the message FAILED and we do NOT touch the Meta-send
    # retry budget — see _REDIS_DOWN_* rationale above.
    if not redis_healthy():
        logger.warning("outbound_dispatch_paused_redis_down", message_id=message_id)
        raise self.retry(
            countdown=_REDIS_DOWN_RETRY_SECONDS,
            max_retries=_REDIS_DOWN_MAX_RETRIES,
            exc=RuntimeError("redis_unavailable_outbound_paused"),
        )

    msg_uuid = uuid.UUID(message_id)

    with sync_session_factory() as session:
        msg_repo = MessageRepository(session)  # type: ignore[arg-type]
        message = msg_repo.get_sync(msg_uuid)

        if message is None:
            logger.error(
                "send_outbound_message_not_found",
                message_id=message_id,
            )
            return

        if message.delivery_status != MessageDeliveryStatus.QUEUED:
            logger.info(
                "send_outbound_message_skipped_non_queued",
                message_id=message_id,
                current_status=str(message.delivery_status),
            )
            return

        # Capture before any commit (expire_on_commit would otherwise force a
        # re-query). Needed post-commit for the inbox reorder + event fan-out.
        conv_id = message.conversation_id

        try:
            # M6: context-manage the pooled client so its connection is
            # closed when the task finishes (sync analogue of the
            # asyncio.run/aclose discipline — architectural invariant #12).
            with MetaClient() as client:
                phone = message.conversation.contact.phone

                # Check for attached media.
                media_assets = getattr(message, "media", None) or []
                if media_assets:
                    media_asset = media_assets[0]
                    if not _ensure_media_file_on_disk(media_asset):
                        raise MetaAPIError(
                            "meta_media_file_missing",
                            details={
                                "retryable": False,
                                "file_path": media_asset.file_path,
                                "reason": "file not on disk and no file_data in DB",
                            },
                        )
                    media_path = _resolve_media_path(media_asset.file_path)

                    # Voice notes: convert WAV → Ogg before upload.
                    if media_asset.media_type == "audio":
                        from app.modules.media.service import MediaService

                        media_svc = MediaService.__new__(MediaService)
                        ogg_rel = media_svc.convert_to_ogg(media_asset.file_path)
                        media_path = _resolve_media_path(ogg_rel)
                        # Update the mime_type for Meta
                        meta_media_type = "audio/ogg; codecs=opus"
                    else:
                        meta_media_type = media_asset.mime_type or "application/octet-stream"

                    meta_media_id = client.upload_media(
                        file_path=str(media_path),
                        mime_type=meta_media_type,
                    )

                    # Persist the Meta media ID.
                    from sqlalchemy import update as sa_update

                    from app.modules.media.models import MediaAsset

                    session.execute(
                        sa_update(MediaAsset)
                        .where(MediaAsset.message_id == msg_uuid)
                        .values(meta_media_id=meta_media_id)
                    )

                    meta_response = client.send_media(
                        to=phone,
                        media_type=media_asset.media_type,
                        media_id_or_url=meta_media_id,
                        caption=message.content if message.content else None,
                    )
                elif getattr(message, "msg_type", "text") == "contact":
                    # Contact card: parse "Name — phone1, phone2" format.
                    name_part, _, phones_part = message.content.partition(" — ")
                    contact_name = name_part.strip() or "Contact"
                    phones = [p.strip() for p in phones_part.split(",") if p.strip()]
                    if not phones:
                        phones = [phone]
                    meta_response = client.send_contact(
                        to=phone,
                        contact_name=contact_name,
                        contact_phones=phones,
                    )
                elif message.template_name:
                    language = message.template_language or "en"
                    logger.info(
                        "outbound_template_send",
                        message_id=message_id,
                        to=phone,
                        template_name=message.template_name,
                        language=language,
                        sender_type=message.sender_type,
                    )
                    meta_response = client.send_template(
                        to=phone,
                        template_name=message.template_name,
                        language=language,
                    )
                else:
                    meta_response = client.send_text(
                        to=phone,
                        body=message.content,
                    )
            meta_msg_id = meta_response.get("messages", [{}])[0].get("id")

            msg_repo.update_delivery_status_sync(
                message_id=msg_uuid,
                new_status=MessageDeliveryStatus.SENT,
                last_error=None,
                meta_message_id=meta_msg_id,
            )
            _backfill_campaign_recipient_meta_id(
                session, message_id=msg_uuid, meta_message_id=meta_msg_id
            )

            # Contact pipeline: mark as contacted + record the outbound timestamp.
            contact = message.conversation.contact
            contact_repo = ContactRepository(session)  # type: ignore[arg-type]
            if contact and contact.status in (
                ContactStatus.ACTIVE.value,
                ContactStatus.FOLLOW_UP.value,
                ContactStatus.NOT_INTERESTED.value,
            ):
                contact_repo.transition_status_sync(
                    contact.id, ContactStatus.CONTACTED.value
                )
            contact_repo.touch_last_contacted_sync(contact.id)

            session.commit()

            logger.info(
                "outbound_message_sent",
                message_id=message_id,
                meta_message_id=meta_msg_id,
            )

            # WhatsApp-style reorder: bump the conversation's last_message_at so
            # the inbox (ordered last_message_at DESC) floats it to the top, then
            # notify live clients so every connected inbox re-fetches. Done in a
            # fresh UoW after the SENT status is already durable; both steps are
            # best-effort and must never fail the (already successful) send.
            try:
                from app.modules.conversations.repository import ConversationRepository  # lazy — cross-module

                conv_repo = ConversationRepository(session)  # type: ignore[arg-type]
                conv_repo.touch_last_message_sync(conv_id, datetime.now(UTC))
                session.commit()
            except Exception:
                session.rollback()
                logger.warning(
                    "outbound_touch_last_message_failed",
                    message_id=message_id,
                    exc_info=True,
                )

            # Emitted post-commit so subscribers never observe a not-yet-durable
            # state. The "message." prefix is relayed to the inbox pub/sub
            # channel (see app/core/events.py).
            from app.core.events import MessageEvents, emit_event

            emit_event(
                MessageEvents.SENT,
                conversation_id=str(conv_id),
                message_id=message_id,
            )

        except MetaAPIError as exc:
            attempt = self.request.retries  # 0-indexed
            _handle_send_failure(
                session=session,
                msg_repo=msg_repo,
                message_id=msg_uuid,
                exc=exc,
                task=self,
                attempt=attempt,
                retryable=(exc.details or {}).get("retryable", True),
            )


@celery_app.task(
    name="messaging.tasks.request_meta_deletion",
    bind=True,
    max_retries=3,
    acks_late=True,
)
def request_meta_deletion_task(self: Task, message_id: str) -> None:
    """Request Meta to delete a message for everyone.

    Meta limits "delete for everyone" to messages sent within ~1 hour.
    If the message has no meta_message_id (never sent), skip. If Meta
    rejects (4xx), treat as terminal — the message can't be deleted
    remotely but the local soft-delete still stands.
    """
    from app.core.exceptions import MetaAPIError
    from app.integrations.meta.client import MetaWhatsAppClient

    msg_uuid = uuid.UUID(message_id)

    with sync_session_factory() as session:
        msg_repo = MessageRepository(session)  # type: ignore[arg-type]
        message = msg_repo.get_sync(msg_uuid)

        if message is None:
            logger.warning("meta_deletion_message_not_found", message_id=message_id)
            return

        if not message.meta_message_id:
            logger.info(
                "meta_deletion_no_meta_id",
                message_id=message_id,
                reason="Message was never delivered to Meta",
            )
            return

        try:
            with MetaWhatsAppClient() as client:
                client.delete_message(meta_message_id=message.meta_message_id)

            logger.info(
                "meta_deletion_succeeded",
                message_id=message_id,
                meta_message_id=message.meta_message_id,
            )
        except MetaAPIError as exc:
            if (exc.details or {}).get("retryable"):
                attempt = self.request.retries
                if attempt < 3:
                    delay = [30, 120, 300][attempt]
                    logger.warning(
                        "meta_deletion_retry",
                        message_id=message_id,
                        attempt=attempt,
                        delay_seconds=delay,
                    )
                    raise self.retry(exc=exc, countdown=delay) from exc
            # Non-retryable or max retries — log and stop.
            logger.error(
                "meta_deletion_failed",
                message_id=message_id,
                error=str(exc),
                exc_info=True,
            )


def _handle_send_failure(
    session,
    msg_repo: MessageRepository,
    message_id: uuid.UUID,
    exc: Exception,
    task: Task,
    attempt: int,
    retryable: bool,
) -> None:
    """
    Handle a send failure by either scheduling a retry or marking the
    message as permanently FAILED.
    """
    next_attempt = attempt + 1

    # Msg-I4 fix: only increment retry_count for retryable errors.
    # Non-retryable errors go straight to terminal failure without
    # skewing the retry_count analytics column.
    if retryable:
        msg_repo.increment_retry_sync(message_id)
        session.commit()

    if not retryable or next_attempt > _MAX_RETRIES:
        # Terminal failure.
        error_code, error_msg = _parse_meta_error(exc)
        msg_repo.update_delivery_status_sync(
            message_id=message_id,
            new_status=MessageDeliveryStatus.FAILED,
            last_error=error_msg,
            error_code=error_code,
        )
        session.commit()
        logger.error(
            "outbound_message_terminal_failure",
            message_id=str(message_id),
            attempt=attempt,
            retryable=retryable,
            error=str(exc),
        )
        return

    delay = _RETRY_DELAYS[next_attempt] if next_attempt < len(_RETRY_DELAYS) else 600
    logger.warning(
        "outbound_message_retry_scheduled",
        message_id=str(message_id),
        attempt=next_attempt,
        delay_seconds=delay,
        error=str(exc),
    )
    raise task.retry(exc=exc, countdown=delay)


def _backfill_campaign_recipient_meta_id(
    session,
    *,
    message_id: uuid.UUID,
    meta_message_id: str | None,
) -> None:
    """After a successful Meta send, copy the assigned meta_message_id onto
    the campaign_recipient so subsequent delivery-status webhooks can find it.
    No-op for messages that are not part of a campaign.
    """
    if not meta_message_id:
        return
    from sqlalchemy import update as sa_update

    from app.modules.campaigns.models import CampaignRecipient

    session.execute(
        sa_update(CampaignRecipient)
        .where(CampaignRecipient.message_id == message_id)
        .values(meta_message_id=meta_message_id)
    )


# ------------------------------------------------------------------- helpers


def _parse_meta_error(exc: Exception) -> tuple[int | None, str]:
    """Extract a (code, message) pair from a MetaAPIError's HTTP response body.

    Meta error JSON shape (send-API and webhook are similar)::

        {"error": {"code": 190, "error_subcode": 131026,
                   "error_user_msg": "Unable to deliver",
                   "error_data": {"details": "…"}}}

    Prefers ``error_subcode`` (the WhatsApp-specific code) over ``code`` (the
    Facebook Graph API code), and ``error_user_msg`` over
    ``error_data.details``.  Returns (None, str(exc)) when the body can't be
    parsed.
    """
    from app.core.exceptions import MetaAPIError

    if not isinstance(exc, MetaAPIError):
        return None, str(exc)

    body = (exc.details or {}).get("body", "")
    try:
        parsed = json.loads(body) if isinstance(body, str) else body
    except (json.JSONDecodeError, TypeError):
        return None, str(exc) if str(exc) != exc.code else (exc.details or {}).get("body", str(exc))

    if not isinstance(parsed, dict):
        return None, str(exc) if str(exc) != exc.code else body

    error_blob = parsed.get("error", parsed)
    if not isinstance(error_blob, dict):
        return None, str(exc) if str(exc) != exc.code else body

    error_code = error_blob.get("error_subcode") or error_blob.get("code")
    try:
        error_code = int(error_code) if error_code is not None else None
    except (TypeError, ValueError):
        error_code = None

    error_msg = (
        error_blob.get("error_user_msg")
        or (error_blob.get("error_data") or {}).get("details")
        or error_blob.get("message")
        or error_blob.get("type")
        or str(exc)
    )
    return error_code, str(error_msg)


def prefetch_inbound_media(payload: dict[str, Any]) -> None:
    """Download media files for every media message in the payload and store
    them on the local filesystem so the API process can serve them.

    Called from the webhook handler (API process) BEFORE the payload is
    dispatched to the Celery worker. The worker sees ``_media_local`` on
    each message dict and skips its own download, only creating DB rows.

    Best-effort: failures are logged and ``_media_local`` is left unset;
    the worker will attempt its own download as a fallback.
    """
    from app.integrations.meta.client import MetaWhatsAppClient as MetaClient
    from app.modules.media.service import MEDIA_ROOT

    _media_keys = ("image", "audio", "video", "document")

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                media_id = None
                media_type = None
                for key in _media_keys:
                    blob = msg.get(key)
                    if blob and blob.get("id"):
                        media_id = blob["id"]
                        media_type = key
                        break
                if not media_id or not media_type:
                    continue

                try:
                    with MetaClient() as client:
                        data, mime = client.download_media(media_id=media_id)

                    ext = _media_ext_for(mime)
                    asset_id = uuid.uuid4()
                    rel_path = f"{media_type}/{asset_id}{ext}"

                    abs_path = MEDIA_ROOT / rel_path
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    abs_path.write_bytes(data)

                    msg["_media_local"] = {
                        "asset_id": str(asset_id),
                        "file_path": rel_path,
                        "mime_type": mime,
                        "file_size_bytes": len(data),
                    }
                except Exception:
                    logger.warning(
                        "inbound_media_prefetch_failed",
                        media_id=media_id,
                        exc_info=True,
                    )
                    continue

                logger.info(
                    "inbound_media_prefetched",
                    media_id=media_id,
                    asset_id=str(asset_id),
                    msg_type=media_type,
                    size_bytes=len(data),
                )


def _resolve_media_path(rel_path: str):
    """Resolve a media file relative path to an absolute filesystem path."""
    from app.modules.media.service import MEDIA_ROOT

    return MEDIA_ROOT / rel_path


def _ensure_media_file_on_disk(media_asset) -> bool:
    """Write the media file from DB bytes if missing from the local filesystem.

    The API and worker containers may not share a volume for /app/media.
    When the file isn't on disk, reconstruct it from the file_data column
    so MetaClient.upload_media() can read it.

    Returns True if the file exists (or was just written). Returns False
    if there is no file_data to fall back to (pre-migration row) and the
    file is genuinely missing.
    """
    from app.modules.media.service import MEDIA_ROOT

    abs_path = MEDIA_ROOT / media_asset.file_path
    if abs_path.exists():
        return True

    if not media_asset.file_data:
        return False

    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(media_asset.file_data)
    logger.info(
        "media_reconstructed_from_db",
        asset_id=str(media_asset.id),
        path=media_asset.file_path,
    )
    return True


def _extract_text_content(msg: dict[str, Any]) -> str | None:
    """Extract text body from a Meta message payload. For media types, returns
    the caption (if present) or a '[type]' placeholder."""
    msg_type = msg.get("type")
    if msg_type == "text":
        return msg.get("text", {}).get("body")
    # Media types may have a caption.
    if msg_type in ("image", "video", "audio", "document"):
        caption = (msg.get(msg_type) or {}).get("caption")
        return caption if caption else f"[{msg_type}]"
    if msg_type == "contacts":
        contacts_list = msg.get("contacts") or []
        if contacts_list and isinstance(contacts_list[0], dict):
            c = contacts_list[0]
            name = (c.get("name") or {}).get("formatted_name") or \
                   (c.get("name") or {}).get("first_name") or "Unknown"
            phones = [p.get("phone") for p in (c.get("phones") or []) if p.get("phone")]
            phone_str = ", ".join(phones) if phones else "No phone"
            return f"{name} — {phone_str}"
        return "[contact]"
    if msg_type == "button":
        return msg.get("button", {}).get("text")
    if msg_type == "interactive":
        interactive = msg.get("interactive", {})
        button_reply = interactive.get("button_reply", {})
        if button_reply:
            return button_reply.get("title")
        list_reply = interactive.get("list_reply", {})
        if list_reply:
            return list_reply.get("title")
    if msg_type == "reaction":
        return (msg.get("reaction") or {}).get("emoji") or "❤️"
    return f"[{msg_type}]" if msg_type else None


def _classify_msg_type(msg: dict[str, Any]) -> str:
    """Map a Meta message type to our internal msg_type discriminator."""
    meta_type = msg.get("type", "text")
    if meta_type in ("image", "video", "audio", "document"):
        return meta_type
    if meta_type == "contacts":
        return "contact"
    if meta_type == "reaction":
        return "text"
    return "text"


def _download_and_store_media(
    session,
    *,
    media_id: str,
    msg_type: str,
    message_id: uuid.UUID,
    msg: dict[str, Any],
) -> None:
    """Persist a MediaAsset row for an inbound media message.

    If the message dict carries ``_media_local`` (set by the webhook handler's
    ``prefetch_inbound_media``, which runs on the API process), the file is
    already on disk — just create the DB row. Otherwise download from Meta
    as a fallback (legacy path, stores to the worker's filesystem).
    """
    from app.modules.media.models import MediaAsset

    prefetched: dict[str, Any] | None = msg.pop("_media_local", None)
    if prefetched is not None:
        asset = MediaAsset(
            id=uuid.UUID(prefetched["asset_id"]),
            message_id=message_id,
            media_type=msg_type,
            file_path=prefetched["file_path"],
            mime_type=prefetched["mime_type"],
            file_size_bytes=prefetched["file_size_bytes"],
        )
        session.add(asset)
        session.flush()
        logger.info(
            "inbound_media_stored",
            media_id=media_id,
            asset_id=prefetched["asset_id"],
            msg_type=msg_type,
            size_bytes=prefetched["file_size_bytes"],
        )
        return

    # Fallback: download from Meta (worker process — file lands on worker disk).
    from app.integrations.meta.client import MetaWhatsAppClient as MetaClient

    try:
        with MetaClient() as client:
            data, mime = client.download_media(media_id=media_id)

        ext = _media_ext_for(mime)
        asset_id = uuid.uuid4()
        rel_path = f"{msg_type}/{asset_id}{ext}"

        abs_path = _resolve_media_path(rel_path)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(data)

        asset = MediaAsset(
            id=asset_id,
            message_id=message_id,
            media_type=msg_type,
            file_path=rel_path,
            mime_type=mime,
            file_size_bytes=len(data),
        )
        session.add(asset)
        session.flush()

        logger.info(
            "inbound_media_stored",
            media_id=media_id,
            asset_id=str(asset_id),
            msg_type=msg_type,
            size_bytes=len(data),
        )
    except Exception:
        logger.warning(
            "inbound_media_download_failed",
            media_id=media_id,
            msg_type=msg_type,
            exc_info=True,
        )


def _media_ext_for(mime_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "audio/ogg": ".ogg",
        "audio/opus": ".opus",
        "audio/mp4": ".m4a",
        "audio/aac": ".aac",
        "audio/mpeg": ".mp3",
        "audio/webm": ".webm",
    }.get(mime_type, ".bin")
