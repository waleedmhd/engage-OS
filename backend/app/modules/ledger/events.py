"""Finance/ledger domain events published to the event bus."""


class FinanceEvents:
    ENTRY_POSTED = "ledger.entry_posted"
    INVOICE_CREATED = "finance.invoice_created"
    BILL_MATCHED = "payables.bill_matched"
    PERIOD_CLOSED = "ledger.period_closed"
    PERIOD_REOPENED = "ledger.period_reopened"
