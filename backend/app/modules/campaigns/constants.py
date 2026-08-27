"""Campaign enums and lifecycle configuration (DSD §4.7)."""

from enum import StrEnum


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    DISPATCHING = "dispatching"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CampaignType(StrEnum):
    IMMEDIATE = "immediate"
    SCHEDULED = "scheduled"
    RECURRING = "recurring"


class CampaignRecipientStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class ComplianceCode(StrEnum):
    TEMPLATE_NOT_APPROVED = "template_not_approved"
    NO_RECIPIENTS = "no_recipients"
    OUTSIDE_SESSION_WINDOW = "outside_session_window"
    INVALID_CRON = "invalid_cron"
    SCHEDULED_AT_IN_PAST = "scheduled_at_in_past"


# State-machine — single source of truth. Service rejects illegal transitions.
# Terminal states (COMPLETED, FAILED, CANCELLED) have no outgoing edges.
ALLOWED_TRANSITIONS: dict[CampaignStatus, set[CampaignStatus]] = {
    CampaignStatus.DRAFT: {CampaignStatus.VALIDATING, CampaignStatus.CANCELLED},
    CampaignStatus.VALIDATING: {
        CampaignStatus.SCHEDULED,
        CampaignStatus.FAILED,
        CampaignStatus.DRAFT,
    },
    CampaignStatus.SCHEDULED: {
        CampaignStatus.QUEUED,
        CampaignStatus.CANCELLED,
        CampaignStatus.SCHEDULED,  # recurring re-arm
    },
    CampaignStatus.QUEUED: {
        CampaignStatus.DISPATCHING,
        CampaignStatus.CANCELLED,
    },
    CampaignStatus.DISPATCHING: {
        CampaignStatus.COMPLETED,
        CampaignStatus.SCHEDULED,  # recurring: re-arm after run
        CampaignStatus.CANCELLED,
        CampaignStatus.FAILED,
    },
    CampaignStatus.COMPLETED: set(),
    CampaignStatus.FAILED: set(),
    CampaignStatus.CANCELLED: set(),
}


# ----------------------------------------------------------- batch + throttling

# Recipients dispatched per Celery batch task. Tuned so a single task fits
# comfortably in the visibility timeout while keeping fan-out manageable.
CAMPAIGN_BATCH_SIZE = 100

# Fallback used only if the AppSetting row is missing.
CAMPAIGN_DEFAULT_RATE_PER_SEC = 10

# Session-window check (24-hour rule) for non-template free-form sends.
CAMPAIGN_SESSION_WINDOW_HOURS = 24

# Beat tick cadence for the scheduler scan task.
SCHEDULER_TICK_SECONDS = 60

# Redis keys
CAMPAIGN_LOCK_REDIS_KEY = "campaign:lock:{campaign_id}"
CAMPAIGN_LOCK_TTL_SECONDS = 300  # 5 minutes — longer than any single dispatch loop
CAMPAIGN_THROTTLE_REDIS_KEY = "campaign:throttle:{campaign_id}:{epoch_sec}"
CAMPAIGN_THROTTLE_KEY_TTL = 2  # seconds; window keys self-expire

# completion poll: how often complete_campaign_task re-checks recipient progress.
CAMPAIGN_COMPLETION_POLL_SECONDS = 30

# Settings keys (AppSetting table, scope='global').
SETTING_CAMPAIGN_RATE_PER_SEC = "campaign.global_rate_per_second"
SETTING_CAMPAIGN_BATCH_SIZE = "campaign.batch_size"

# Operational toggles (piece 2) — settings module owns the canonical keys.
from app.modules.settings.constants import (  # noqa: E402,F401
    SETTING_OPS_BUSINESS_HOURS,
    SETTING_OPS_CAMPAIGN_DAILY_CAP,
    SETTING_OPS_TIMEZONE,
)
