"""Engagement policy constants: outreach lifecycle states, regime timing, active-hours
configuration, opt-out keywords, and permanent delivery-failure codes (DSD §2-§8).
"""

from enum import StrEnum


class OutreachState(StrEnum):
    """Outreach lifecycle per the engagement follow-up policy.

    Cold track (§4.1) - template-based, pre-conversation:
      PENDING → OUTREACH_SENT → COLD_FOLLOWUP_SENT → UNRESPONSIVE

    In-window (§4.2-4.3) - free service messages, driven off conversation
    last-inbound timestamp + turn count:
      1 inbound → REENGAGE_1 → REENGAGE_2 → UNRESPONSIVE
      ≥2 inbound → RESCUE_1 → RESCUE_2 → UNRESPONSIVE

    Any inbound reply → CONVERTED (trumps all cadence states).
    """

    # Cold track (§4.1)
    PENDING = "PENDING"
    OUTREACH_SENT = "OUTREACH_SENT"
    COLD_FOLLOWUP_SENT = "COLD_FOLLOWUP_SENT"

    # In-window re-engage (§4.2): exactly 1 inbound, then silent
    REENGAGE_1 = "REENGAGE_1"
    REENGAGE_2 = "REENGAGE_2"

    # In-window rescue (§4.3): ≥2 inbound, mid-thread, then silent
    RESCUE_1 = "RESCUE_1"
    RESCUE_2 = "RESCUE_2"

    # Terminal
    CONVERTED = "CONVERTED"
    UNRESPONSIVE = "UNRESPONSIVE"
    UNDELIVERABLE = "UNDELIVERABLE"
    SUPPRESSED = "SUPPRESSED"


OUTREACH_TERMINAL_STATES: frozenset[OutreachState] = frozenset({
    OutreachState.CONVERTED,
    OutreachState.UNRESPONSIVE,
    OutreachState.UNDELIVERABLE,
    OutreachState.SUPPRESSED,
})

OUTREACH_COLD_STATES: frozenset[OutreachState] = frozenset({
    OutreachState.PENDING,
    OutreachState.OUTREACH_SENT,
    OutreachState.COLD_FOLLOWUP_SENT,
})

OUTREACH_REENGAGE_STATES: frozenset[OutreachState] = frozenset({
    OutreachState.REENGAGE_1,
    OutreachState.REENGAGE_2,
})

OUTREACH_RESCUE_STATES: frozenset[OutreachState] = frozenset({
    OutreachState.RESCUE_1,
    OutreachState.RESCUE_2,
})

# -------- regime timing (DSD §4) --------

# §4.1 Cold: ~24h after Touch 1, different time-of-day, aligned to active hours
COLD_FOLLOWUP_DELAY_HOURS: float = 24.0

# §4.2 Re-engage (1 inbound, then silent): free in-window follow-ups
REENGAGE_1_MIN_HOURS: float = 3.0
REENGAGE_1_MAX_HOURS: float = 6.0
REENGAGE_2_TARGET_HOURS: float = 23.0  # as late as possible inside window

# §4.3 Rescue (≥2 inbound, mid-thread silence): context-based, momentum-timed
RESCUE_1_MIN_HOURS: float = 1.0
RESCUE_1_MAX_HOURS: float = 2.0
RESCUE_2_MIN_HOURS: float = 6.0
RESCUE_2_MAX_HOURS: float = 12.0

# WhatsApp free window: 24 h from last inbound (re-opened on each new inbound)
FREE_WINDOW_HOURS: float = 24.0

# -------- active hours (DSD §4.3, configurable via settings) --------

DEFAULT_ACTIVE_HOURS_START: int = 8   # 08:00 local
DEFAULT_ACTIVE_HOURS_END: int = 21    # 21:00 local

# UAE weekend (configurable per market)
DEFAULT_WEEKEND_DAYS: frozenset[int] = frozenset({5, 6})  # Sat=5, Sun=6 (Python weekday)

# -------- opt-out keywords (§2 fast-path) --------

# Case-insensitive. Space-joined phrases are matched as substrings against the
# lowercased inbound message text (word-boundary not required - erring toward
# detection at the cost of an occasional false positive is the correct trade-off
# per the policy's "errs toward stopping when intent is ambiguous" rule).
OPT_OUT_KEYWORDS: frozenset[str] = frozenset({
    "stop",
    "unsubscribe",
    "unstop",
    "stopall",
    "cancel",
    "end",
    "quit",
    "do not message",
    "don't message",
    "dont message",
    "stop messaging",
    "stop contacting",
    "please stop",
    "remove me",
    "delete my number",
    "don't contact",
    "dont contact",
    "do not contact",
    "do not text",
    "no more messages",
    "take me off",
    "leave me alone",
    "不要再发",
    "不要联系",
    "لا ترسل",
    "توقف",
    "اريد الغاء",
    "حذف رقمي",
})


def detect_opt_out_keywords(text: str | None) -> bool:
    """Return True if *text* contains any opt-out keyword phrase.

    Case-insensitive substring match - errs toward detection (§2).
    """
    if not text:
        return False
    lowered = text.lower().strip()
    return any(kw in lowered for kw in OPT_OUT_KEYWORDS)


# -------- permanent delivery-failure codes (§3) --------

# Meta error codes that indicate the message *cannot ever* be delivered to this
# recipient. The message row should transition to FAILED → terminal; the
# corresponding outreach lifecycle goes to UNDELIVERABLE; the appropriate
# delivery-derived tag is auto-applied.
PERMANENT_FAILURE_CODES: frozenset[int] = frozenset({
    131026,  # Message undeliverable / recipient not a WhatsApp user
    131047,  # Message expired - recipient not on WhatsApp
    131049,  # Recipient phone number not on WhatsApp
    131051,  # Unable to send message - user is blocked
    131052,  # Number does not exist / invalid phone number
    131053,  # Unable to send - phone number not on WhatsApp
})


def is_permanent_failure(error_code: int | None) -> bool:
    """Return True if *error_code* is a known permanent delivery failure."""
    return error_code is not None and error_code in PERMANENT_FAILURE_CODES


def tag_for_failure_code(error_code: int | None) -> str | None:
    """Return the auto-apply tag name for a permanent-failure error code."""
    if error_code is None:
        return None
    if error_code in {131026, 131047, 131049, 131053}:
        return "NOT_ON_WHATSAPP"
    if error_code in {131052}:
        return "INVALID_NUMBER"
    if error_code in {131051}:
        return "UNDELIVERABLE"
    return "UNDELIVERABLE"


# -------- sweep cadence --------

ENGAGEMENT_SWEEP_INTERVAL_SECONDS: float = 120.0  # 2 minutes
