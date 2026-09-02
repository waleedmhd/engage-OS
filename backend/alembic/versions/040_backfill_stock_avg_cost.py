"""Backfill stock_balances.avg_cost from the stock ledger.

GRNService.confirm() updated ``stock_balances.qty`` on receipt but never
``avg_cost``, so bulk stock stayed valued at zero: the stock report showed
AED 0.00 per row while the GRN journal had debited the full cost to account
1200. The service now maintains a moving average, but rows received before
that fix still read zero.

Reconstruct the average from the inbound stock ledger entries, which record
both the quantity and the value of every receipt. Only rows still sitting at
zero are touched, so a correctly-valued balance is never overwritten.

Revision ID: 040_backfill_stock_avg_cost
Revises: 039_analytics_rollup_defaults
"""

from alembic import op

revision = "040_backfill_stock_avg_cost"
down_revision = "039_analytics_rollup_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Averaged per item rather than per item+location: stock_ledger_entries
    # records warehouse_id, not location_id, so it cannot be joined back to a
    # specific balance row. Receipts of one item share a cost basis, so the
    # per-item weighted average is the faithful reconstruction.
    op.execute(
        """
        UPDATE stock_balances sb
        SET avg_cost = r.avg_cost
        FROM (
            SELECT item_id,
                   SUM(stock_value_change) / NULLIF(SUM(qty_change), 0) AS avg_cost
            FROM stock_ledger_entries
            WHERE qty_change > 0
            GROUP BY item_id
        ) r
        WHERE sb.item_id = r.item_id
          AND sb.avg_cost = 0
          AND r.avg_cost IS NOT NULL
          AND r.avg_cost > 0
        """
    )


def downgrade() -> None:
    # Not reversible: the previous value was zero for every row this touched,
    # and resetting them would restore the defect rather than a prior state.
    pass
