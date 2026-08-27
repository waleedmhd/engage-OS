"""Campaign Celery tasks (DSD §4.7).

All tasks are sync and route to QUEUE_OUTBOUND (configured in workers/queues.py).

Lifecycle:

  dispatch_campaign_task        — entry point. QUEUED → DISPATCHING; fans out batches.
  process_campaign_batch_task   — sends a batch of recipients respecting throttle.
  complete_campaign_task        — polls progress, transitions DISPATCHING → COMPLETED.
  scheduler_tick_task           — beat-driven; finds due SCHEDULED/RECURRING campaigns.

Pattern follows messaging Msg-C4: persist + commit, then dispatch downstream
task. Retries on the throttle bucket use Celery's countdown.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from celery import Task

from app.celery_app import celery_app
from app.core.redis import get_sync_redis, redis_healthy
from app.db.session import sync_session_factory
from app.modules.audit.constants import ActorType
from app.modules.audit.models import AuditLog
from app.modules.campaigns.constants import (
    CAMPAIGN_BATCH_SIZE,
    CAMPAIGN_COMPLETION_POLL_SECONDS,
    CAMPAIGN_DEFAULT_RATE_PER_SEC,
    CAMPAIGN_LOCK_REDIS_KEY,
    CAMPAIGN_LOCK_TTL_SECONDS,
    CAMPAIGN_THROTTLE_KEY_TTL,
    CAMPAIGN_THROTTLE_REDIS_KEY,
    SETTING_CAMPAIGN_RATE_PER_SEC,
    CampaignRecipientStatus,
    CampaignStatus,
    CampaignType,
)
from app.modules.campaigns.repository import (
    CampaignRecipientRepository,
    CampaignRepository,
)
from app.modules.conversations.repository import ConversationRepository
from app.modules.messaging.constants import (
    MessageDeliveryStatus,
    MessageDirection,
    SenderType,
)
from app.modules.messaging.models import Message
from app.modules.settings.operational import (
    daily_counter_key,
    is_within_business_hours,
    read_operational_config_sync,
    seconds_until_local_midnight,
    seconds_until_window_open,
)

logger = structlog.get_logger(__name__)


# Daily-cap counter key TTL: long enough to survive a clock day in any tz
# (max UTC offset 14h) plus slack, short enough to self-clean.
_DAILY_CAP_KEY_TTL_SECONDS = 48 * 3600

# ----------------------------------------------------------- helper functions

def _resolve_rate_per_second(session, campaign) -> int:
    """Per-campaign override > AppSetting > built-in default."""
    if campaign.rate_limit_per_second:
        return int(campaign.rate_limit_per_second)
    from sqlalchemy import select

    from app.modules.settings.models import AppSetting

    row = session.execute(
        select(AppSetting).where(
            AppSetting.scope == "global",
            AppSetting.key == SETTING_CAMPAIGN_RATE_PER_SEC,
        )
    ).scalar_one_or_none()
    if row and isinstance(row.value, dict) and "rate" in row.value:
        try:
            return int(row.value["rate"])
        except (TypeError, ValueError):
            pass
    return CAMPAIGN_DEFAULT_RATE_PER_SEC


def _campaign_ops_gate(session, redis, *, now_utc: datetime | None = None):
    """Return (allowed, retry_countdown_seconds, reason).

    Business hours is checked first (broad gate), then the daily cap.
    When not allowed, retry_countdown is the seconds to defer for.

    ``session`` may be ``None``; the function will open its own short-lived
    session in that case (used by the task wiring so no session is held open
    before the gate decision).
    """
    now_utc = now_utc or datetime.now(UTC)
    if session is None:
        with sync_session_factory() as _s:
            return _campaign_ops_gate(_s, redis, now_utc=now_utc)
    cfg = read_operational_config_sync(session)

    if not is_within_business_hours(cfg, now_utc):
        return False, seconds_until_window_open(cfg, now_utc), "outside_business_hours"

    if cfg.cap.enabled:
        raw = redis.get(daily_counter_key(cfg, now_utc))
        sent = int(raw) if raw else 0
        if sent >= cfg.cap.limit:
            return (
                False,
                seconds_until_local_midnight(cfg, now_utc),
                "daily_cap_reached",
            )

    return True, None, None


def _increment_daily_cap(session, redis) -> None:
    """Count one real campaign send against today's local-tz bucket."""
    cfg = read_operational_config_sync(session)
    if not cfg.cap.enabled:
        return
    key = daily_counter_key(cfg, datetime.now(UTC))
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, _DAILY_CAP_KEY_TTL_SECONDS)
    pipe.execute()


