"""Messaging enums and retry/delay configuration (DSD §4.1, §4.4)."""

from enum import StrEnum


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class SenderType(StrEnum):
    CONTACT = "contact"
    AGENT = "agent"
    AI = "ai"
    SYSTEM = "system"


class MessageDeliveryStatus(StrEnum):
    PENDING = "pending"
    DRAFT = "draft"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class MessageType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    CONTACT = "contact"


# Outbound retry policy (DSD §4.1).
# Index = attempt number (0-based). attempt 1 is immediate, attempt 2 waits 30s, etc.
RETRY_DELAY_SECONDS: list[int] = [0, 30, 120, 600]
MAX_SEND_ATTEMPTS: int = len(RETRY_DELAY_SECONDS)  # 4 attempts total before terminal failure.

# Delivery-failure retry schedule: when Meta reports the message couldn't be
# delivered (HTTP 200 + status=failed callback), re-queue for re-send on an
# escalating schedule. Separate budget from send-attempt retries.
DELIVERY_FAILURE_RETRY_DELAYS: list[int] = [900, 10800, 43200]  # 15m, 3h, 12h
MAX_DELIVERY_RETRIES: int = len(DELIVERY_FAILURE_RETRY_DELAYS)  # 3

# Realistic delay buckets in seconds (DSD §4.4).
# Tightened to keep total reply latency ≤ 7 s including API round-trip.
DELAY_SHORT_RANGE = (1, 3)          # 1-15 words
DELAY_MEDIUM_RANGE = (2, 5)         # 16-60 words
DELAY_LONG_RANGE = (4, 6)           # 60+ words
DELAY_VARIANCE = 0.10               # ±10%
