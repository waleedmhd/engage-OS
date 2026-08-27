"""Market module enums and seed data (DSD section 3 through 6)."""

from enum import StrEnum


class MarketSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class ReviewStatus(StrEnum):
    AUTO = "AUTO"
    PENDING = "PENDING"
    REVIEWED = "REVIEWED"
    DISMISSED = "DISMISSED"
    UNREVIEWED_EXPIRED = "UNREVIEWED_EXPIRED"


class MessageStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class MessageSource(StrEnum):
    GROUP = "group"
    CHANNEL = "channel"
    DM = "dm"


class ProductTier(StrEnum):
    BASE = "base"
    PLUS = "plus"
    PRO = "pro"
    PRO_MAX = "pro max"
    ULTRA = "ultra"
    UNKNOWN = "unknown"


class ResolverKind(StrEnum):
    KEYWORD = "keyword"
    LLM = "llm"


class AliasSource(StrEnum):
    SEED = "seed"
    LLM_LEARNED = "llm_learned"
    HUMAN = "human"


class DealStage(StrEnum):
    MATCHED = "matched"
    CONTACTED = "contacted"
    NEGOTIATING = "negotiating"
    CONFIRMED = "confirmed"
    CLOSED = "closed"
    LOST = "lost"


class OutreachStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


# Confidence thresholds (DSD §4).
KEYWORD_CONFIDENCE = 0.95
LLM_CONFIDENCE_FLOOR = 0.60

# Expiry: BUY leads ~45 min; SELL leads ~48 hours (DSD §6.3).
BUY_EXPIRY_MINUTES = 45
SELL_EXPIRY_HOURS = 48

# Seed product catalog — Apple + Samsung phone trees (DSD §5).
SEED_PRODUCTS: list[dict] = [
    # Apple
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 17 pro max", "tier": "pro max"},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 17 pro", "tier": "pro"},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 17", "tier": "base"},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 16 pro max", "tier": "pro max"},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 16 pro", "tier": "pro"},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 16 plus", "tier": "plus"},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 16", "tier": "base"},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 15 pro max", "tier": "pro max"},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 15 pro", "tier": "pro"},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 15", "tier": "base"},
    # Samsung
    {"brand": "Samsung", "family": "Galaxy S", "canonical_name": "samsung s25 ultra", "tier": "ultra"},
    {"brand": "Samsung", "family": "Galaxy S", "canonical_name": "samsung s25", "tier": "base"},
    {"brand": "Samsung", "family": "Galaxy S", "canonical_name": "samsung s24 ultra", "tier": "ultra"},
    {"brand": "Samsung", "family": "Galaxy S", "canonical_name": "samsung s24", "tier": "base"},
    {"brand": "Samsung", "family": "Galaxy Z", "canonical_name": "samsung z fold 6", "tier": "ultra"},
    {"brand": "Samsung", "family": "Galaxy Z", "canonical_name": "samsung z flip 6", "tier": "pro"},
]

# Seed aliases — common misspellings and shorthand (DSD §4.3, §5).
SEED_ALIASES: list[dict] = [
    # iPhone 17
    {"canonical_name": "iphone 17 pro max", "alias": "17pm", "source": "seed"},
    {"canonical_name": "iphone 17 pro max", "alias": "17 pro max", "source": "seed"},
    {"canonical_name": "iphone 17 pro", "alias": "17p", "source": "seed"},
    {"canonical_name": "iphone 17 pro", "alias": "17 pro", "source": "seed"},
    {"canonical_name": "iphone 17", "alias": "i17", "source": "seed"},
    # iPhone 16
    {"canonical_name": "iphone 16 pro max", "alias": "16pm", "source": "seed"},
    {"canonical_name": "iphone 16 pro max", "alias": "16 pro max", "source": "seed"},
    {"canonical_name": "iphone 16 pro max", "alias": "i16pm", "source": "seed"},
    {"canonical_name": "iphone 16 pro", "alias": "16p", "source": "seed"},
    {"canonical_name": "iphone 16 pro", "alias": "16 pro", "source": "seed"},
    {"canonical_name": "iphone 16 pro", "alias": "i16p", "source": "seed"},
    {"canonical_name": "iphone 16 plus", "alias": "16 plus", "source": "seed"},
    {"canonical_name": "iphone 16", "alias": "i16", "source": "seed"},
    {"canonical_name": "iphone 16", "alias": "iph16", "source": "seed"},
    # iPhone 15
    {"canonical_name": "iphone 15 pro max", "alias": "15pm", "source": "seed"},
    {"canonical_name": "iphone 15 pro max", "alias": "15 pro max", "source": "seed"},
    {"canonical_name": "iphone 15 pro", "alias": "15p", "source": "seed"},
    {"canonical_name": "iphone 15 pro", "alias": "15 pro", "source": "seed"},
    {"canonical_name": "iphone 15", "alias": "i15", "source": "seed"},
    # Samsung S25
    {"canonical_name": "samsung s25 ultra", "alias": "s25u", "source": "seed"},
    {"canonical_name": "samsung s25 ultra", "alias": "s25 ultra", "source": "seed"},
    {"canonical_name": "samsung s25", "alias": "s25", "source": "seed"},
    # Samsung S24
    {"canonical_name": "samsung s24 ultra", "alias": "s24u", "source": "seed"},
    {"canonical_name": "samsung s24 ultra", "alias": "s24 ultra", "source": "seed"},
    {"canonical_name": "samsung s24", "alias": "s24", "source": "seed"},
    # Samsung Z
    {"canonical_name": "samsung z fold 6", "alias": "zfold6", "source": "seed"},
    {"canonical_name": "samsung z fold 6", "alias": "fold 6", "source": "seed"},
    {"canonical_name": "samsung z flip 6", "alias": "zflip6", "source": "seed"},
    {"canonical_name": "samsung z flip 6", "alias": "flip 6", "source": "seed"},
    # Brand-level misspellings
    {"canonical_name": "iphone 16 pro max", "alias": "iphone16 promax", "source": "seed"},
    {"canonical_name": "iphone 16 pro", "alias": "iphone16 pro", "source": "seed"},
    {"canonical_name": "samsung s25 ultra", "alias": "sam s25u", "source": "seed"},
    {"canonical_name": "samsung s25", "alias": "samsng s25", "source": "seed"},
    {"canonical_name": "samsung s24 ultra", "alias": "sams s24u", "source": "seed"},
]

# Buy/sell keyword patterns for side classification (DSD §4.1).
BUY_PATTERNS: tuple[str, ...] = (
    "wtb", "want to buy", "looking for", "looking to buy", "need",
    "in search of", "iso", "i want", "i need", "buy", "buying",
    "wanted", "wanted to buy", "lf", "lf ", "searching for",
    "anyone selling", "anyone have", "anyone got",
)

SELL_PATTERNS: tuple[str, ...] = (
    "wts", "want to sell", "for sale", "selling", "available",
    "have stock", "offering", "selling my", "sell", "brand new",
    "brandnew", "sealed", "unused", "unopened", "new sealed",
    "mint condition", "in stock", "available now", "dm me",
    "interested dm", "serious buyers", "best price",
)
