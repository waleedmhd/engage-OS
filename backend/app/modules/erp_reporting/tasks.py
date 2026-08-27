"""ERP reporting Celery tasks.

Heavy reports can be generated async and cached to Redis for retrieval.
"""

from __future__ import annotations

import json
from datetime import date

from app.celery_app import celery_app
from app.core.redis import get_sync_redis
from app.db.session import sync_session_factory


@celery_app.task(
    name="erp_reporting.tasks.generate_statement_task",
    max_retries=2,
    default_retry_delay=60,
    autoretry_for=(Exception,),
)
def generate_statement_task(
    report_type: str,
    fiscal_year: int | None = None,
    as_of_date_str: str | None = None,
    *,
    ttl: int = 3600,
) -> None:
    """Generate a heavy financial statement and cache to Redis.

    Called by the API for reports that may time out in the HTTP request cycle.
    Results are cached with a Redis key like `report:trial_balance:2025-12-31`.

    Args:
        report_type: One of 'trial_balance', 'profit_and_loss', 'balance_sheet', 'gross_margin'.
        fiscal_year: Used for P&L and margin reports.
        as_of_date_str: ISO date string, used for trial balance and balance sheet.
        ttl: Redis cache TTL in seconds (default 1 hour).
    """
    from app.modules.erp_reporting.repository import SyncReportRepository

    as_of_date_obj: date | None = date.fromisoformat(as_of_date_str) if as_of_date_str else None

    with sync_session_factory() as session:
        repo = SyncReportRepository(session)

        if report_type == "trial_balance":
            if as_of_date_obj is None:
                raise ValueError("as_of_date_str is required for trial_balance")
            rows = repo.trial_balance(as_of_date_obj)
            result_dict: dict = {"as_of_date": as_of_date_str, "rows": rows}
        elif report_type == "profit_and_loss":
            if fiscal_year is None:
                raise ValueError("fiscal_year is required for profit_and_loss")
            result_dict = repo.profit_and_loss(fiscal_year)
        elif report_type == "balance_sheet":
            if as_of_date_obj is None:
                raise ValueError("as_of_date_str is required for balance_sheet")
            result_dict = repo.balance_sheet(as_of_date_obj)
        elif report_type == "gross_margin":
            if fiscal_year is None:
                raise ValueError("fiscal_year is required for gross_margin")
            result_dict = {"fiscal_year": fiscal_year, "items": repo.gross_margin(fiscal_year)}
        else:
            raise ValueError(f"Unknown report_type: {report_type}")

        json_str = json.dumps(result_dict, default=str)

    # Cache to Redis.
    cache_key = f"report:{report_type}"
    if as_of_date_str:
        cache_key += f":{as_of_date_str}"
    if fiscal_year is not None:
        cache_key += f":fy{fiscal_year}"

    redis_client = get_sync_redis()
    redis_client.setex(cache_key, ttl, json_str)
