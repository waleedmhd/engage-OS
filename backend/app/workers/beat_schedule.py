"""Celery Beat schedule registry.

Each module appends its scheduled tasks here so Beat starts cleanly with
a single source of truth.
"""

from celery.schedules import crontab

from app.modules.assignments.constants import LOCK_EXPIRY_SWEEP_INTERVAL_SECONDS
from app.modules.campaigns.constants import SCHEDULER_TICK_SECONDS
from app.modules.engagement.constants import ENGAGEMENT_SWEEP_INTERVAL_SECONDS
from app.workers.queues import QUEUE_ANALYTICS, QUEUE_DEFAULT, QUEUE_OUTBOUND

BEAT_SCHEDULE: dict[str, dict] = {
    # Campaigns: scan for SCHEDULED/RECURRING runs whose time has come.
    "campaigns-scheduler-tick": {
        "task": "campaigns.tasks.scheduler_tick_task",
        "schedule": SCHEDULER_TICK_SECONDS,
        "options": {"queue": QUEUE_OUTBOUND},
    },
    # Assignments: reap conversation locks whose TTL has expired.
    "assignments-expire-stale-locks": {
        "task": "assignments.tasks.expire_stale_locks_task",
        "schedule": float(LOCK_EXPIRY_SWEEP_INTERVAL_SECONDS),
        "options": {"queue": QUEUE_DEFAULT},
    },
    # Contacts: sweep contacted→follow_up after 12h with no reply.
    "contacts-sweep-follow-up": {
        "task": "contacts.tasks.sweep_follow_up_task",
        "schedule": 600.0,
        "options": {"queue": QUEUE_DEFAULT},
    },
    # Engagement: scan for conversations needing follow-up scheduling (re-engage,
    # rescue, cold touch-2) — agent-engagement-policy §4.
    "engagement-sweep": {
        "task": "engagement.tasks.engagement_sweep_task",
        "schedule": ENGAGEMENT_SWEEP_INTERVAL_SECONDS,
        "options": {"queue": QUEUE_DEFAULT},
    },
    # Analytics: roll up yesterday's source data into the daily rollup tables.
    "analytics-aggregate-daily-metrics": {
        "task": "analytics.tasks.aggregate_daily_metrics_task",
        "schedule": crontab(hour=0, minute=15),
        "options": {"queue": QUEUE_ANALYTICS},
    },
    # Market: expire stale buy/sell messages past their per-side TTL.
    "market-expire-messages": {
        "task": "market.tasks.expire_market_messages_task",
        "schedule": 300.0,
        "options": {"queue": QUEUE_DEFAULT},
    },
}