def _claim_throttle_slot(redis, campaign_id: uuid.UUID, rate: int) -> bool:
    """Sliding 1-second token bucket. Returns True if a slot is available."""
    epoch_sec = int(time.time())
    key = CAMPAIGN_THROTTLE_REDIS_KEY.format(
        campaign_id=campaign_id, epoch_sec=epoch_sec
    )
    pipeline = redis.pipeline()
    pipeline.incr(key)
    pipeline.expire(key, CAMPAIGN_THROTTLE_KEY_TTL)
    count, _ = pipeline.execute()
    return int(count) <= rate


def _resolve_or_create_conversation_sync(session, contact_id: uuid.UUID):
    """Reuse the open conversation for a contact, or create one."""
    conv_repo = ConversationRepository(session)
    conv = conv_repo.get_active_for_contact_sync(contact_id)
    if conv is None:
        conv = conv_repo.create_for_contact_sync(contact_id=contact_id)
    return conv


def _render_template(template, contact) -> str:
    """Render template content. Phase 4 keeps the body literal — Meta-side
    placeholders are resolved by the Send API. We expose a hook here so a
    later phase can interpolate {{name}}, {{company}} etc. without changing
    the dispatch loop.
    """
    body = getattr(template, "body", None) or template.name
    if "{{name}}" in body and contact.name:
        body = body.replace("{{name}}", contact.name)
    if "{{company}}" in body and contact.company:
        body = body.replace("{{company}}", contact.company)
    return body


# ----------------------------------------------------------- dispatch (entry)

@celery_app.task(
    name="campaigns.tasks.dispatch_campaign_task",
    bind=True,
    max_retries=3,
    acks_late=True,
)
def dispatch_campaign_task(self: Task, campaign_id: str) -> None:
    """Fan out a QUEUED campaign into per-batch tasks.

    Singleflight: a Redis lock ensures only one worker runs the loop for
    a given campaign at a time. If the lock is held, exit silently — the
    holder is already doing the work.
    """
    redis = get_sync_redis()
    campaign_uuid = uuid.UUID(campaign_id)

    allowed, countdown, reason = _campaign_ops_gate(None, redis)
    if not allowed:
        logger.info(
            "campaign_dispatch_deferred",
            campaign_id=campaign_id,
            reason=reason,
            countdown=countdown,
        )
        raise self.retry(
            countdown=countdown,
            max_retries=None,
            exc=RuntimeError(f"campaign_deferred:{reason}"),
        )

    lock_key = CAMPAIGN_LOCK_REDIS_KEY.format(campaign_id=campaign_uuid)

    if not redis.set(lock_key, "1", nx=True, ex=CAMPAIGN_LOCK_TTL_SECONDS):
        logger.info("campaign_dispatch_skipped_lock_held", campaign_id=campaign_id)
        return

    try:
        with sync_session_factory() as session:
            repo = CampaignRepository(session)  # type: ignore[arg-type]
            recipient_repo = CampaignRecipientRepository(session)  # type: ignore[arg-type]
            campaign = repo.get_sync(campaign_uuid)
            if campaign is None:
                logger.error("campaign_not_found_in_dispatch", campaign_id=campaign_id)
                return

            if campaign.status not in {
                CampaignStatus.QUEUED.value,
                CampaignStatus.DISPATCHING.value,
            }:
                logger.info(
                    "campaign_dispatch_skipped_wrong_status",
                    campaign_id=campaign_id,
                    status=campaign.status,
                )
                return

            if campaign.status == CampaignStatus.QUEUED.value:
                repo.update_status_sync(
                    campaign_uuid,
                    CampaignStatus.DISPATCHING.value,
                    extra={"started_at": datetime.now(UTC)},
                )
                session.commit()

            offset = 0
            total_dispatched = 0
            while True:
                ids = recipient_repo.list_pending_ids_sync(
                    campaign_uuid, limit=CAMPAIGN_BATCH_SIZE, offset=offset
                )
                if not ids:
                    break
                process_campaign_batch_task.delay(
                    str(campaign_uuid), [str(i) for i in ids]
                )
                total_dispatched += len(ids)
                offset += CAMPAIGN_BATCH_SIZE

            logger.info(
                "campaign_dispatch_fanned_out",
                campaign_id=campaign_id,
                batches_dispatched=total_dispatched // CAMPAIGN_BATCH_SIZE
                + (1 if total_dispatched % CAMPAIGN_BATCH_SIZE else 0),
                total_recipients=total_dispatched,
            )

        # Schedule completion poll outside the session.
        complete_campaign_task.apply_async(
            args=[campaign_id], countdown=CAMPAIGN_COMPLETION_POLL_SECONDS
        )
    finally:
        redis.delete(lock_key)


# ----------------------------------------------------------------- per-batch

