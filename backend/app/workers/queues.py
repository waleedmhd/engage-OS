"""Celery queue definitions and task routing.

Routes are kept here so each module's `tasks.py` only declares task names.
"""

QUEUE_DEFAULT = "default"
QUEUE_OUTBOUND = "outbound"
QUEUE_AI = "ai"
QUEUE_ANALYTICS = "analytics"

ALL_QUEUES = (
    QUEUE_DEFAULT,
    QUEUE_OUTBOUND,
    QUEUE_AI,
    QUEUE_ANALYTICS,
)

# NOTE: no `categorization.tasks.*` route — categorization runs inline via
# `CategorizationService.create_suggestion_sync` from `AIOrchestrator._decide`.
# There is no Celery task to route. See memory/stub_cleanup_2026_05_21.md.
TASK_ROUTES: dict[str, dict[str, str]] = {
    "messaging.tasks.*": {"queue": QUEUE_OUTBOUND},
    "campaigns.tasks.*": {"queue": QUEUE_OUTBOUND},
    "ai.tasks.*": {"queue": QUEUE_AI},
    "analytics.tasks.*": {"queue": QUEUE_ANALYTICS},
    "assignments.tasks.*": {"queue": QUEUE_DEFAULT},
    "contacts.tasks.*": {"queue": QUEUE_DEFAULT},
    "templates.tasks.*": {"queue": QUEUE_DEFAULT},
    "market.tasks.*": {"queue": QUEUE_DEFAULT},
    "inventory.tasks.*": {"queue": QUEUE_ANALYTICS},
    "erp_reporting.tasks.*": {"queue": QUEUE_DEFAULT},
}
