"""Payables Celery tasks.

* ``recompute_ageing_task`` — periodic task that updates overdue status on
  issued bills where due_date < today.

Uses sync_session_factory() for the worker path.
"""

from __future__ import annotations

from datetime import date

import structlog
from sqlalchemy import select, update

from app.celery_app import celery_app
from app.db.session import sync_session_factory
from app.modules.payables.constants import BillStatus
from app.modules.payables.models import SupplierBill

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="payables.tasks.recompute_ageing_task",
    bind=True,
    acks_late=True,
)
def recompute_ageing_task(self) -> dict:
    """Mark issued bills as overdue when their due date has passed.

    Safe to run repeatedly — only updates bills that are currently ISSUED
    and past their due_date.
    """
    today = date.today()
    updated_count = 0

    with sync_session_factory() as session:
        result = session.execute(
            update(SupplierBill)
            .where(
                SupplierBill.status == BillStatus.ISSUED.value,
                SupplierBill.due_date < today,
            )
            .values(status=BillStatus.OVERDUE.value)
        )
        session.commit()
        updated_count = result.rowcount  # type: ignore[attr-defined]

    logger.info(
        "payables_ageing_recomputed",
        updated=updated_count,
        as_of=today.isoformat(),
    )
    return {"updated": updated_count, "as_of": today.isoformat()}