@celery_app.task(
    name="campaigns.tasks.process_campaign_batch_task",
    bind=True,
    max_retries=10,
    acks_late=True,
)
def process_campaign_batch_task(
    self: Task, campaign_id: str, recipient_ids: list[str]
) -> None:
    """Process a single batch of recipients respecting the per-second rate."""
    # DSD §11: Redis down → pause the batch before any send. The throttle
    # bucket lives in Redis; without it we cannot rate-limit safely. Checked
    # before the lock/throttle loop so re-running the whole batch is idempotent
    # (no recipient has been dispatched yet at this point) — no double-send.
    if not redis_healthy():
        logger.warning("campaign_batch_paused_redis_down", campaign_id=campaign_id)
        raise self.retry(
            countdown=60, exc=RuntimeError("redis_unavailable_outbound_paused")
        )

    redis = get_sync_redis()
    campaign_uuid = uuid.UUID(campaign_id)

    allowed, countdown, reason = _campaign_ops_gate(None, redis)
    if not allowed:
        logger.info(
            "campaign_batch_deferred",
            campaign_id=campaign_id,
            reason=reason,
            countdown=countdown,
        )
        raise self.retry(
            args=[campaign_id, recipient_ids],
            countdown=countdown,
            max_retries=self.max_retries,
            exc=RuntimeError(f"campaign_deferred:{reason}"),
        )

    from app.modules.messaging.tasks import send_outbound_message_task

    with sync_session_factory() as session:
        repo = CampaignRepository(session)  # type: ignore[arg-type]
        recipient_repo = CampaignRecipientRepository(session)  # type: ignore[arg-type]
        campaign = repo.get_sync(campaign_uuid)
        if campaign is None:
            logger.error("campaign_not_found_in_batch", campaign_id=campaign_id)
            return

        if campaign.status not in {
            CampaignStatus.DISPATCHING.value,
            CampaignStatus.QUEUED.value,
        }:
            logger.info(
                "campaign_batch_skipped_wrong_status",
                campaign_id=campaign_id,
                status=campaign.status,
            )
            return

        rate = _resolve_rate_per_second(session, campaign)

        # Load the template once for the whole batch and verify it was
        # submitted to Meta — otherwise every send_template call will fail
        # with "template not found".
        template = campaign.template
        if template.meta_template_id is None:
            logger.error(
                "campaign_template_not_on_meta",
                campaign_id=campaign_id,
                template_name=template.name,
                template_id=str(template.id),
            )
            for rid_str in recipient_ids:
                rid = uuid.UUID(rid_str)
                recipient_repo.mark_failed_sync(
                    rid, error="Template not submitted to Meta"
                )
            repo.increment_counters_sync(
                campaign_uuid, failed_delta=len(recipient_ids)
            )
            session.commit()
            return

        # Process recipients one at a time so the throttle is enforced
        # per-message rather than per-batch.
        remaining: list[str] = []
        sent_count = 0
        failed_count = 0
        for rid_str in recipient_ids:
            if not _claim_throttle_slot(redis, campaign_uuid, rate):
                # Bucket exhausted. Carry the rest forward via retry.
                remaining = recipient_ids[recipient_ids.index(rid_str):]
                break

            rid = uuid.UUID(rid_str)
            pair = recipient_repo.get_with_contact_sync(rid)
            if pair is None:
                continue
            recipient, contact = pair
            if recipient.status != CampaignRecipientStatus.PENDING.value:
                continue

            try:
                body = _render_template(template, contact)
                conversation = _resolve_or_create_conversation_sync(
                    session, contact.id
                )
                message = Message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.OUTBOUND.value,
                    sender_type=SenderType.SYSTEM.value,
                    content=body,
                    delivery_status=MessageDeliveryStatus.QUEUED.value,
                    template_name=template.name,
                    template_language=template.language,
                )
                session.add(message)
                session.flush()

                recipient_repo.mark_sent_sync(
                    rid,
                    message_id=message.id,
                    meta_message_id=None,  # populated by Meta send-callback
                )
                repo.increment_counters_sync(campaign_uuid, sent_delta=1)
                # Msg-C4: commit before dispatching the downstream task so
                # the worker can definitely read the message row.
                session.commit()

                send_outbound_message_task.delay(str(message.id))
                _increment_daily_cap(session, redis)
                sent_count += 1
            except Exception as exc:
                session.rollback()
                logger.exception(
                    "campaign_recipient_send_failed",
                    campaign_id=campaign_id,
                    recipient_id=rid_str,
                    error=str(exc),
                )
                with sync_session_factory() as inner:
                    CampaignRecipientRepository(inner).mark_failed_sync(  # type: ignore[arg-type]
                        rid, error=str(exc)
                    )
                    CampaignRepository(inner).increment_counters_sync(  # type: ignore[arg-type]
                        campaign_uuid, failed_delta=1
                    )
                    inner.commit()
                failed_count += 1

        logger.info(
            "campaign_batch_processed",
            campaign_id=campaign_id,
            sent=sent_count,
            failed=failed_count,
            remaining=len(remaining),
        )

    if remaining:
        # Re-queue the unprocessed tail. countdown=1 so we re-check the
        # bucket on the next epoch second.
        raise self.retry(
            args=[campaign_id, remaining],
            countdown=1,
            max_retries=self.max_retries,
        )


