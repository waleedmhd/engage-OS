"""ERP reporting repositories — read-model queries against erp_fin tables.

No ORM models — raw SQL joined queries for trial balance, P&L, balance sheet,
and gross margin reports.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.money import money_zero


class ReportRepository:
    """Read-model queries for financial statements."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -------------------------------------------------------------- trial balance

    async def trial_balance(self, as_of_date: date) -> list[dict]:
        """SUM dr/cr per account grouped by account, as of a given date.

        Returns list of dicts with keys:
            account_code, account_name, account_type, dr_total, cr_total, net_balance
        """
        stmt = sa.text("""
            SELECT
                a.code AS account_code,
                a.name AS account_name,
                a.type AS account_type,
                COALESCE(SUM(jl.dr), 0) AS dr_total,
                COALESCE(SUM(jl.cr), 0) AS cr_total,
                CASE
                    WHEN a.normal_side = 'debit'
                        THEN COALESCE(SUM(jl.dr), 0) - COALESCE(SUM(jl.cr), 0)
                    ELSE COALESCE(SUM(jl.cr), 0) - COALESCE(SUM(jl.dr), 0)
                END AS net_balance
            FROM accounts a
            LEFT JOIN journal_lines jl ON jl.account_id = a.id
            LEFT JOIN journal_entries je ON je.id = jl.entry_id
                AND je.posting_date <= :as_of_date
                AND je.status = 'posted'
            WHERE a.is_active = true
            GROUP BY a.id, a.code, a.name, a.type, a.normal_side
            ORDER BY a.code
        """)
        result = await self._session.execute(stmt, {"as_of_date": as_of_date})
        rows = result.mappings().all()
        return [
            {
                "account_code": row["account_code"],
                "account_name": row["account_name"],
                "account_type": row["account_type"],
                "dr_total": Decimal(str(row["dr_total"])),
                "cr_total": Decimal(str(row["cr_total"])),
                "net_balance": Decimal(str(row["net_balance"])),
            }
            for row in rows
        ]

    # ----------------------------------------------------------- profit and loss

    async def profit_and_loss(self, fiscal_year: int) -> dict:
        """Revenue - COGS - OPEX for the fiscal year.

        Returns dict with:
            revenue, cogs, gross_profit, opex, net_profit
        """
        stmt = sa.text("""
            SELECT
                a.type AS account_type,
                COALESCE(SUM(jl.cr) - SUM(jl.dr), 0) AS net_amount
            FROM journal_lines jl
            JOIN accounts a ON a.id = jl.account_id
            JOIN journal_entries je ON je.id = jl.entry_id
            JOIN fiscal_periods fp ON fp.id = je.period_id
            WHERE fp.fiscal_year = :fiscal_year
                AND je.status = 'posted'
                AND a.type IN ('revenue', 'cogs', 'opex')
            GROUP BY a.type
        """)
        result = await self._session.execute(stmt, {"fiscal_year": fiscal_year})
        rows = result.mappings().all()

        amounts: dict[str, Decimal] = {"revenue": money_zero(), "cogs": money_zero(), "opex": money_zero()}
        for row in rows:
            amounts[row["account_type"]] = Decimal(str(row["net_amount"]))

        revenue = amounts["revenue"]
        cogs = amounts["cogs"]
        opex = amounts["opex"]
        gross_profit = revenue - abs(cogs)
        net_profit = gross_profit - abs(opex)

        return {
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "opex": opex,
            "net_profit": net_profit,
        }

    # -------------------------------------------------------------- balance sheet

    async def balance_sheet(self, as_of_date: date) -> dict:
        """Assets = Liabilities + Equity as of a given date.

        Returns dict with:
            assets, liabilities, equity, retained_earnings

        Both the balance-sheet accounts and the P&L accounts are summed. The
        P&L net is reported as ``retained_earnings`` and added to equity: until
        a year-end closing entry moves them, profit sits in the revenue/COGS/
        OPEX accounts, and omitting it left the sheet out of balance by exactly
        the net profit. Deriving it here is what makes a mid-year balance sheet
        tie without requiring a closing entry first.
        """
        stmt = sa.text("""
            SELECT
                a.type AS account_type,
                COALESCE(SUM(jl.dr) - SUM(jl.cr), 0) AS net_amount
            FROM journal_lines jl
            JOIN accounts a ON a.id = jl.account_id
            JOIN journal_entries je ON je.id = jl.entry_id
            WHERE je.posting_date <= :as_of_date
                AND je.status = 'posted'
            GROUP BY a.type
        """)
        result = await self._session.execute(stmt, {"as_of_date": as_of_date})
        rows = result.mappings().all()

        amounts: dict[str, Decimal] = {
            "asset": money_zero(), "liability": money_zero(), "equity": money_zero(),
            "revenue": money_zero(), "cogs": money_zero(), "opex": money_zero(),
        }
        for row in rows:
            amounts[row["account_type"]] = Decimal(str(row["net_amount"]))

        # Every net above is (debits - credits). Assets are debit-normal and so
        # are already positive; liabilities and equity are credit-normal and
        # come back negative, so both must be flipped — previously only
        # liabilities were, which left equity negative and the total wrong.
        assets = amounts["asset"]
        liabilities = -amounts["liability"]
        equity = -amounts["equity"]

        # Revenue is credit-normal, COGS and OPEX debit-normal.
        retained_earnings = -amounts["revenue"] - amounts["cogs"] - amounts["opex"]

        return {
            "assets": assets,
            "liabilities": liabilities,
            "equity": equity + retained_earnings,
            "retained_earnings": retained_earnings,
            "total_liabilities_and_equity": liabilities + equity + retained_earnings,
        }

    # --------------------------------------------------------------- gross margin

    async def gross_margin(self, fiscal_year: int) -> list[dict]:
        """Gross margin by item/customer for the fiscal year.

        Returns list of dicts with:
            item_id, item_name, revenue, cogs, margin, margin_pct
        """
        stmt = sa.text("""
            SELECT
                COALESCE(jl.party_id, dm.item_id) AS entity_id,
                CASE
                    WHEN jl.party_type = 'customer' THEN c.name
                    ELSE i.name
                END AS entity_name,
                CASE
                    WHEN jl.party_type = 'customer' THEN 'customer'
                    ELSE 'item'
                END AS entity_type,
                COALESCE(SUM(CASE WHEN a.type = 'revenue' THEN jl.cr - jl.dr ELSE 0 END), 0) AS revenue,
                COALESCE(SUM(CASE WHEN a.type = 'cogs' THEN jl.dr - jl.cr ELSE 0 END), 0) AS cogs
            FROM journal_lines jl
            JOIN accounts a ON a.id = jl.account_id
            JOIN journal_entries je ON je.id = jl.entry_id
            JOIN fiscal_periods fp ON fp.id = je.period_id
            LEFT JOIN contacts c ON c.id = jl.party_id AND jl.party_type = 'customer'
            LEFT JOIN dispatch_lines dm ON dm.dispatch_id = je.source_id
                AND je.source_type = 'dispatch'
            LEFT JOIN items i ON i.id = dm.item_id
            WHERE fp.fiscal_year = :fiscal_year
                AND je.status = 'posted'
                AND a.type IN ('revenue', 'cogs')
                AND (jl.party_id IS NOT NULL OR dm.item_id IS NOT NULL)
            GROUP BY entity_id, entity_name, entity_type
            ORDER BY revenue DESC
        """)
        result = await self._session.execute(stmt, {"fiscal_year": fiscal_year})
        rows = result.mappings().all()

        return [
            {
                "entity_id": str(row["entity_id"]) if row["entity_id"] else None,
                "entity_name": row["entity_name"] or "Unknown",
                "entity_type": row["entity_type"],
                "revenue": Decimal(str(row["revenue"])),
                "cogs": Decimal(str(row["cogs"])),
                "margin": Decimal(str(row["revenue"])) - Decimal(str(row["cogs"])),
                "margin_pct": (
                    ((Decimal(str(row["revenue"])) - Decimal(str(row["cogs"])))
                     / Decimal(str(row["revenue"])) * 100).quantize(Decimal("0.01"))
                    if Decimal(str(row["revenue"])) != 0
                    else Decimal("0")
                ),
            }
            for row in rows
        ]


