"""ERP reporting module constants."""

from enum import StrEnum


class ReportType(StrEnum):
    TRIAL_BALANCE = "trial_balance"
    PL = "profit_and_loss"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    AR_AGEING = "ar_ageing"
    AP_AGEING = "ap_ageing"
    STOCK_VALUATION = "stock_valuation"
    MARGIN = "gross_margin"
