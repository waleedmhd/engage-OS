"""Analytics service — thin async layer over the read-only repository."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.analytics.constants import AnalyticsRange, resolve_range
from app.modules.analytics.repository import AnalyticsRepository
from app.modules.analytics.schemas import (
    AISummary,
    CampaignDailyPoint,
    CampaignDetailResponse,
    CampaignROIRow,
    CampaignSummaryRow,
    ConversionDailyPoint,
    ConversionSummary,
    CostDailyPoint,
    CostSummary,
    DailyPatternPoint,
    HourlyPatternPoint,
    ResponsivenessSummary,
    ROISummary,
    TemplateDailyPoint,
    TemplateDetailResponse,
    TemplateSummaryRow,
)

_TOP_CAMPAIGNS_LIMIT = 10


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AnalyticsRepository(session)

    async def cost(self, range_: AnalyticsRange) -> CostSummary:
        start, end = resolve_range(range_)
        totals = await self.repo.cost_totals(start, end)
        per_day = await self.repo.cost_by_day(start, end)
        return CostSummary(
            range=range_.value,
            start_date=start,
            end_date=end,
            ai_spend_usd=totals["ai"],
            message_cost_usd=totals["msg"],
            meta_cost_aed=totals["meta_aed"],
            tokens_input=totals["tokens_input"],
            tokens_output=totals["tokens_output"],
            total_cost_usd=totals["total"],
            by_day=[CostDailyPoint(**p) for p in per_day],
        )

    async def conversion(self, range_: AnalyticsRange) -> ConversionSummary:
        start, end = resolve_range(range_)
        totals = await self.repo.conversion_totals(start, end)
        per_day = await self.repo.conversion_by_day(start, end)
        sent = totals["sent"]
        received = totals["received"]
        delivered = totals["delivered"]
        rate = min(1.0, received / sent) if sent else 0.0
        return ConversionSummary(
            range=range_.value,
            start_date=start,
            end_date=end,
            messages_sent=sent,
            messages_received=received,
            messages_delivered=delivered,
            messages_failed=totals["failed"],
            response_rate=rate,
            # Conversion rate ≡ response rate at the global level until a
            # deal-closure event is introduced (see plan: deferred).
            conversion_rate=rate,
            by_day=[ConversionDailyPoint(**p) for p in per_day],
        )

    async def ai(self, range_: AnalyticsRange) -> AISummary:
        start, end = resolve_range(range_)
        totals = await self.repo.ai_totals(start, end)
        return AISummary(
            range=range_.value,
            start_date=start,
            end_date=end,
            token_spend_usd=totals["spend"],
            ai_call_count=totals["calls"],
            ai_error_count=totals["errors"],
            tokens_input=totals["tokens_input"],
            tokens_output=totals["tokens_output"],
            avg_latency_ms=totals["avg_latency_ms"],
            # ai_handled_pct deferred — needs conversation-state breakdown.
            ai_handled_pct=0.0,
        )

    async def roi(self, range_: AnalyticsRange) -> ROISummary:
        start, end = resolve_range(range_)
        totals = await self.repo.campaign_totals(start, end)
        top_rows = await self.repo.top_campaigns_by_roi(
            start, end, limit=_TOP_CAMPAIGNS_LIMIT
        )
        revenue = totals["revenue"]
        cost = totals["cost"]
        overall_roi = float(revenue / cost) if cost != 0 else None
        return ROISummary(
            range=range_.value,
            start_date=start,
            end_date=end,
            total_revenue_usd=revenue,
            total_cost_usd=cost,
            overall_roi=overall_roi,
            top_campaigns=[CampaignROIRow(**r) for r in top_rows],
        )

    async def list_campaigns(
        self, range_: AnalyticsRange, page: int, page_size: int
    ) -> tuple[list[CampaignSummaryRow], int, int, int]:
        start, end = resolve_range(range_)
        items, total = await self.repo.list_campaign_summary(
            start, end, page, page_size
        )
        return (
            [CampaignSummaryRow(**i) for i in items],
            total,
            page,
            page_size,
        )

    async def campaign_detail(
        self, campaign_id: uuid.UUID, range_: AnalyticsRange
    ) -> CampaignDetailResponse:
        start, end = resolve_range(range_)
        name = await self.repo.get_campaign_name(campaign_id)
        if name is None:
            raise NotFoundError(f"Campaign:{campaign_id}")

        totals = await self.repo.campaign_totals_for(campaign_id, start, end)
        rows = await self.repo.campaign_by_day(campaign_id, start, end)

        delivered = totals["recipients_delivered"]
        responded = totals["recipients_responded"]
        cost = totals["cost_usd"]
        revenue = totals["revenue_usd"]

        summary = CampaignSummaryRow(
            campaign_id=campaign_id,
            campaign_name=name,
            recipients_sent=totals["recipients_sent"],
            recipients_delivered=delivered,
            recipients_responded=responded,
            response_rate=(min(1.0, responded / delivered) if delivered else 0.0),
            revenue_usd=revenue,
            cost_usd=cost,
            meta_cost_aed=totals["meta_cost_aed"],
            tokens_input=totals["tokens_input"],
            tokens_output=totals["tokens_output"],
            roi=float(revenue / cost) if cost != 0 else None,
        )
        return CampaignDetailResponse(
            campaign_id=campaign_id,
            campaign_name=name,
            range=range_.value,
            start_date=start,
            end_date=end,
            totals=summary,
            by_day=[CampaignDailyPoint(**r) for r in rows],
        )

    async def list_templates(
        self, range_: AnalyticsRange, page: int, page_size: int
    ) -> tuple[list[TemplateSummaryRow], int, int, int]:
        start, end = resolve_range(range_)
        items, total = await self.repo.list_template_summary(
            start, end, page, page_size
        )
        return (
            [TemplateSummaryRow(**i) for i in items],
            total,
            page,
            page_size,
        )

    async def template_detail(
        self, template_id: uuid.UUID, range_: AnalyticsRange
    ) -> TemplateDetailResponse:
        start, end = resolve_range(range_)
        name = await self.repo.get_template_name(template_id)
        if name is None:
            raise NotFoundError(f"Template:{template_id}")

        totals = await self.repo.template_totals_for(template_id, start, end)
        rows = await self.repo.template_by_day(template_id, start, end)

        delivered = totals["recipients_delivered"]
        responded = totals["recipients_responded"]

        summary = TemplateSummaryRow(
            template_id=template_id,
            template_name=name,
            campaigns_used=totals["campaigns_used"],
            recipients_sent=totals["recipients_sent"],
            recipients_delivered=delivered,
            recipients_responded=responded,
            response_rate=(
                min(1.0, responded / delivered) if delivered else 0.0
            ),
            message_cost_usd=totals["message_cost_usd"],
            meta_cost_aed=totals["meta_cost_aed"],
            ai_spend_usd=totals["ai_spend_usd"],
            tokens_input=totals["tokens_input"],
            tokens_output=totals["tokens_output"],
            total_cost_usd=totals["total_cost_usd"],
        )
        return TemplateDetailResponse(
            template_id=template_id,
            template_name=name,
            range=range_.value,
            start_date=start,
            end_date=end,
            totals=summary,
            by_day=[TemplateDailyPoint(**r) for r in rows],
        )

    async def responsiveness(
        self, range_: AnalyticsRange
    ) -> ResponsivenessSummary:
        start, end = resolve_range(range_)
        hourly = await self.repo.hourly_pattern(start, end)
        daily = await self.repo.daily_pattern(start, end)
        return ResponsivenessSummary(
            range=range_.value,
            start_date=start,
            end_date=end,
            by_hour=[HourlyPatternPoint(**r) for r in hourly],
            by_day_of_week=[DailyPatternPoint(**r) for r in daily],
        )