# --------------------------------------------------------------- completion

@celery_app.task(
    name="campaigns.tasks.complete_campaign_task",
    bind=True,
    max_retries=120,  # ≈ 60 minutes at 30s intervals
    acks_late=True,
)
def complete_campaign_task(self: Task, campaign_id: str) -> None:
    """Poll recipient progress; finalise the campaign when none are PENDING.

    For RECURRING campaigns this also re-arms next_run_at.
    """
    campaign_uuid = uuid.UUID(campaign_id)

    with sync_session_factory() as session:
        repo = CampaignRepository(session)  # type: ignore[arg-type]
        recipient_repo = CampaignRecipientRepository(session)  # type: ignore[arg-type]
        campaign = repo.get_sync(campaign_uuid)
        if campaign is None:
            logger.error("campaign_not_found_in_complete", campaign_id=campaign_id)
            return

        if campaign.status not in {
            CampaignStatus.DISPATCHING.value,
        }:
            return

        breakdown = recipient_repo.count_by_status_sync(campaign_uuid)
        pending = breakdown.get(CampaignRecipientStatus.PENDING.value, 0)
        if pending > 0:
            raise self.retry(
                args=[campaign_id],
                countdown=CAMPAIGN_COMPLETION_POLL_SECONDS,
            )

        now = datetime.now(UTC)

        failed_count = breakdown.get(CampaignRecipientStatus.FAILED.value, 0)
        if failed_count > 0:
            # Any failure marks the whole campaign as FAILED.
            # Recurring campaigns do NOT re-arm on failure so an operator
            # can investigate and decide whether to re-launch.
            repo.update_status_sync(
                campaign_uuid,
                CampaignStatus.FAILED.value,
                extra={"completed_at": now},
            )
            session.add(
                AuditLog(
                    actor_type=ActorType.SYSTEM.value,
                    action="campaign.failed",
                    entity_type="campaign",
                    entity_id=campaign_uuid,
                    after_state={
                        "status": CampaignStatus.FAILED.value,
                        "failed_count": failed_count,
                    },
                )
            )
            logger.info(
                "campaign_failed",
                campaign_id=campaign_id,
                failed_count=failed_count,
            )
        elif (
            campaign.type == CampaignType.RECURRING.value
            and campaign.cron_expression
        ):
            from croniter import croniter

            next_run = croniter(campaign.cron_expression, now).get_next(datetime)
            repo.update_status_sync(
                campaign_uuid,
                CampaignStatus.SCHEDULED.value,
                extra={
                    "completed_at": now,
                    "last_run_at": now,
                    "next_run_at": next_run,
                },
            )
            logger.info(
                "campaign_recurring_run_completed",
                campaign_id=campaign_id,
                next_run_at=next_run.isoformat(),
            )
        else:
            repo.update_status_sync(
                campaign_uuid,
                CampaignStatus.COMPLETED.value,
                extra={"completed_at": now},
            )
            logger.info("campaign_completed", campaign_id=campaign_id)
        session.commit()


# ------------------------------------------------------------ scheduler tick

@celery_app.task(
    name="campaigns.tasks.scheduler_tick_task",
    bind=True,
    acks_late=True,
)
def scheduler_tick_task(self: Task) -> None:
    """Beat-driven scan for due SCHEDULED/RECURRING campaigns."""
    with sync_session_factory() as session:
        repo = CampaignRepository(session)  # type: ignore[arg-type]
        due = repo.find_due_for_scheduler_sync(limit=200)
        for campaign in due:
            # Re-load + transition under a fresh transaction so a slow
            # campaign doesn't hold a long-running lock.
            now = datetime.now(UTC)
            extra: dict[str, Any] = {}
            if campaign.type == CampaignType.RECURRING.value:
                extra["last_run_at"] = now
            rowcount = repo.update_status_sync(
                campaign.id,
                CampaignStatus.QUEUED.value,
                extra=extra,
            )
            if rowcount:
                session.commit()
                dispatch_campaign_task.delay(str(campaign.id))
                logger.info(
                    "scheduler_tick_dispatched",
                    campaign_id=str(campaign.id),
                    type=campaign.type,
                )
            else:
                session.rollback()
