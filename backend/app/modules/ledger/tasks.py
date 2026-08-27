"""Ledger Celery tasks — periodic reminders and end-of-period checks.

All tasks own their own transaction (Msg-C4: task is the outermost tx owner)
and call ``session.commit()`` once at the end.
"""

from __future__ import annotations

from datetime import date, timedelta

import structlog

from app.celery_app import celery_app
from app.db.session import sync_session_factory
from app.modules.ledger.constants import PeriodStatus

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="ledger.tasks.period_end_reminder_task",
    bind=True,
    acks_late=True,
)
def period_end_reminder_task(self) -> dict:
    """Check for open fiscal periods ending within 3 days and log a reminder.

    Runs daily; no retry on failure — the next beat tick covers it.
    """
    from sqlalchemy import select as sa_select
    from app.modules.ledger.models import FiscalPeriod

    today = date.today()
    cutoff = today + timedelta(days=3)

    with sync_session_factory() as session:
        stmt = sa_select(FiscalPeriod).where(
            FiscalPeriod.status == PeriodStatus.OPEN.value,
            FiscalPeriod.end_date >= today,
            FiscalPeriod.end_date <= cutoff,
        )
        result = session.execute(stmt)
        upcoming = result.scalars().all()

        period_ids: list[str] = []
        for period in upcoming:
            period_ids.append(f"{period.fiscal_year}-{period.month:02d}")

        if period_ids:
            logger.info(
                "period_end_reminder",
                periods=period_ids,
                count=len(period_ids),
                cutoff_date=cutoff.isoformat(),
            )
        else:
            logger.info(
                "period_end_reminder_empty",
                cutoff_date=cutoff.isoformat(),
            )

        session.commit()

    return {
        "upcoming_periods": period_ids,
        "count": len(period_ids),
        "cutoff_date": cutoff.isoformat(),
    }
