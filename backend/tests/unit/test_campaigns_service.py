"""Unit tests for CampaignService — no DB required."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.campaigns.constants import (
    CampaignRecipientStatus,
    CampaignStatus,
)
from app.modules.campaigns.schemas import CampaignReportResponse
from app.modules.campaigns.service import CampaignService


@pytest.fixture
def svc() -> CampaignService:
    svc = CampaignService.__new__(CampaignService)
    svc._session = AsyncMock()
    svc._repo = MagicMock()
    svc._recipient_repo = MagicMock()
    svc._audit = MagicMock()
    return svc


@pytest.mark.asyncio
async def test_get_report_includes_error_breakdown(svc: CampaignService) -> None:
    campaign_id = uuid.uuid4()
    now = datetime.now(UTC)

    campaign = MagicMock()
    campaign.id = campaign_id
    campaign.status = CampaignStatus.FAILED.value
    campaign.audience_count = 10
    campaign.sent_count = 10
    campaign.delivered_count = 8
    campaign.failed_count = 2
    campaign.response_count = 1
    campaign.started_at = now
    campaign.completed_at = now

    svc._get_or_404 = AsyncMock(return_value=campaign)  # type: ignore[method-assign]
    svc._recipient_repo.count_by_status = AsyncMock(  # type: ignore[attr-defined]
        return_value={
            CampaignRecipientStatus.SENT.value: 8,
            CampaignRecipientStatus.FAILED.value: 2,
        }
    )
    svc._recipient_repo.error_breakdown = AsyncMock(  # type: ignore[attr-defined]
        return_value=[("network timeout", None, 1), ("template render error", 131053, 1)]
    )

    report = await svc.get_report(campaign_id)

    assert isinstance(report, CampaignReportResponse)
    assert report.status == "failed"
    assert len(report.error_breakdown) == 2
    assert report.error_breakdown[0].error_message == "network timeout"
    assert report.error_breakdown[0].count == 1
    assert report.error_breakdown[1].error_message == "template render error"
    assert report.error_breakdown[1].count == 1


@pytest.mark.asyncio
async def test_get_report_empty_error_breakdown(svc: CampaignService) -> None:
    campaign_id = uuid.uuid4()

    campaign = MagicMock()
    campaign.id = campaign_id
    campaign.status = CampaignStatus.COMPLETED.value
    campaign.audience_count = 10
    campaign.sent_count = 10
    campaign.delivered_count = 10
    campaign.failed_count = 0
    campaign.response_count = 2
    campaign.started_at = None
    campaign.completed_at = None

    svc._get_or_404 = AsyncMock(return_value=campaign)  # type: ignore[method-assign]
    svc._recipient_repo.count_by_status = AsyncMock(  # type: ignore[attr-defined]
        return_value={CampaignRecipientStatus.DELIVERED.value: 10}
    )
    svc._recipient_repo.error_breakdown = AsyncMock(  # type: ignore[attr-defined]
        return_value=[]
    )

    report = await svc.get_report(campaign_id)

    assert report.error_breakdown == []
    assert report.delivery_rate == 1.0
