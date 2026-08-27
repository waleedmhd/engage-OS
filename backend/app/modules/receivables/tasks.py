"""Receivables Celery tasks.

Currently a single task: recompute_ageing_task — sweeps overdue invoices daily.
"""

from __future__ import annotations

from datetime import date

import structlog

from app.celery_app import celery_app
from app.db.session import sync_session_factory
from app.modules.receivables.constants import InvoiceStatus
from app.modules.receivables.models import SalesInvoice

logger = structlog.get_logger(__name__)


@celery_app.task(name="receivables.tasks.recompute_ageing_task")
def recompute_ageing_task() -> dict:
    """Daily sweep: mark issued invoices past their due date as overdue.

    Returns a small dict so the result is inspectable in Flower.
    """
    updated = 0
    with sync_session_factory() as session:
        try:
            overdue_invoices = (
                session.query(SalesInvoice)
                .filter(
                    SalesInvoice.status == InvoiceStatus.ISSUED.value,
                    SalesInvoice.due_date < date.today(),
                )
                .all()
            )
            for inv in overdue_invoices:
                inv.status = InvoiceStatus.OVERDUE.value
                updated += 1
            session.commit()
            logger.info("recompute_ageing_complete", updated=updated)
        except Exception:
            logger.exception("recompute_ageing_failed")
            session.rollback()
            raise
    return {"updated": updated}
