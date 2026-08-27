"""Analytics Celery tasks (Phase 6).

* ``aggregate_daily_metrics_task`` — fires daily from beat at 00:15 UTC.
  Computes "yesterday" by default; accepts ``target_date_iso`` for ad-hoc
  re-runs. No ``self.retry()``: the next beat tick is the retry path.

* ``backfill_daily_metrics_task`` — iterates a date range and calls the
  same aggregator helpers. Triggered from the admin backfill endpoint.

Both tasks own their own transaction (Msg-C4: task is the outermost tx
owner) and call ``session.commit()`` once at the end.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import structlog

from app.celery_app import celery_app
from app.db.session import sync_session_factory
from app.modules.analytics.aggregator import (
    upsert_campaign_daily,
    upsert_global_daily,
    upsert_hourly_metrics,
    upsert_template_daily,
)

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="analytics.tasks.aggregate_daily_metrics_task",
    bind=True,
    acks_late=True,
)
def aggregate_daily_metrics_task(self, target_date_iso: str | None = None) -> dict:
    """Roll up one calendar day into the analytics rollup tables.

    ``target_date_iso`` defaults to yesterday (UTC). Re-running for the
    same date is safe — the underlying SQL is ON CONFLICT DO UPDATE.
    """
    target = (
        date.fromisoformat(target_date_iso)
        if target_date_iso
        else (datetime.now(UTC).date() - timedelta(days=1))
    )
    with sync_session_factory() as session:
        upsert_global_daily(session, target)
        campaigns_touched = upsert_campaign_daily(session, target)
        templates_touched = upsert_template_daily(session, target)
        hours_touched = upsert_hourly_metrics(session, target)
        session.commit()

    logger.info(
        "analytics_aggregate_daily_completed",
        target_date=target.isoformat(),
        campaigns=campaigns_touched,
        templates=templates_touched,
        hours=hours_touched,
    )
    return {
        "target_date": target.isoformat(),
        "campaigns": campaigns_touched,
        "templates": templates_touched,
        "hours": hours_touched,
    }


@celery_app.task(name="analytics.tasks.backfill_daily_metrics_task", acks_late=True)
def backfill_daily_metrics_task(start_iso: str, end_iso: str) -> dict:
    """Re-aggregate every day in ``[start_iso, end_iso]`` inclusive.

    Iterates one day at a time, each in its own commit, so a failure
    midway leaves the earlier days persisted. Use the admin endpoint
    when source data changes after the fact (e.g., manual revenue update).
    """
    start = date.fromisoformat(start_iso)
    end = date.fromisoformat(end_iso)
    if end < start:
        raise ValueError("end_date must be >= start_date")

    days_processed = 0
    campaigns_total = 0
    templates_total = 0
    hours_total = 0
    current = start
    while current <= end:
        with sync_session_factory() as session:
            upsert_global_daily(session, current)
            campaigns_total += upsert_campaign_daily(session, current)
            templates_total += upsert_template_daily(session, current)
            hours_total += upsert_hourly_metrics(session, current)
            session.commit()
        days_processed += 1
        current += timedelta(days=1)

    logger.info(
        "analytics_backfill_completed",
        start=start_iso,
        end=end_iso,
        days=days_processed,
        campaigns=campaigns_total,
        templates=templates_total,
        hours=hours_total,
    )
    return {
        "start_date": start_iso,
        "end_date": end_iso,
        "days": days_processed,
        "campaigns": campaigns_total,
        "templates": templates_total,
        "hours": hours_total,
    }
