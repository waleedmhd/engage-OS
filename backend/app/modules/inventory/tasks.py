"""Inventory Celery tasks — valuation refresh, reconciliation logging."""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa
import structlog

from app.celery_app import celery_app
from app.db.session import sync_session_factory

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="inventory.tasks.recompute_valuation_task",
    bind=True,
    acks_late=True,
)
def recompute_valuation_task(self) -> dict:
    """Periodic task: recompute total stock value and log reconciliation vs GL 1200.

    Runs via Celery Beat. Uses a sync session because Celery tasks run in
    worker threads.
    """
    from app.modules.inventory.constants import StockUnitStatus
    from app.modules.inventory.models import StockBalance, StockUnit

    with sync_session_factory() as session:
        # --------------------------------------------------------- stock value
        # Serialized: SUM of purchase_cost for all IN_STOCK units.
        serial_value_q = session.execute(
            sa.select(sa.func.coalesce(sa.func.sum(StockUnit.purchase_cost), 0))
            .where(StockUnit.status == StockUnitStatus.IN_STOCK.value)
        )
        serial_value = Decimal(str(serial_value_q.scalar_one()))

        # Bulk: SUM(qty * avg_cost) from stock_balances.
        bulk_value_q = session.execute(
            sa.select(
                sa.func.coalesce(
                    sa.func.sum(StockBalance.qty * StockBalance.avg_cost), 0
                )
            )
        )
        bulk_value = Decimal(str(bulk_value_q.scalar_one()))

        stock_value = serial_value + bulk_value

        # ------------------------------------------------------------ GL check
        gl_stmt = sa.text(
            """
            SELECT
                COALESCE(SUM(
                    CASE WHEN jl.dr_base > 0 THEN jl.dr_base ELSE -jl.cr_base END
                ), 0) AS balance
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.entry_id
            JOIN accounts a ON a.id = jl.account_id
            WHERE a.code = '1200'
              AND je.status = 'posted'
            """
        )
        gl_result = session.execute(gl_stmt)
        gl_balance = Decimal(str(gl_result.scalar_one()))

        # Quantize.
        from app.core.money import money

        stock_value = money(stock_value)
        variance = money(stock_value - gl_balance)
        reconciled = abs(variance) < Decimal("0.005")

        session.commit()

        logger.info(
            "valuation_recomputed",
            stock_value=str(stock_value),
            gl_balance=str(gl_balance),
            variance=str(variance),
            reconciled=reconciled,
        )
        return {
            "status": "ok",
            "stock_value": str(stock_value),
            "gl_balance": str(gl_balance),
            "variance": str(variance),
            "reconciled": reconciled,
        }
