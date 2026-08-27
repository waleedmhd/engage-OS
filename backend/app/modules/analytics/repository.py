"""Analytics repository — read-only aggregations over rollup tables + source tables.

Rollup tables are the primary read target for established dimensions
(cost, conversion). New dimensions (meta_cost_aed, tokens_input/output,
template performance, responsiveness) query source tables directly so
data is available immediately, not just after the nightly beat run.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.models import (
    AnalyticsCampaignDailyMetrics,
    AnalyticsDailyMetrics,
)

# ---------------------------------------------------------------------------
# Shared raw-SQL fragments used by multiple methods
# ---------------------------------------------------------------------------

_SOURCE_META_TOKENS_GLOBAL = text(
    """
    WITH
    msg AS (
        SELECT
            COUNT(*) FILTER (
                WHERE direction = 'outbound'
                  AND delivery_status IN ('delivered','read')
            ) * 0.18::numeric(12,4) AS meta_cost_aed
        FROM messages
        WHERE created_at >= :day_start AND created_at < :day_end
    ),
    ai_tok AS (
        SELECT
            COALESCE(SUM((response->'usage'->>'input_tokens')::int), 0)::int AS tokens_in,
            COALESCE(SUM((response->'usage'->>'output_tokens')::int), 0)::int AS tokens_out
        FROM ai_events
        WHERE created_at >= :day_start AND created_at < :day_end
    )
    SELECT msg.meta_cost_aed, ai_tok.tokens_in, ai_tok.tokens_out
    FROM msg, ai_tok
    """
)

_SOURCE_TEMPLATE_PERF_SQL = """
    WITH
    day_recip AS (
        SELECT
            t.id AS template_id,
            t.name AS template_name,
            cr.campaign_id,
            COUNT(*) FILTER (
                WHERE cr.status IN ('sent','delivered','failed')
            ) AS sent_n,
            COUNT(*) FILTER (
                WHERE cr.delivered_at IS NOT NULL
            ) AS delivered_n,
            COUNT(*) FILTER (WHERE cr.responded = TRUE) AS responded_n
        FROM campaign_recipients cr
        JOIN campaigns c ON c.id = cr.campaign_id
        JOIN templates t ON t.id = c.template_id
        WHERE cr.sent_at IS NOT NULL
          AND cr.sent_at >= :day_start
          AND cr.sent_at < :day_end
        GROUP BY t.id, t.name, cr.campaign_id
    ),
    tmpl AS (
        SELECT
            template_id,
            MAX(template_name) AS template_name,
            COUNT(DISTINCT campaign_id)::int AS campaigns_used,
            SUM(sent_n)::int AS sent_n,
            SUM(delivered_n)::int AS delivered_n,
            SUM(responded_n)::int AS responded_n
        FROM day_recip
        GROUP BY template_id
    ),
    msg_cost AS (
        SELECT
            t.id AS template_id,
            COALESCE(SUM(m.cost), 0)::numeric(12,4) AS message_cost
        FROM campaign_recipients cr
        JOIN campaigns c ON c.id = cr.campaign_id
        JOIN templates t ON t.id = c.template_id
        JOIN messages m ON m.id = cr.message_id
        WHERE cr.sent_at IS NOT NULL
          AND cr.sent_at >= :day_start
          AND cr.sent_at < :day_end
          AND m.delivery_status IN ('delivered','read','sent','failed')
        GROUP BY t.id
    ),
    ai_cost AS (
        SELECT
            t.id AS template_id,
            COALESCE(SUM(ae.cost_estimate), 0)::numeric(12,4) AS ai_spend,
            COALESCE(SUM((ae.response->'usage'->>'input_tokens')::int), 0)::int AS tokens_in,
            COALESCE(SUM((ae.response->'usage'->>'output_tokens')::int), 0)::int AS tokens_out
        FROM campaign_recipients cr
        JOIN campaigns c ON c.id = cr.campaign_id
        JOIN templates t ON t.id = c.template_id
        JOIN messages m ON m.id = cr.message_id
        JOIN ai_events ae ON ae.conversation_id = m.conversation_id
        WHERE cr.sent_at IS NOT NULL
          AND cr.sent_at >= :day_start
          AND cr.sent_at < :day_end
          AND ae.created_at >= :day_start
          AND ae.created_at < :day_end
        GROUP BY t.id
    )
    SELECT
        tmpl.template_id,
        tmpl.template_name,
        tmpl.campaigns_used,
        tmpl.sent_n,
        tmpl.delivered_n,
        tmpl.responded_n,
        COALESCE(mc.message_cost, 0) AS msg_cost,
        tmpl.delivered_n * 0.18::numeric(12,4) AS meta_aed,
        COALESCE(ac.ai_spend, 0) AS ai_cost,
        COALESCE(ac.tokens_in, 0) AS tokens_in,
        COALESCE(ac.tokens_out, 0) AS tokens_out,
        (COALESCE(ac.ai_spend, 0) + COALESCE(mc.message_cost, 0)
         + tmpl.delivered_n * 0.049)::numeric(12,4) AS total_cost
    FROM tmpl
    LEFT JOIN msg_cost mc ON mc.template_id = tmpl.template_id
    LEFT JOIN ai_cost ac ON ac.template_id = tmpl.template_id
    """


def _next_day(d: date) -> date:
    """Return d + 1 day (exclusive upper bound for date ranges)."""
    from datetime import timedelta

    return d + timedelta(days=1)


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Global rollups
    # ------------------------------------------------------------------
    async def cost_totals(self, start: date, end: date) -> dict[str, Any]:
        rollup = select(
            func.coalesce(func.sum(AnalyticsDailyMetrics.ai_spend_usd), 0),
            func.coalesce(func.sum(AnalyticsDailyMetrics.message_cost_usd), 0),
            func.coalesce(func.sum(AnalyticsDailyMetrics.total_cost_usd), 0),
        ).where(AnalyticsDailyMetrics.metric_date.between(start, end))
        ai, msg, total = (await self.session.execute(rollup)).one()

        src = await self.session.execute(
            _SOURCE_META_TOKENS_GLOBAL,
            {"day_start": start, "day_end": _next_day(end)},
        )
        meta_aed, tokens_in, tokens_out = src.one()

        return {
            "ai": Decimal(ai),
            "msg": Decimal(msg),
            "meta_aed": Decimal(meta_aed),
            "tokens_input": int(tokens_in),
            "tokens_output": int(tokens_out),
            "total": Decimal(total),
        }

    async def cost_by_day(self, start: date, end: date) -> list[dict[str, Any]]:
        stmt = (
            select(
                AnalyticsDailyMetrics.metric_date,
                AnalyticsDailyMetrics.ai_spend_usd,
                AnalyticsDailyMetrics.message_cost_usd,
                AnalyticsDailyMetrics.total_cost_usd,
            )
            .where(AnalyticsDailyMetrics.metric_date.between(start, end))
            .order_by(AnalyticsDailyMetrics.metric_date.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "metric_date": r[0],
                "ai_spend_usd": Decimal(r[1]),
                "message_cost_usd": Decimal(r[2]),
                "meta_cost_aed": Decimal(0),
                "tokens_input": 0,
                "tokens_output": 0,
                "total_cost_usd": Decimal(r[3]),
            }
            for r in rows
        ]

    async def conversion_totals(self, start: date, end: date) -> dict[str, Any]:
        stmt = select(
            func.coalesce(func.sum(AnalyticsDailyMetrics.messages_sent), 0),
            func.coalesce(func.sum(AnalyticsDailyMetrics.messages_received), 0),
            func.coalesce(func.sum(AnalyticsDailyMetrics.messages_delivered), 0),
            func.coalesce(func.sum(AnalyticsDailyMetrics.messages_failed), 0),
        ).where(AnalyticsDailyMetrics.metric_date.between(start, end))
        sent, received, delivered, failed = (await self.session.execute(stmt)).one()
        return {
            "sent": int(sent),
            "received": int(received),
            "delivered": int(delivered),
            "failed": int(failed),
        }

    async def conversion_by_day(self, start: date, end: date) -> list[dict[str, Any]]:
        stmt = (
            select(
                AnalyticsDailyMetrics.metric_date,
                AnalyticsDailyMetrics.messages_sent,
                AnalyticsDailyMetrics.messages_received,
                AnalyticsDailyMetrics.response_rate,
            )
            .where(AnalyticsDailyMetrics.metric_date.between(start, end))
            .order_by(AnalyticsDailyMetrics.metric_date.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "metric_date": r[0],
                "messages_sent": int(r[1]),
                "messages_received": int(r[2]),
                "response_rate": float(r[3]),
            }
            for r in rows
        ]

    async def ai_totals(self, start: date, end: date) -> dict[str, Any]:
        rollup = select(
            func.coalesce(func.sum(AnalyticsDailyMetrics.ai_spend_usd), 0),
            func.coalesce(func.sum(AnalyticsDailyMetrics.ai_call_count), 0),
            func.coalesce(func.sum(AnalyticsDailyMetrics.ai_error_count), 0),
            func.coalesce(
                func.sum(
                    AnalyticsDailyMetrics.ai_avg_latency_ms
                    * AnalyticsDailyMetrics.ai_call_count
                ),
                0,
            ),
        ).where(AnalyticsDailyMetrics.metric_date.between(start, end))
        spend, calls, errors, latency_weighted = (
            await self.session.execute(rollup)
        ).one()
        calls_int = int(calls)
        avg_latency = (
            int(int(latency_weighted) / calls_int) if calls_int > 0 else None
        )

        # tokens from source (ai_events JSONB)
        tok_stmt = text(
            """
            SELECT
                COALESCE(SUM((response->'usage'->>'input_tokens')::int), 0)::int,
                COALESCE(SUM((response->'usage'->>'output_tokens')::int), 0)::int
            FROM ai_events
            WHERE created_at >= :start AND created_at < :end
            """
        )
        tok_row = (
            await self.session.execute(
                tok_stmt, {"start": start, "end": _next_day(end)}
            )
        ).one()

        return {
            "spend": Decimal(spend),
            "calls": calls_int,
            "errors": int(errors),
            "tokens_input": int(tok_row[0]),
            "tokens_output": int(tok_row[1]),
            "avg_latency_ms": avg_latency,
        }

    # ------------------------------------------------------------------
    # Per-campaign rollups
    # ------------------------------------------------------------------
    async def campaign_totals(self, start: date, end: date) -> dict[str, Decimal]:
        stmt = select(
            func.coalesce(
                func.sum(AnalyticsCampaignDailyMetrics.revenue_attributed_usd), 0
            ),
            func.coalesce(
                func.sum(AnalyticsCampaignDailyMetrics.total_cost_usd), 0
            ),
        ).where(AnalyticsCampaignDailyMetrics.metric_date.between(start, end))
        revenue, cost = (await self.session.execute(stmt)).one()
        return {"revenue": Decimal(revenue), "cost": Decimal(cost)}

    async def top_campaigns_by_roi(
        self, start: date, end: date, limit: int = 10
    ) -> list[dict[str, Any]]:
        stmt = text(
            """
            SELECT
                acdm.campaign_id,
                COALESCE(c.name, '') AS campaign_name,
                SUM(acdm.revenue_attributed_usd) AS revenue,
                SUM(acdm.total_cost_usd) AS cost
            FROM analytics_campaign_daily_metrics acdm
            LEFT JOIN campaigns c ON c.id = acdm.campaign_id
            WHERE acdm.metric_date BETWEEN :start AND :end
            GROUP BY acdm.campaign_id, c.name
            ORDER BY (
                CASE WHEN SUM(acdm.total_cost_usd) = 0 THEN NULL
                     ELSE SUM(acdm.revenue_attributed_usd) / SUM(acdm.total_cost_usd)
                END
            ) DESC NULLS LAST,
            SUM(acdm.revenue_attributed_usd) DESC
            LIMIT :limit
            """
        )
        rows = (
            await self.session.execute(
                stmt, {"start": start, "end": end, "limit": limit}
            )
        ).all()
        return [
            {
                "campaign_id": r[0],
                "campaign_name": r[1] or "",
                "revenue_usd": Decimal(r[2]),
                "cost_usd": Decimal(r[3]),
                "roi": (
                    float(Decimal(r[2]) / Decimal(r[3]))
                    if Decimal(r[3]) != 0
                    else None
                ),
            }
            for r in rows
        ]

    async def list_campaign_summary(
        self, start: date, end: date, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        offset = (page - 1) * page_size
        count_stmt = text(
            """
            SELECT COUNT(DISTINCT campaign_id)
            FROM analytics_campaign_daily_metrics
            WHERE metric_date BETWEEN :start AND :end
            """
        )
        total = int(
            (
                await self.session.execute(count_stmt, {"start": start, "end": end})
            ).scalar_one()
        )

        stmt = text(
            """
            SELECT
                acdm.campaign_id,
                COALESCE(c.name, '') AS campaign_name,
                COALESCE(t.name, '') AS template_name,
                SUM(acdm.recipients_sent) AS sent_n,
                SUM(acdm.recipients_delivered) AS delivered_n,
                SUM(acdm.recipients_responded) AS responded_n,
                SUM(acdm.revenue_attributed_usd) AS revenue,
                SUM(acdm.total_cost_usd) AS cost
            FROM analytics_campaign_daily_metrics acdm
            LEFT JOIN campaigns c ON c.id = acdm.campaign_id
            LEFT JOIN templates t ON t.id = c.template_id
            WHERE acdm.metric_date BETWEEN :start AND :end
            GROUP BY acdm.campaign_id, c.name, t.name
            ORDER BY SUM(acdm.revenue_attributed_usd) DESC,
                     SUM(acdm.recipients_sent) DESC
            LIMIT :limit OFFSET :offset
            """
        )
        rows = (
            await self.session.execute(
                stmt,
                {
                    "start": start,
                    "end": end,
                    "limit": page_size,
                    "offset": offset,
                },
            )
        ).all()

        # Source query for meta_cost + tokens per campaign in this window
        campaign_ids = [r[0] for r in rows]
        extra: dict[str, dict] = {}
        if campaign_ids:
            extra = await self._campaign_source_extra(
                start, end, campaign_ids
            )

        items = []
        for r in rows:
            cid = r[0]
            e = extra.get(str(cid), {})
            delivered = int(r[4])
            responded = int(r[5])
            cost = Decimal(r[7])
            revenue = Decimal(r[6])
            items.append(
                {
                    "campaign_id": cid,
                    "campaign_name": r[1] or "",
                    "template_name": r[2] or "",
                    "recipients_sent": int(r[3]),
                    "recipients_delivered": delivered,
                    "recipients_responded": responded,
                    "response_rate": (
                        min(1.0, responded / delivered) if delivered else 0.0
                    ),
                    "revenue_usd": revenue,
                    "cost_usd": cost,
                    "meta_cost_aed": Decimal(e.get("meta_cost_aed", 0)),
                    "tokens_input": int(e.get("tokens_input", 0)),
                    "tokens_output": int(e.get("tokens_output", 0)),
                    "roi": float(revenue / cost) if cost != 0 else None,
                }
            )
        return items, total

    async def _campaign_source_extra(
        self, start: date, end: date, campaign_ids: list
    ) -> dict[str, dict]:
        """Fetch meta_cost_aed + tokens per campaign from source tables."""
        stmt = text(
            """
            WITH
            recip AS (
                SELECT
                    cr.campaign_id,
                    COUNT(*) FILTER (
                        WHERE cr.delivered_at IS NOT NULL
                    )::int AS delivered_n
                FROM campaign_recipients cr
                WHERE cr.sent_at >= :start AND cr.sent_at < :end
                  AND cr.campaign_id = ANY(:cids)
                GROUP BY cr.campaign_id
            ),
            ai AS (
                SELECT
                    cr.campaign_id,
                    COALESCE(SUM((ae.response->'usage'->>'input_tokens')::int), 0)::int AS tokens_in,
                    COALESCE(SUM((ae.response->'usage'->>'output_tokens')::int), 0)::int AS tokens_out
                FROM campaign_recipients cr
                JOIN messages m ON m.id = cr.message_id
                JOIN ai_events ae ON ae.conversation_id = m.conversation_id
                WHERE cr.sent_at >= :start AND cr.sent_at < :end
                  AND cr.campaign_id = ANY(:cids)
                  AND ae.created_at >= :start AND ae.created_at < :end
                GROUP BY cr.campaign_id
            )
            SELECT
                r.campaign_id,
                r.delivered_n * 0.18::numeric(12,4) AS meta_cost_aed,
                COALESCE(ai.tokens_in, 0) AS tokens_input,
                COALESCE(ai.tokens_out, 0) AS tokens_output
            FROM recip r
            LEFT JOIN ai ON ai.campaign_id = r.campaign_id
            """
        )
        rows = await self.session.execute(
            stmt,
            {
                "start": start,
                "end": _next_day(end),
                "cids": campaign_ids,
            },
        )
        return {
            str(r[0]): {
                "meta_cost_aed": r[1],
                "tokens_input": r[2],
                "tokens_output": r[3],
            }
            for r in rows
        }

    async def campaign_by_day(
        self, campaign_id: uuid.UUID, start: date, end: date
    ) -> list[dict[str, Any]]:
        stmt = (
            select(
                AnalyticsCampaignDailyMetrics.metric_date,
                AnalyticsCampaignDailyMetrics.recipients_sent,
                AnalyticsCampaignDailyMetrics.recipients_delivered,
                AnalyticsCampaignDailyMetrics.recipients_responded,
                AnalyticsCampaignDailyMetrics.response_rate,
                AnalyticsCampaignDailyMetrics.revenue_attributed_usd,
                AnalyticsCampaignDailyMetrics.total_cost_usd,
                AnalyticsCampaignDailyMetrics.roi,
            )
            .where(AnalyticsCampaignDailyMetrics.campaign_id == campaign_id)
            .where(AnalyticsCampaignDailyMetrics.metric_date.between(start, end))
            .order_by(AnalyticsCampaignDailyMetrics.metric_date.asc())
        )
        rows = (await self.session.execute(stmt)).all()

        # Source query for per-day meta_cost + tokens for this campaign
        extra_by_day = await self._campaign_by_day_source_extra(
            campaign_id, start, end
        )

        return [
            {
                "metric_date": r[0],
                "recipients_sent": int(r[1]),
                "recipients_delivered": int(r[2]),
                "recipients_responded": int(r[3]),
                "response_rate": float(r[4]),
                "revenue_usd": Decimal(r[5]),
                "cost_usd": Decimal(r[6]),
                "meta_cost_aed": Decimal(
                    extra_by_day.get(r[0], {}).get("meta_cost_aed", 0)
                ),
                "tokens_input": int(
                    extra_by_day.get(r[0], {}).get("tokens_input", 0)
                ),
                "tokens_output": int(
                    extra_by_day.get(r[0], {}).get("tokens_output", 0)
                ),
                "roi": float(r[7]) if r[7] is not None else None,
            }
            for r in rows
        ]

    async def _campaign_by_day_source_extra(
        self, campaign_id: uuid.UUID, start: date, end: date
    ) -> dict:
        stmt = text(
            """
            WITH
            recip AS (
                SELECT
                    cr.sent_at::date AS metric_date,
                    COUNT(*) FILTER (
                        WHERE cr.delivered_at IS NOT NULL
                    )::int AS delivered_n
                FROM campaign_recipients cr
                WHERE cr.campaign_id = :cid
                  AND cr.sent_at >= :start AND cr.sent_at < :end
                GROUP BY cr.sent_at::date
            ),
            ai AS (
                SELECT
                    cr.sent_at::date AS metric_date,
                    COALESCE(SUM((ae.response->'usage'->>'input_tokens')::int), 0)::int AS tokens_in,
                    COALESCE(SUM((ae.response->'usage'->>'output_tokens')::int), 0)::int AS tokens_out
                FROM campaign_recipients cr
                JOIN messages m ON m.id = cr.message_id
                JOIN ai_events ae ON ae.conversation_id = m.conversation_id
                WHERE cr.campaign_id = :cid
                  AND cr.sent_at >= :start AND cr.sent_at < :end
                  AND ae.created_at >= :start AND ae.created_at < :end
                GROUP BY cr.sent_at::date
            )
            SELECT
                r.metric_date,
                r.delivered_n * 0.18::numeric(12,4) AS meta_cost_aed,
                COALESCE(ai.tokens_in, 0) AS tokens_input,
                COALESCE(ai.tokens_out, 0) AS tokens_output
            FROM recip r
            LEFT JOIN ai ON ai.metric_date = r.metric_date
            """
        )
        rows = await self.session.execute(
            stmt,
            {
                "cid": campaign_id,
                "start": start,
                "end": _next_day(end),
            },
        )
        return {
            r[0]: {
                "meta_cost_aed": r[1],
                "tokens_input": r[2],
                "tokens_output": r[3],
            }
            for r in rows
        }

    async def campaign_totals_for(
        self, campaign_id: uuid.UUID, start: date, end: date
    ) -> dict[str, Any]:
        stmt = select(
            func.coalesce(func.sum(AnalyticsCampaignDailyMetrics.recipients_sent), 0),
            func.coalesce(
                func.sum(AnalyticsCampaignDailyMetrics.recipients_delivered), 0
            ),
            func.coalesce(
                func.sum(AnalyticsCampaignDailyMetrics.recipients_responded), 0
            ),
            func.coalesce(
                func.sum(AnalyticsCampaignDailyMetrics.revenue_attributed_usd), 0
            ),
            func.coalesce(
                func.sum(AnalyticsCampaignDailyMetrics.total_cost_usd), 0
            ),
        ).where(
            (AnalyticsCampaignDailyMetrics.campaign_id == campaign_id)
            & (AnalyticsCampaignDailyMetrics.metric_date.between(start, end))
        )
        sent, delivered, responded, revenue, cost = (
            await self.session.execute(stmt)
        ).one()

        # Source query for meta/token per-campaign totals
        src_stmt = text(
            """
            WITH
            recip AS (
                SELECT
                    COUNT(*) FILTER (
                        WHERE cr.delivered_at IS NOT NULL
                    )::int AS delivered_n
                FROM campaign_recipients cr
                WHERE cr.campaign_id = :cid
                  AND cr.sent_at >= :start AND cr.sent_at < :end
            ),
            ai AS (
                SELECT
                    COALESCE(SUM((ae.response->'usage'->>'input_tokens')::int), 0)::int AS tokens_in,
                    COALESCE(SUM((ae.response->'usage'->>'output_tokens')::int), 0)::int AS tokens_out
                FROM campaign_recipients cr
                JOIN messages m ON m.id = cr.message_id
                JOIN ai_events ae ON ae.conversation_id = m.conversation_id
                WHERE cr.campaign_id = :cid
                  AND cr.sent_at >= :start AND cr.sent_at < :end
                  AND ae.created_at >= :start AND ae.created_at < :end
            )
            SELECT
                r.delivered_n * 0.18::numeric(12,4) AS meta_aed,
                COALESCE(ai.tokens_in, 0) AS tokens_in,
                COALESCE(ai.tokens_out, 0) AS tokens_out
            FROM recip r, ai
            """
        )
        src = (
            await self.session.execute(
                src_stmt,
                {
                    "cid": campaign_id,
                    "start": start,
                    "end": _next_day(end),
                },
            )
        ).one()

        return {
            "recipients_sent": int(sent),
            "recipients_delivered": int(delivered),
            "recipients_responded": int(responded),
            "revenue_usd": Decimal(revenue),
            "cost_usd": Decimal(cost),
            "meta_cost_aed": Decimal(src[0]),
            "tokens_input": int(src[1]),
            "tokens_output": int(src[2]),
        }

    async def get_campaign_name(self, campaign_id: uuid.UUID) -> str | None:
        stmt = text("SELECT name FROM campaigns WHERE id = :id")
        result = await self.session.execute(stmt, {"id": campaign_id})
        row = result.first()
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Template performance — source tables (not rollup, so data is live)
    # ------------------------------------------------------------------

    async def list_template_summary(
        self, start: date, end: date, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        offset = (page - 1) * page_size

        # Count: distinct templates used in recipients within the window
        count_stmt = text(
            """
            SELECT COUNT(DISTINCT t.id)
            FROM campaign_recipients cr
            JOIN campaigns c ON c.id = cr.campaign_id
            JOIN templates t ON t.id = c.template_id
            WHERE cr.sent_at IS NOT NULL
              AND cr.sent_at >= :start AND cr.sent_at < :end
            """
        )
        total = int(
            (
                await self.session.execute(
                    count_stmt,
                    {"start": start, "end": _next_day(end)},
                )
            ).scalar_one()
        )

        # Main query with pagination
        stmt = text(
            _SOURCE_TEMPLATE_PERF_SQL
            + " ORDER BY 4 DESC LIMIT :limit OFFSET :offset"
        )
        rows = (
            await self.session.execute(
                stmt,
                {
                    "day_start": start,
                    "day_end": _next_day(end),
                    "limit": page_size,
                    "offset": offset,
                },
            )
        ).all()
        items = []
        for r in rows:
            delivered = int(r[4])
            responded = int(r[5])
            items.append(
                {
                    "template_id": r[0],
                    "template_name": r[1] or "",
                    "campaigns_used": int(r[2]),
                    "recipients_sent": int(r[3]),
                    "recipients_delivered": delivered,
                    "recipients_responded": responded,
                    "response_rate": (
                        min(1.0, responded / delivered) if delivered else 0.0
                    ),
                    "message_cost_usd": Decimal(r[6]),
                    "meta_cost_aed": Decimal(r[7]),
                    "ai_spend_usd": Decimal(r[8]),
                    "tokens_input": int(r[9]),
                    "tokens_output": int(r[10]),
                    "total_cost_usd": Decimal(r[11]),
                }
            )
        return items, total

    async def template_totals_for(
        self, template_id: uuid.UUID, start: date, end: date
    ) -> dict[str, Any]:
        stmt = text(
            _SOURCE_TEMPLATE_PERF_SQL
            + " WHERE tmpl.template_id = :tid"
        )
        r = (
            await self.session.execute(
                stmt,
                {
                    "day_start": start,
                    "day_end": _next_day(end),
                    "tid": template_id,
                },
            )
        ).one()
        return {
            "campaigns_used": int(r[2]),
            "recipients_sent": int(r[3]),
            "recipients_delivered": int(r[4]),
            "recipients_responded": int(r[5]),
            "message_cost_usd": Decimal(r[6]),
            "meta_cost_aed": Decimal(r[7]),
            "ai_spend_usd": Decimal(r[8]),
            "tokens_input": int(r[9]),
            "tokens_output": int(r[10]),
            "total_cost_usd": Decimal(r[11]),
        }

    async def template_by_day(
        self, template_id: uuid.UUID, start: date, end: date
    ) -> list[dict[str, Any]]:
        stmt = text(
            """
            WITH
            day_recip AS (
                SELECT
                    cr.sent_at::date AS metric_date,
                    cr.campaign_id,
                    COUNT(*) FILTER (
                        WHERE cr.status IN ('sent','delivered','failed')
                    ) AS sent_n,
                    COUNT(*) FILTER (
                        WHERE cr.delivered_at IS NOT NULL
                    ) AS delivered_n,
                    COUNT(*) FILTER (WHERE cr.responded = TRUE) AS responded_n
                FROM campaign_recipients cr
                JOIN campaigns c ON c.id = cr.campaign_id
                WHERE c.template_id = :tid
                  AND cr.sent_at IS NOT NULL
                  AND cr.sent_at >= :start AND cr.sent_at < :end
                GROUP BY cr.sent_at::date, cr.campaign_id
            ),
            tmpl AS (
                SELECT
                    metric_date,
                    COUNT(DISTINCT campaign_id)::int AS campaigns_used,
                    SUM(sent_n)::int AS sent_n,
                    SUM(delivered_n)::int AS delivered_n,
                    SUM(responded_n)::int AS responded_n
                FROM day_recip
                GROUP BY metric_date
            ),
            msg_cost AS (
                SELECT
                    cr.sent_at::date AS metric_date,
                    COALESCE(SUM(m.cost), 0)::numeric(12,4) AS message_cost
                FROM campaign_recipients cr
                JOIN campaigns c ON c.id = cr.campaign_id
                JOIN messages m ON m.id = cr.message_id
                WHERE c.template_id = :tid
                  AND cr.sent_at IS NOT NULL
                  AND cr.sent_at >= :start AND cr.sent_at < :end
                  AND m.delivery_status IN ('delivered','read','sent','failed')
                GROUP BY cr.sent_at::date
            ),
            ai_cost AS (
                SELECT
                    cr.sent_at::date AS metric_date,
                    COALESCE(SUM(ae.cost_estimate), 0)::numeric(12,4) AS ai_spend,
                    COALESCE(SUM((ae.response->'usage'->>'input_tokens')::int), 0)::int AS tokens_in,
                    COALESCE(SUM((ae.response->'usage'->>'output_tokens')::int), 0)::int AS tokens_out
                FROM campaign_recipients cr
                JOIN campaigns c ON c.id = cr.campaign_id
                JOIN messages m ON m.id = cr.message_id
                JOIN ai_events ae ON ae.conversation_id = m.conversation_id
                WHERE c.template_id = :tid
                  AND cr.sent_at IS NOT NULL
                  AND cr.sent_at >= :start AND cr.sent_at < :end
                  AND ae.created_at >= :start AND ae.created_at < :end
                GROUP BY cr.sent_at::date
            )
            SELECT
                tmpl.metric_date,
                tmpl.campaigns_used,
                tmpl.sent_n,
                tmpl.delivered_n,
                tmpl.responded_n,
                COALESCE(mc.message_cost, 0) AS msg_cost,
                tmpl.delivered_n * 0.18::numeric(12,4) AS meta_aed,
                COALESCE(ac.ai_spend, 0) AS ai_cost,
                COALESCE(ac.tokens_in, 0) AS tokens_in,
                COALESCE(ac.tokens_out, 0) AS tokens_out,
                (COALESCE(ac.ai_spend, 0) + COALESCE(mc.message_cost, 0)
                 + tmpl.delivered_n * 0.049)::numeric(12,4) AS total_cost
            FROM tmpl
            LEFT JOIN msg_cost mc ON mc.metric_date = tmpl.metric_date
            LEFT JOIN ai_cost ac ON ac.metric_date = tmpl.metric_date
            ORDER BY tmpl.metric_date ASC
            """
        )
        rows = (
            await self.session.execute(
                stmt,
                {
                    "tid": template_id,
                    "start": start,
                    "end": _next_day(end),
                },
            )
        ).all()
        return [
            {
                "metric_date": r[0],
                "campaigns_used": int(r[1]),
                "recipients_sent": int(r[2]),
                "recipients_delivered": int(r[3]),
                "recipients_responded": int(r[4]),
                "response_rate": (
                    min(1.0, int(r[4]) / int(r[3])) if int(r[3]) else 0.0
                ),
                "message_cost_usd": Decimal(r[5]),
                "meta_cost_aed": Decimal(r[6]),
                "ai_spend_usd": Decimal(r[7]),
                "tokens_input": int(r[8]),
                "tokens_output": int(r[9]),
                "total_cost_usd": Decimal(r[10]),
            }
            for r in rows
        ]

    async def get_template_name(self, template_id: uuid.UUID) -> str | None:
        stmt = text("SELECT name FROM templates WHERE id = :id")
        result = await self.session.execute(stmt, {"id": template_id})
        row = result.first()
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Responsiveness — source tables (messages) for live data
    # ------------------------------------------------------------------

    async def hourly_pattern(
        self, start: date, end: date
    ) -> list[dict[str, Any]]:
        stmt = text(
            """
            SELECT
                EXTRACT(HOUR FROM created_at)::int AS hour,
                COUNT(*) FILTER (
                    WHERE direction = 'outbound'
                      AND delivery_status NOT IN ('draft','pending')
                )::int AS sent_n,
                COUNT(*) FILTER (WHERE direction = 'inbound')::int AS received_n
            FROM messages
            WHERE created_at >= :start AND created_at < :end
            GROUP BY EXTRACT(HOUR FROM created_at)
            ORDER BY hour ASC
            """
        )
        rows = await self.session.execute(
            stmt, {"start": start, "end": _next_day(end)}
        )
        return [
            {
                "hour": int(r[0]),
                "messages_sent": int(r[1]),
                "messages_received": int(r[2]),
                "response_rate": (
                    min(1.0, int(r[2]) / int(r[1])) if int(r[1]) else 0.0
                ),
            }
            for r in rows
        ]

    async def daily_pattern(
        self, start: date, end: date
    ) -> list[dict[str, Any]]:
        stmt = text(
            """
            SELECT
                (EXTRACT(ISODOW FROM created_at)::int - 1) AS dow,
                COUNT(*) FILTER (
                    WHERE direction = 'outbound'
                      AND delivery_status NOT IN ('draft','pending')
                )::int AS sent_n,
                COUNT(*) FILTER (WHERE direction = 'inbound')::int AS received_n
            FROM messages
            WHERE created_at >= :start AND created_at < :end
            GROUP BY EXTRACT(ISODOW FROM created_at)
            ORDER BY dow ASC
            """
        )
        rows = await self.session.execute(
            stmt, {"start": start, "end": _next_day(end)}
        )
        return [
            {
                "day_of_week": int(r[0]),
                "messages_sent": int(r[1]),
                "messages_received": int(r[2]),
                "response_rate": (
                    min(1.0, int(r[2]) / int(r[1])) if int(r[1]) else 0.0
                ),
            }
            for r in rows
        ]
