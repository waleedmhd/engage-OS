"""Market Celery tasks — classification, expiry sweep (DSD §4, §6.3)."""

from __future__ import annotations

import uuid

from app.celery_app import celery_app
from app.db.session import sync_session_factory
from app.modules.market.service import MarketClassificationService


@celery_app.task(
    name="market.tasks.classify_message_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def classify_message_task(
    self,
    message_id: str,
) -> dict:
    """LLM fallback classification for a market message.

    Dispatched after keyword+alias classification if no products were matched
    or side is UNKNOWN. Uses Haiku via the sync classification service.
    """
    try:
        mid = uuid.UUID(message_id)
    except ValueError:
        return {"action": "noop", "reason": "invalid_message_id"}

    with sync_session_factory() as session:
        MarketClassificationService.classify_with_llm_sync(session, mid)
        session.commit()

    return {"action": "classified", "message_id": message_id}


@celery_app.task(
    name="market.tasks.backfill_extracted_attributes_task",
    bind=True,
    max_retries=2,
    acks_late=True,
)
def backfill_extracted_attributes_task(self, batch_size: int = 200) -> dict:
    """One-shot backfill: run Python extractor on messages without extracted_attributes.

    Safe to run multiple times — skips already-populated rows.
    Dispatched manually (not on beat). Can be limited with a MAX_ROWS env var
    for incremental backfill across multiple runs.
    """
    import logging
    from datetime import UTC, datetime

    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import JSONB

    from app.core.config import get_settings
    from app.modules.market.extractor import extract_attributes, extract_intent
    from app.modules.market.models import MarketMessage

    logger = logging.getLogger(__name__)
    settings = get_settings()
    max_rows = getattr(settings, "MARKET_BACKFILL_MAX_ROWS", None)
    processed = 0

    with sync_session_factory() as session:
        try:
            while True:
                if max_rows and processed >= max_rows:
                    break

                # JSONB(none_as_null=False) stores Python None as JSON 'null',
                # not SQL NULL, so check both forms.
                rows = session.execute(
                    sa.select(MarketMessage)
                    .where(
                        sa.or_(
                            MarketMessage.extracted_attributes.is_(None),
                            MarketMessage.extracted_attributes
                            == sa.type_coerce("null", JSONB),
                        )
                    )
                    .order_by(MarketMessage.captured_at.asc())
                    .limit(batch_size)
                ).scalars().all()

                if not rows:
                    break

                for msg in rows:
                    try:
                        intent = extract_intent(msg.raw_text)
                        attrs = extract_attributes(msg.raw_text)
                        msg.extracted_attributes = {
                            "intent": intent,
                            "attributes": attrs,
                            "backfilled_at": datetime.now(tz=UTC).isoformat(),
                        }
                    except Exception:
                        msg.extracted_attributes = {"error": "extraction_failed"}

                session.commit()
                processed += len(rows)
                logger.info("Backfill batch: %d messages processed", processed)
        finally:
            session.close()

    return {"backfilled": processed}


@celery_app.task(
    name="market.tasks.expire_market_messages_task",
    bind=True,
    acks_late=True,
)
def expire_market_messages_task(self) -> dict:
    """Periodic sweep: set ACTIVE messages past TTL to EXPIRED (DSD §6.3).

    BUY messages expire ~45 min after capture; SELL messages expire after
    ~48 hours. This task runs every 5 minutes via Celery beat.
    """
    from app.modules.market.constants import BUY_EXPIRY_MINUTES, SELL_EXPIRY_HOURS
    from app.modules.market.repository import MarketMessageRepository

    with sync_session_factory() as session:
        repo = MarketMessageRepository(session)  # type: ignore[arg-type]
        counts = repo.expire_stale_sync(
            buy_minutes=BUY_EXPIRY_MINUTES,
            sell_hours=SELL_EXPIRY_HOURS,
        )
        session.commit()

    return {
        "action": "expired",
        "expired": counts["expired"],
        "unreviewed_expired": counts["unreviewed_expired"],
        "count": counts["expired"] + counts["unreviewed_expired"],
    }
