"""Settings module constants."""

from enum import StrEnum


class SettingScope(StrEnum):
    GLOBAL = "global"
    USER = "user"


# --- Typed registry (layered over the generic key/value store) ----------
# Each bool setting is stored as {"enabled": <bool>} in app_settings.value.

SETTING_AI_KILL_SWITCH = "ai.kill_switch"
SETTING_AI_AUTO_SEND_ENABLED = "ai.auto_send_enabled"
SETTING_AI_TEST_NUMBERS = "ai.test_numbers"
SETTING_AI_TAG_SUGGESTIONS_ENABLED = "ai.tag_suggestions_enabled"
SETTING_AI_RESPONSE_GENERATION_ENABLED = "ai.response_generation_enabled"
SETTING_AI_BUSINESS_CARD_MEDIA_ID = "ai.business_card_media_id"

AI_SETTING_DEFAULTS: dict[str, bool] = {
    SETTING_AI_KILL_SWITCH: False,
    SETTING_AI_AUTO_SEND_ENABLED: True,
    SETTING_AI_TAG_SUGGESTIONS_ENABLED: True,
    SETTING_AI_RESPONSE_GENERATION_ENABLED: True,
}

AI_TEST_NUMBERS_DEFAULT: dict[str, list[str]] = {"numbers": []}


# --- Operational toggles (piece 2) --------------------------------------
# JSON envelopes, scope="global". Shapes are distinct from the AI
# {"enabled": bool} envelope and the campaign {"rate": N} envelope.

SETTING_OPS_READ_ONLY_MODE = "ops.read_only_mode"
SETTING_OPS_TIMEZONE = "ops.timezone"
SETTING_OPS_BUSINESS_HOURS = "ops.business_hours"
SETTING_OPS_CAMPAIGN_DAILY_CAP = "ops.campaign_daily_cap"
SETTING_OPS_DELIVERY_FAILURE_RETRY = "ops.delivery_failure_retry"

OPS_DEFAULT_TIMEZONE = "UTC"
OPS_CAMPAIGN_DAILY_CAP_DEFAULT_LIMIT = 800  # DSD §10 throughput target

OPERATIONAL_SETTING_DEFAULTS: dict[str, dict] = {
    SETTING_OPS_READ_ONLY_MODE: {"enabled": False},
    SETTING_OPS_TIMEZONE: {"tz": OPS_DEFAULT_TIMEZONE},
    SETTING_OPS_BUSINESS_HOURS: {
        "enabled": False,
        "start": "09:00",
        "end": "18:00",
    },
    SETTING_OPS_CAMPAIGN_DAILY_CAP: {
        "enabled": True,
        "limit": OPS_CAMPAIGN_DAILY_CAP_DEFAULT_LIMIT,
    },
    SETTING_OPS_DELIVERY_FAILURE_RETRY: {
        "enabled": True,
    },
}


# --- ERP settings (Path C — ERP keys live in the same app_settings table) ----

SETTING_ERP_FISCAL_YEAR_START_MONTH = "erp.fiscal_year_start_month"
SETTING_ERP_BASE_CURRENCY = "erp.base_currency"
SETTING_ERP_DEFAULT_AR_ACCOUNT = "erp.default_ar_account"
SETTING_ERP_DEFAULT_AP_ACCOUNT = "erp.default_ap_account"
SETTING_ERP_DEFAULT_INVENTORY_ACCOUNT = "erp.default_inventory_account"
SETTING_ERP_DEFAULT_COGS_ACCOUNT = "erp.default_cogs_account"
SETTING_ERP_DEFAULT_REVENUE_ACCOUNT = "erp.default_revenue_account"
SETTING_ERP_CREDIT_CONTROL_ENABLED = "erp.credit_control_enabled"
SETTING_ERP_DOCUMENT_STORE = "erp.document_store"

ERP_SETTING_DEFAULTS: dict[str, dict] = {
    SETTING_ERP_FISCAL_YEAR_START_MONTH: {"month": 1},
    SETTING_ERP_BASE_CURRENCY: {"code": "AED"},
    SETTING_ERP_DEFAULT_AR_ACCOUNT: {"account_id": ""},
    SETTING_ERP_DEFAULT_AP_ACCOUNT: {"account_id": ""},
    SETTING_ERP_DEFAULT_INVENTORY_ACCOUNT: {"account_id": ""},
    SETTING_ERP_DEFAULT_COGS_ACCOUNT: {"account_id": ""},
    SETTING_ERP_DEFAULT_REVENUE_ACCOUNT: {"account_id": ""},
    SETTING_ERP_CREDIT_CONTROL_ENABLED: {"enabled": True},
    SETTING_ERP_DOCUMENT_STORE: {"backend": "postgres"},
}


# --- Market confidence thresholds (P0) ----------------------------------
# Admin-tunable three-band boundaries for the review queue.  Values are
# per-field confidence floors; the row confidence is the minimum of its
# fields.  auto_min ≥ this → AUTO;  review_min ≤ field < auto_min → PENDING;
# below review_min → stored UNRESOLVED (never mutates contact state).

SETTING_MARKET_CONFIDENCE_AUTO_MIN = "market.confidence.auto_min"
SETTING_MARKET_CONFIDENCE_REVIEW_MIN = "market.confidence.review_min"

MARKET_CONFIDENCE_DEFAULTS: dict[str, dict] = {
    SETTING_MARKET_CONFIDENCE_AUTO_MIN: {"value": 0.85},
    SETTING_MARKET_CONFIDENCE_REVIEW_MIN: {"value": 0.55},
}