class SyncReportRepository:
    """Sync variant for Celery tasks — same queries, sync session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def trial_balance(self, as_of_date: date) -> list[dict]:
        stmt = sa.text("""
            SELECT
                a.code AS account_code,
                a.name AS account_name,
                a.type AS account_type,
                COALESCE(SUM(jl.dr), 0) AS dr_total,
                COALESCE(SUM(jl.cr), 0) AS cr_total,
                CASE
                    WHEN a.normal_side = 'debit'
                        THEN COALESCE(SUM(jl.dr), 0) - COALESCE(SUM(jl.cr), 0)
                    ELSE COALESCE(SUM(jl.cr), 0) - COALESCE(SUM(jl.dr), 0)
                END AS net_balance
            FROM accounts a
            LEFT JOIN journal_lines jl ON jl.account_id = a.id
            LEFT JOIN journal_entries je ON je.id = jl.entry_id
                AND je.posting_date <= :as_of_date
                AND je.status = 'posted'
            WHERE a.is_active = true
            GROUP BY a.id, a.code, a.name, a.type, a.normal_side
            ORDER BY a.code
        """)
        result = self._session.execute(stmt, {"as_of_date": as_of_date})
        rows = result.mappings().all()
        return [
            {
                "account_code": row["account_code"],
                "account_name": row["account_name"],
                "account_type": row["account_type"],
                "dr_total": Decimal(str(row["dr_total"])),
                "cr_total": Decimal(str(row["cr_total"])),
                "net_balance": Decimal(str(row["net_balance"])),
            }
            for row in rows
        ]

    def profit_and_loss(self, fiscal_year: int) -> dict:
        stmt = sa.text("""
            SELECT
                a.type AS account_type,
                COALESCE(SUM(jl.cr) - SUM(jl.dr), 0) AS net_amount
            FROM journal_lines jl
            JOIN accounts a ON a.id = jl.account_id
            JOIN journal_entries je ON je.id = jl.entry_id
            JOIN fiscal_periods fp ON fp.id = je.period_id
            WHERE fp.fiscal_year = :fiscal_year
                AND je.status = 'posted'
                AND a.type IN ('revenue', 'cogs', 'opex')
            GROUP BY a.type
        """)
        result = self._session.execute(stmt, {"fiscal_year": fiscal_year})
        rows = result.mappings().all()
        amounts: dict[str, Decimal] = {"revenue": money_zero(), "cogs": money_zero(), "opex": money_zero()}
        for row in rows:
            amounts[row["account_type"]] = Decimal(str(row["net_amount"]))
        revenue = amounts["revenue"]
        cogs = amounts["cogs"]
        opex = amounts["opex"]
        return {
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": revenue - abs(cogs),
            "opex": opex,
            "net_profit": revenue - abs(cogs) - abs(opex),
        }

    def balance_sheet(self, as_of_date: date) -> dict:
        stmt = sa.text("""
            SELECT
                a.type AS account_type,
                COALESCE(SUM(jl.dr) - SUM(jl.cr), 0) AS net_amount
            FROM journal_lines jl
            JOIN accounts a ON a.id = jl.account_id
            JOIN journal_entries je ON je.id = jl.entry_id
            WHERE je.posting_date <= :as_of_date
                AND je.status = 'posted'
                AND a.type IN ('asset', 'liability', 'equity')
            GROUP BY a.type
        """)
        result = self._session.execute(stmt, {"as_of_date": as_of_date})
        rows = result.mappings().all()
        amounts: dict[str, Decimal] = {"asset": money_zero(), "liability": money_zero(), "equity": money_zero()}
        for row in rows:
            amounts[row["account_type"]] = Decimal(str(row["net_amount"]))
        assets = amounts["asset"]
        liabilities = abs(amounts["liability"])
        equity = amounts["equity"]
        return {
            "assets": assets,
            "liabilities": liabilities,
            "equity": equity,
            "total_liabilities_and_equity": liabilities + equity,
        }

    def gross_margin(self, fiscal_year: int) -> list[dict]:
        stmt = sa.text("""
            SELECT
                COALESCE(jl.party_id, dm.item_id) AS entity_id,
                CASE
                    WHEN jl.party_type = 'customer' THEN c.name
                    ELSE i.name
                END AS entity_name,
                CASE
                    WHEN jl.party_type = 'customer' THEN 'customer'
                    ELSE 'item'
                END AS entity_type,
                COALESCE(SUM(CASE WHEN a.type = 'revenue' THEN jl.cr - jl.dr ELSE 0 END), 0) AS revenue,
                COALESCE(SUM(CASE WHEN a.type = 'cogs' THEN jl.dr - jl.cr ELSE 0 END), 0) AS cogs
            FROM journal_lines jl
            JOIN accounts a ON a.id = jl.account_id
            JOIN journal_entries je ON je.id = jl.entry_id
            JOIN fiscal_periods fp ON fp.id = je.period_id
            LEFT JOIN contacts c ON c.id = jl.party_id AND jl.party_type = 'customer'
            LEFT JOIN dispatch_lines dm ON dm.dispatch_id = je.source_id
                AND je.source_type = 'dispatch'
            LEFT JOIN items i ON i.id = dm.item_id
            WHERE fp.fiscal_year = :fiscal_year
                AND je.status = 'posted'
                AND a.type IN ('revenue', 'cogs')
                AND (jl.party_id IS NOT NULL OR dm.item_id IS NOT NULL)
            GROUP BY entity_id, entity_name, entity_type
            ORDER BY revenue DESC
        """)
        result = self._session.execute(stmt, {"fiscal_year": fiscal_year})
        rows = result.mappings().all()
        return [
            {
                "entity_id": str(row["entity_id"]) if row["entity_id"] else None,
                "entity_name": row["entity_name"] or "Unknown",
                "entity_type": row["entity_type"],
                "revenue": Decimal(str(row["revenue"])),
                "cogs": Decimal(str(row["cogs"])),
                "margin": Decimal(str(row["revenue"])) - Decimal(str(row["cogs"])),
                "margin_pct": (
                    ((Decimal(str(row["revenue"])) - Decimal(str(row["cogs"])))
                     / Decimal(str(row["revenue"])) * 100).quantize(Decimal("0.01"))
                    if Decimal(str(row["revenue"])) != 0
                    else Decimal("0")
                ),
            }
            for row in rows
        ]
