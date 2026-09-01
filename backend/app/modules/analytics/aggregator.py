"""Pure-SQL upserts that populate the analytics rollup tables.

Called from ``analytics.tasks.aggregate_daily_metrics_task`` (sync Celery
context). Each helper is a single ``INSERT ... ON CONFLICT DO UPDATE`` so
re-running for any historical date overwrites that day's row — idempotent
by construction.

We deliberately keep everything in raw SQL (``sqlalchemy.text``) rather
than ORM loops: the worker scans potentially millions of rows per day, so
a single grouped INSERT is the difference between sub-second and minutes.

Conventions:
  * ``:target_date`` parameter — the calendar day being computed, UTC.
  * Direction / status string literals match the enum ``.value`` strings
    in ``messaging/constants.py`` and ``campaigns/constants.py``.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.analytics.constants import ATTRIBUTION_WINDOW_DAYS

_GLOBAL_UPSERT_SQL = text(
    """
    WITH
    ai AS (
        SELECT
            COALESCE(SUM(cost_estimate), 0)::numeric(12,4) AS ai_spend,
            COUNT(*) AS ai_calls,
            COUNT(*) FILTER (WHERE error IS NOT NULL) AS ai_errors,
            AVG(latency_ms)::int AS ai_avg_latency,
            COALESCE(SUM((response->'usage'->>'input_tokens')::int), 0)::int AS tokens_in,
            COALESCE(SUM((response->'usage'->>'output_tokens')::int), 0)::int AS tokens_out
        FROM ai_events
        WHERE created_at >= :day_start AND created_at < :day_end
    ),
    msg AS (
        SELECT
            COALESCE(SUM(cost) FILTER (
                WHERE direction = 'outbound'
                  AND delivery_status IN ('delivered','read')
            ), 0)::numeric(12,4) AS msg_cost,
            COUNT(*) FILTER (
                WHERE direction = 'outbound'
                  AND delivery_status NOT IN ('draft','pending','failed')
            ) AS msgs_sent,
            COUNT(*) FILTER (
                WHERE direction = 'outbound'
                  AND delivery_status IN ('delivered','read')
            ) AS msgs_delivered,
            COUNT(*) FILTER (
                WHERE direction = 'outbound' AND delivery_status = 'failed'
            ) AS msgs_failed,
            COUNT(*) FILTER (WHERE direction = 'inbound') AS msgs_received,
            COUNT(*) FILTER (
                WHERE direction = 'outbound'
                  AND delivery_status IN ('delivered','read')
            ) * 0.18::numeric(12,4) AS meta_cost_aed,
            COUNT(*) FILTER (
                WHERE direction = 'outbound'
                  AND delivery_status IN ('delivered','read')
            ) * 0.049::numeric(12,4) AS meta_cost_usd
        FROM messages
        WHERE created_at >= :day_start AND created_at < :day_end
    )
    INSERT INTO analytics_daily_metrics (
        metric_date,
        ai_spend_usd, ai_call_count, ai_error_count,
        tokens_input, tokens_output, ai_avg_latency_ms,
        message_cost_usd, meta_cost_aed,
        messages_sent, messages_delivered, messages_failed,
        messages_received, response_rate, ai_handled_pct, total_cost_usd
    )
    SELECT
        :target_date,
        ai.ai_spend, ai.ai_calls, ai.ai_errors,
        ai.tokens_in, ai.tokens_out, ai.ai_avg_latency,
        msg.msg_cost, msg.meta_cost_aed,
        msg.msgs_sent, msg.msgs_delivered, msg.msgs_failed,
        msg.msgs_received,
        CASE WHEN msg.msgs_sent = 0 THEN 0
             ELSE LEAST(1.0, msg.msgs_received::numeric / msg.msgs_sent)
        END AS response_rate,
        0 AS ai_handled_pct,  -- conversation-state breakdown deferred
        (ai.ai_spend + msg.msg_cost + msg.meta_cost_usd)::numeric(12,4) AS total_cost
    FROM ai, msg
    ON CONFLICT (metric_date) DO UPDATE SET
        ai_spend_usd = EXCLUDED.ai_spend_usd,
        ai_call_count = EXCLUDED.ai_call_count,
        ai_error_count = EXCLUDED.ai_error_count,
        tokens_input = EXCLUDED.tokens_input,
        tokens_output = EXCLUDED.tokens_output,
        ai_avg_latency_ms = EXCLUDED.ai_avg_latency_ms,
        message_cost_usd = EXCLUDED.message_cost_usd,
        meta_cost_aed = EXCLUDED.meta_cost_aed,
        messages_sent = EXCLUDED.messages_sent,
        messages_delivered = EXCLUDED.messages_delivered,
        messages_failed = EXCLUDED.messages_failed,
        messages_received = EXCLUDED.messages_received,
        response_rate = EXCLUDED.response_rate,
        ai_handled_pct = EXCLUDED.ai_handled_pct,
        total_cost_usd = EXCLUDED.total_cost_usd,
        updated_at = now()
    """
)


_CAMPAIGN_UPSERT_SQL = text(
    """
    WITH
    -- 1) Recipient-level counts grouped by campaign for the target day.
    --    `sent_at::date = :target_date` defines membership in the day's row.
    recip AS (
        SELECT
            cr.campaign_id,
            COUNT(*) FILTER (
                WHERE cr.status IN ('sent','delivered','failed')
            ) AS sent_n,
            COUNT(*) FILTER (
                WHERE cr.delivered_at IS NOT NULL
                  AND cr.delivered_at::date = :target_date
            ) AS delivered_n,
            COUNT(*) FILTER (
                WHERE cr.failed_at IS NOT NULL
                  AND cr.failed_at::date = :target_date
            ) AS failed_n,
            COUNT(*) FILTER (WHERE cr.responded = TRUE) AS responded_n
        FROM campaign_recipients cr
        WHERE cr.sent_at IS NOT NULL AND cr.sent_at::date = :target_date
        GROUP BY cr.campaign_id
    ),
    -- 2) Send/delivery cost: sum messages.cost for outbound messages linked
    --    to the day's recipients via campaign_recipients.message_id.
    msg_cost AS (
        SELECT
            cr.campaign_id,
            COALESCE(SUM(m.cost), 0)::numeric(12,4) AS message_cost
        FROM campaign_recipients cr
        JOIN messages m ON m.id = cr.message_id
        WHERE cr.sent_at IS NOT NULL AND cr.sent_at::date = :target_date
          AND m.delivery_status IN ('delivered','read','sent','failed')
        GROUP BY cr.campaign_id
    ),
    -- 3) AI spend attributable to the campaign's conversations on the day.
    --    Conversation linkage: campaign_recipient → message → conversation_id.
    ai_cost AS (
        SELECT
            cr.campaign_id,
            COALESCE(SUM(ae.cost_estimate), 0)::numeric(12,4) AS ai_spend,
            COALESCE(SUM((ae.response->'usage'->>'input_tokens')::int), 0)::int AS tokens_in,
            COALESCE(SUM((ae.response->'usage'->>'output_tokens')::int), 0)::int AS tokens_out
        FROM campaign_recipients cr
        JOIN messages m ON m.id = cr.message_id
        JOIN ai_events ae ON ae.conversation_id = m.conversation_id
        WHERE cr.sent_at IS NOT NULL AND cr.sent_at::date = :target_date
          AND ae.created_at >= :day_start AND ae.created_at < :day_end
        GROUP BY cr.campaign_id
    ),
    -- 4) Last-touch revenue attribution within the configured window.
    --    For each contact whose responded recipient row sits inside the
    --    window, pick the MOST RECENT campaign they responded to and credit
    --    that contact's revenue_attributed to it. Restricted to contacts
    --    whose last-touch landed on :target_date so the row belongs to one day.
    last_touch AS (
        SELECT DISTINCT ON (cr.contact_id)
            cr.contact_id,
            cr.campaign_id,
            cr.sent_at::date AS touched_date
        FROM campaign_recipients cr
        WHERE cr.responded = TRUE
          AND cr.sent_at >= (CAST(:target_date AS date) - (:attribution_days * INTERVAL '1 day'))
          AND cr.sent_at::date <= :target_date
        ORDER BY cr.contact_id, cr.sent_at DESC
    ),
    revenue AS (
        SELECT
            lt.campaign_id,
            COALESCE(SUM(c.revenue_attributed), 0)::numeric(14,2) AS revenue_attributed
        FROM last_touch lt
        JOIN contacts c ON c.id = lt.contact_id
        WHERE lt.touched_date = :target_date
        GROUP BY lt.campaign_id
    )
    INSERT INTO analytics_campaign_daily_metrics (
        campaign_id, metric_date,
        recipients_sent, recipients_delivered, recipients_failed,
        recipients_responded, response_rate, conversion_rate,
        revenue_attributed_usd, ai_spend_usd, tokens_input, tokens_output,
        message_cost_usd, meta_cost_aed,
        total_cost_usd, roi
    )
    SELECT
        r.campaign_id, :target_date,
        r.sent_n, r.delivered_n, r.failed_n, r.responded_n,
        CASE WHEN r.delivered_n = 0 THEN 0
             ELSE LEAST(1.0, r.responded_n::numeric / r.delivered_n)
        END AS response_rate,
        CASE WHEN r.delivered_n = 0 THEN 0
             ELSE LEAST(1.0, r.responded_n::numeric / r.delivered_n)
        END AS conversion_rate,
        COALESCE(rev.revenue_attributed, 0),
        COALESCE(ai.ai_spend, 0),
        COALESCE(ai.tokens_in, 0),
        COALESCE(ai.tokens_out, 0),
        COALESCE(mc.message_cost, 0),
        r.delivered_n * 0.18::numeric(12,4),
        (COALESCE(ai.ai_spend, 0) + COALESCE(mc.message_cost, 0)
         + r.delivered_n * 0.049)::numeric(12,4),
        CASE
            WHEN (COALESCE(ai.ai_spend, 0) + COALESCE(mc.message_cost, 0)
                  + r.delivered_n * 0.049) = 0
                THEN NULL
            -- Capped at the column's ceiling: revenue is numeric(14,2) and the
            -- divisor can be a small fraction, so an uncapped ratio overflows
            -- numeric(10,4) on ordinary data. Same guard as the rates above.
            ELSE LEAST(999999.9999, COALESCE(rev.revenue_attributed, 0)
                  / (COALESCE(ai.ai_spend, 0) + COALESCE(mc.message_cost, 0)
                     + r.delivered_n * 0.049))::numeric(10,4)
        END AS roi
    FROM recip r
    LEFT JOIN msg_cost mc ON mc.campaign_id = r.campaign_id
    LEFT JOIN ai_cost ai ON ai.campaign_id = r.campaign_id
    LEFT JOIN revenue rev ON rev.campaign_id = r.campaign_id
    ON CONFLICT (campaign_id, metric_date) DO UPDATE SET
        recipients_sent = EXCLUDED.recipients_sent,
        recipients_delivered = EXCLUDED.recipients_delivered,
        recipients_failed = EXCLUDED.recipients_failed,
        recipients_responded = EXCLUDED.recipients_responded,
        response_rate = EXCLUDED.response_rate,
        conversion_rate = EXCLUDED.conversion_rate,
        revenue_attributed_usd = EXCLUDED.revenue_attributed_usd,
        ai_spend_usd = EXCLUDED.ai_spend_usd,
        tokens_input = EXCLUDED.tokens_input,
        tokens_output = EXCLUDED.tokens_output,
        message_cost_usd = EXCLUDED.message_cost_usd,
        meta_cost_aed = EXCLUDED.meta_cost_aed,
        total_cost_usd = EXCLUDED.total_cost_usd,
        roi = EXCLUDED.roi,
        updated_at = now()
    """
)


def upsert_global_daily(session: Session, target_date: date) -> None:
    """Compute and upsert the global daily rollup row for ``target_date``."""
    session.execute(
        _GLOBAL_UPSERT_SQL,
        {
            "target_date": target_date,
            "day_start": target_date,
            "day_end": _next_day(target_date),
        },
    )


def upsert_campaign_daily(session: Session, target_date: date) -> int:
    """Compute per-campaign rollup rows for ``target_date``.

    Returns the number of campaign rows touched (inserted or updated) on
    this run — used for task telemetry.
    """
    result = session.execute(
        _CAMPAIGN_UPSERT_SQL,
        {
            "target_date": target_date,
            "day_start": target_date,
            "day_end": _next_day(target_date),
            "attribution_days": ATTRIBUTION_WINDOW_DAYS,
        },
    )
    return result.rowcount or 0  # type: ignore[attr-defined]


_TEMPLATE_UPSERT_SQL = text(
    """
    WITH
    -- Campaign recipients for the day joined through to templates.
    recip AS (
        SELECT
            t.id AS template_id,
            t.name AS template_name,
            cr.campaign_id,
            COUNT(*) FILTER (
                WHERE cr.status IN ('sent','delivered','failed')
            ) AS sent_n,
            COUNT(*) FILTER (
                WHERE cr.delivered_at IS NOT NULL
                  AND cr.delivered_at::date = :target_date
            ) AS delivered_n,
            COUNT(*) FILTER (WHERE cr.responded = TRUE) AS responded_n
        FROM campaign_recipients cr
        JOIN campaigns c ON c.id = cr.campaign_id
        JOIN templates t ON t.id = c.template_id
        WHERE cr.sent_at IS NOT NULL AND cr.sent_at::date = :target_date
        GROUP BY t.id, t.name, cr.campaign_id
    ),
    -- Per-template aggregation across all campaigns that used it on this day.
    tmpl AS (
        SELECT
            template_id,
            template_name,
            COUNT(DISTINCT campaign_id)::int AS campaigns_used,
            SUM(sent_n)::int AS sent_n,
            SUM(delivered_n)::int AS delivered_n,
            SUM(responded_n)::int AS responded_n
        FROM recip
        GROUP BY template_id, template_name
    ),
    -- Message cost per template on the day.
    msg_cost AS (
        SELECT
            t.id AS template_id,
            COALESCE(SUM(m.cost), 0)::numeric(12,4) AS message_cost
        FROM campaign_recipients cr
        JOIN campaigns c ON c.id = cr.campaign_id
        JOIN templates t ON t.id = c.template_id
        JOIN messages m ON m.id = cr.message_id
        WHERE cr.sent_at IS NOT NULL AND cr.sent_at::date = :target_date
          AND m.delivery_status IN ('delivered','read','sent','failed')
        GROUP BY t.id
    ),
    -- AI spend per template on the day.
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
        WHERE cr.sent_at IS NOT NULL AND cr.sent_at::date = :target_date
          AND ae.created_at >= :day_start AND ae.created_at < :day_end
        GROUP BY t.id
    )
    INSERT INTO analytics_template_daily_metrics (
        template_id, template_name, metric_date,
        campaigns_used, recipients_sent, recipients_delivered,
        recipients_responded, response_rate,
        message_cost_usd, meta_cost_aed,
        ai_spend_usd, tokens_input, tokens_output, total_cost_usd
    )
    SELECT
        tmpl.template_id,
        tmpl.template_name,
        :target_date,
        tmpl.campaigns_used,
        tmpl.sent_n,
        tmpl.delivered_n,
        tmpl.responded_n,
        CASE WHEN tmpl.delivered_n = 0 THEN 0
             ELSE LEAST(1.0, tmpl.responded_n::numeric / tmpl.delivered_n)
        END AS response_rate,
        COALESCE(mc.message_cost, 0),
        tmpl.delivered_n * 0.18::numeric(12,4),
        COALESCE(ai.ai_spend, 0),
        COALESCE(ai.tokens_in, 0),
        COALESCE(ai.tokens_out, 0),
        (COALESCE(ai.ai_spend, 0) + COALESCE(mc.message_cost, 0)
         + tmpl.delivered_n * 0.049)::numeric(12,4)
    FROM tmpl
    LEFT JOIN msg_cost mc ON mc.template_id = tmpl.template_id
    LEFT JOIN ai_cost ai ON ai.template_id = tmpl.template_id
    ON CONFLICT (template_id, metric_date) DO UPDATE SET
        template_name = EXCLUDED.template_name,
        campaigns_used = EXCLUDED.campaigns_used,
        recipients_sent = EXCLUDED.recipients_sent,
        recipients_delivered = EXCLUDED.recipients_delivered,
        recipients_responded = EXCLUDED.recipients_responded,
        response_rate = EXCLUDED.response_rate,
        message_cost_usd = EXCLUDED.message_cost_usd,
        meta_cost_aed = EXCLUDED.meta_cost_aed,
        ai_spend_usd = EXCLUDED.ai_spend_usd,
        tokens_input = EXCLUDED.tokens_input,
        tokens_output = EXCLUDED.tokens_output,
        total_cost_usd = EXCLUDED.total_cost_usd,
        updated_at = now()
    """
)

_HOURLY_UPSERT_SQL = text(
    """
    WITH
    hourly AS (
        SELECT
            EXTRACT(HOUR FROM created_at)::int AS hour,
            COUNT(*) FILTER (
                WHERE direction = 'outbound'
                  AND delivery_status NOT IN ('draft','pending')
            ) AS sent_n,
            COUNT(*) FILTER (WHERE direction = 'inbound') AS received_n
        FROM messages
        WHERE created_at >= :day_start AND created_at < :day_end
        GROUP BY EXTRACT(HOUR FROM created_at)
    )
    INSERT INTO analytics_hourly_metrics (
        metric_date, hour,
        messages_sent, messages_received, response_rate
    )
    SELECT
        :target_date,
        hour,
        sent_n,
        received_n,
        CASE WHEN sent_n = 0 THEN 0
             ELSE LEAST(1.0, received_n::numeric / sent_n)
        END AS response_rate
    FROM hourly
    ON CONFLICT (metric_date, hour) DO UPDATE SET
        messages_sent = EXCLUDED.messages_sent,
        messages_received = EXCLUDED.messages_received,
        response_rate = EXCLUDED.response_rate,
        updated_at = now()
    """
)


def upsert_template_daily(session: Session, target_date: date) -> int:
    """Compute per-template rollup rows for ``target_date``.

    Only templates that were used in campaigns whose recipients were active
    on this day will produce rows — unused templates are excluded.
    """
    result = session.execute(
        _TEMPLATE_UPSERT_SQL,
        {
            "target_date": target_date,
            "day_start": target_date,
            "day_end": _next_day(target_date),
        },
    )
    return result.rowcount or 0  # type: ignore[attr-defined]


def upsert_hourly_metrics(session: Session, target_date: date) -> int:
    """Compute per-hour responsiveness rows for ``target_date``."""
    result = session.execute(
        _HOURLY_UPSERT_SQL,
        {
            "target_date": target_date,
            "day_start": target_date,
            "day_end": _next_day(target_date),
        },
    )
    return result.rowcount or 0  # type: ignore[attr-defined]


def _next_day(d: date) -> date:
    from datetime import timedelta

    return d + timedelta(days=1)
