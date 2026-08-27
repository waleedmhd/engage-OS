"""Unit tests for AnalyticsService — repository is AsyncMocked."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.modules.analytics.constants import AnalyticsRange
from app.modules.analytics.service import AnalyticsService


def _make_service():
    session = AsyncMock()
    svc = AnalyticsService(session)
    svc.repo = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_cost_assembles_totals_and_by_day():
    svc = _make_service()
    svc.repo.cost_totals.return_value = {
        "ai": Decimal("12.50"),
        "msg": Decimal("3.00"),
        "meta_aed": Decimal("0.54"),
        "tokens_input": 5000,
        "tokens_output": 1200,
        "total": Decimal("15.50"),
    }
    svc.repo.cost_by_day.return_value = [
        {
            "metric_date": date(2026, 5, 12),
            "ai_spend_usd": Decimal("12.50"),
            "message_cost_usd": Decimal("3.00"),
            "meta_cost_aed": Decimal("0.54"),
            "tokens_input": 5000,
            "tokens_output": 1200,
            "total_cost_usd": Decimal("15.50"),
        }
    ]
    out = await svc.cost(AnalyticsRange.DAY)
    assert out.ai_spend_usd == Decimal("12.50")
    assert out.message_cost_usd == Decimal("3.00")
    assert out.total_cost_usd == Decimal("15.50")
    assert len(out.by_day) == 1
    assert out.range == "day"


@pytest.mark.asyncio
async def test_conversion_computes_response_rate():
    svc = _make_service()
    svc.repo.conversion_totals.return_value = {
        "sent": 100,
        "received": 40,
        "delivered": 95,
        "failed": 5,
    }
    svc.repo.conversion_by_day.return_value = []
    out = await svc.conversion(AnalyticsRange.WEEK)
    assert out.messages_sent == 100
    assert out.messages_received == 40
    assert out.response_rate == 0.4
    assert out.conversion_rate == 0.4


@pytest.mark.asyncio
async def test_conversion_handles_zero_sent():
    svc = _make_service()
    svc.repo.conversion_totals.return_value = {
        "sent": 0,
        "received": 0,
        "delivered": 0,
        "failed": 0,
    }
    svc.repo.conversion_by_day.return_value = []
    out = await svc.conversion(AnalyticsRange.MONTH)
    assert out.response_rate == 0.0


@pytest.mark.asyncio
async def test_ai_passes_repo_data_through():
    svc = _make_service()
    svc.repo.ai_totals.return_value = {
        "spend": Decimal("4.5"),
        "calls": 50,
        "errors": 2,
        "tokens_input": 8000,
        "tokens_output": 2000,
        "avg_latency_ms": 800,
    }
    out = await svc.ai(AnalyticsRange.MONTH)
    assert out.token_spend_usd == Decimal("4.5")
    assert out.ai_call_count == 50
    assert out.ai_error_count == 2
    assert out.avg_latency_ms == 800


@pytest.mark.asyncio
async def test_roi_computes_overall_from_totals():
    svc = _make_service()
    svc.repo.campaign_totals.return_value = {
        "revenue": Decimal("1000"),
        "cost": Decimal("250"),
    }
    svc.repo.top_campaigns_by_roi.return_value = []
    out = await svc.roi(AnalyticsRange.MONTH)
    assert out.total_revenue_usd == Decimal("1000")
    assert out.total_cost_usd == Decimal("250")
    assert out.overall_roi == 4.0


@pytest.mark.asyncio
async def test_roi_zero_cost_returns_null_roi():
    svc = _make_service()
    svc.repo.campaign_totals.return_value = {
        "revenue": Decimal("100"),
        "cost": Decimal("0"),
    }
    svc.repo.top_campaigns_by_roi.return_value = []
    out = await svc.roi(AnalyticsRange.MONTH)
    assert out.overall_roi is None


@pytest.mark.asyncio
async def test_campaign_detail_raises_when_campaign_missing():
    svc = _make_service()
    svc.repo.get_campaign_name.return_value = None
    with pytest.raises(NotFoundError):
        await svc.campaign_detail(uuid.uuid4(), AnalyticsRange.MONTH)


@pytest.mark.asyncio
async def test_campaign_detail_assembles_response():
    svc = _make_service()
    cid = uuid.uuid4()
    svc.repo.get_campaign_name.return_value = "Spring Promo"
    svc.repo.campaign_totals_for.return_value = {
        "recipients_sent": 200,
        "recipients_delivered": 180,
        "recipients_responded": 60,
        "revenue_usd": Decimal("3000"),
        "cost_usd": Decimal("100"),
        "meta_cost_aed": Decimal("32.40"),
        "tokens_input": 3000,
        "tokens_output": 800,
    }
    svc.repo.campaign_by_day.return_value = [
        {
            "metric_date": date(2026, 5, 12),
            "recipients_sent": 200,
            "recipients_delivered": 180,
            "recipients_responded": 60,
            "response_rate": 0.333,
            "revenue_usd": Decimal("3000"),
            "cost_usd": Decimal("100"),
            "meta_cost_aed": Decimal("32.40"),
            "tokens_input": 3000,
            "tokens_output": 800,
            "roi": 30.0,
        }
    ]
    out = await svc.campaign_detail(cid, AnalyticsRange.MONTH)
    assert out.campaign_id == cid
    assert out.campaign_name == "Spring Promo"
    assert out.totals.recipients_sent == 200
    assert out.totals.roi == 30.0
    assert out.totals.response_rate == pytest.approx(60 / 180)
    assert len(out.by_day) == 1


@pytest.mark.asyncio
async def test_list_campaigns_pages_and_returns_total():
    svc = _make_service()
    cid = uuid.uuid4()
    svc.repo.list_campaign_summary.return_value = (
        [
            {
                "campaign_id": cid,
                "campaign_name": "Promo",
                "template_name": "Welcome",
                "recipients_sent": 10,
                "recipients_delivered": 9,
                "recipients_responded": 3,
                "response_rate": 1 / 3,
                "revenue_usd": Decimal("90"),
                "cost_usd": Decimal("30"),
                "meta_cost_aed": Decimal("1.62"),
                "tokens_input": 500,
                "tokens_output": 150,
                "roi": 3.0,
            }
        ],
        7,
    )
    items, total, p, ps = await svc.list_campaigns(AnalyticsRange.MONTH, 1, 50)
    assert total == 7
    assert p == 1
    assert ps == 50
    assert items[0].campaign_id == cid
    assert items[0].roi == 3.0
