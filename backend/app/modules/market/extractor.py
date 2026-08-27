"""Deterministic market message extractor -- Python port of listener/src/filter/pipeline.js
Pass A (text cleaning only), Pass B (intent/side), and Pass C (attribute extraction).

Trust flag: get_settings().MARKET_TRUST_LISTENER
When True (default), backend trusts listener's precomputed filter_results.
When False, this extractor runs at ingestion time.

All pattern constants are defined inline, matching listener/src/filter/constants.js
and pipeline.js exactly. Do NOT refactor or "improve" the JS logic -- behavioral
identity with the JS is the requirement.
"""

from __future__ import annotations

import re
from typing import Any

# =============================================================================
# Helpers -- exact ports of JS matchAny, matchNamedPatterns, extractFirstMatch,
#            extractNumber
# =============================================================================


def match_any(text: str, patterns: list[str | re.Pattern]) -> bool:
    """Port of JS matchAny(text, patterns)."""
    for p in patterns:
        if isinstance(p, str):
            if p.lower() in text.lower():
                return True
        elif p.search(text):
            return True
    return False


def match_named_patterns(
    text: str, pattern_map: dict[str, list[Any]],
) -> dict[str, bool]:
    """Port of JS matchNamedPatterns(text, patternMap).
    Returns {key: True} for each named group with at least one match."""
    hits: dict[str, bool] = {}
    for name, patterns in pattern_map.items():
        for p in patterns:
            if isinstance(p, str):
                if p.lower() in text.lower():
                    hits[name] = True
                    break
            elif p.search(text):
                hits[name] = True
                break
    return hits


def extract_first_match(
    text: str, patterns: list[str | re.Pattern],
) -> str | None:
    """Port of JS extractFirstMatch(text, patterns)."""
    for p in patterns:
        if isinstance(p, re.Pattern):
            m = p.search(text)
            if m:
                return m.group(0)
        elif isinstance(p, str) and p.lower() in text.lower():
            return p
    return None


def extract_number(text: str, pattern: re.Pattern) -> int | None:
    """Port of JS extractNumber(text, pattern)."""
    m = pattern.search(text)
    if m:
        try:
            return int(m.group(1))
        except (ValueError, IndexError):
            return None
    return None


# =============================================================================
# Pass A -- Text cleaning only (noise rejection stays listener-side)
# =============================================================================

_PASS_A_CLEANING: list[tuple[re.Pattern, str]] = [
    (re.compile(r"This broadcast is powered by.*$", re.MULTILINE), ""),
    (re.compile(r"Recommended Member in.*$", re.MULTILINE), ""),
    (re.compile(r"From .* Member ID \d+.*$", re.MULTILINE), ""),
    (re.compile(r"Platinum .* Member.*$", re.MULTILINE), ""),
    (re.compile(r"━━+"), ""),
    (re.compile(r"_{3,}"), ""),
    (re.compile(r"\*{3,}"), ""),
]


def clean_text(text: str) -> str:
    """Apply Pass A text cleaning (JS passA steps 6-7)."""
    result = text
    for pat, replacement in _PASS_A_CLEANING:
        result = pat.sub(replacement, result)
    return result.strip()


# =============================================================================
# Pattern constants -- exact port of listener/src/filter/constants.js
# =============================================================================

# --- Pass B: Intent & side ---

INTENT_PATTERNS: dict[str, list[str | re.Pattern]] = {
    "SIDE_BUY": [
        re.compile(r"\bWTB\b"),
        re.compile(r"\bWtb\b"),
        re.compile(r"Want to buy", re.IGNORECASE),
        re.compile(r"\*Want to buy\*", re.IGNORECASE),
        re.compile(r"Looking to Buy", re.IGNORECASE),
        re.compile(r"I need(?:\s+a|\s+an|\s+\d+)?\b", re.IGNORECASE),
        re.compile(r"Looking for\b", re.IGNORECASE),
        re.compile(r"anyone (?:have|got|selling)", re.IGNORECASE),
        re.compile(r"buyer(?:\s|$)", re.IGNORECASE),
        re.compile(r"buying", re.IGNORECASE),
    ],
    "SIDE_SELL": [
        re.compile(r"\bWTS\b"),
        re.compile(r"\bW T S\b"),
        re.compile(r"\bW\.T\.S\b"),
        re.compile(r"Want to Sell", re.IGNORECASE),
        re.compile(r"WANT TO SELL"),
        re.compile(r"\bSelling\b", re.IGNORECASE),
        re.compile(r"Selling Today", re.IGNORECASE),
        re.compile(r"Wholesale Offer", re.IGNORECASE),
        re.compile(r"Bulk Stock Update", re.IGNORECASE),
        re.compile(r"New stock available", re.IGNORECASE),
        re.compile(r"Stock (?:available|update|ready)", re.IGNORECASE),
        re.compile(r"seller(?:\s|$)", re.IGNORECASE),
        re.compile(r"for sale", re.IGNORECASE),
    ],
    "INTENT_PRICE_DISCOVERY": [
        re.compile(r"Message for best price", re.IGNORECASE),
        re.compile(r"Ask for best price", re.IGNORECASE),
        re.compile(r"Offer your best price", re.IGNORECASE),
        re.compile(r"\*Ask for best price\*", re.IGNORECASE),
        re.compile(r"Ping me for best", re.IGNORECASE),
        re.compile(r"best (?:combo|bundle) offers", re.IGNORECASE),
        re.compile(r"Price on ask", re.IGNORECASE),
        re.compile(r"DM (?:for|me) (?:price|best)", re.IGNORECASE),
        re.compile(r"Message (?:for|me) (?:price|best)", re.IGNORECASE),
    ],
    "INTENT_PREBOOK": [
        re.compile(r"Pre Booking", re.IGNORECASE),
        re.compile(r"\bBooking\b", re.IGNORECASE),
        re.compile(r"Pre[- ]?Book", re.IGNORECASE),
    ],
    "INTENT_STATUS_CLOSE": [
        re.compile(r"already sold", re.IGNORECASE),
        re.compile(r"deal done", re.IGNORECASE),
        re.compile(r"don'?t need it anymore", re.IGNORECASE),
        re.compile(r"\bsold out\b", re.IGNORECASE),
        re.compile(r"\bclosed\b", re.IGNORECASE),
    ],
}

# --- Pass C: Brand ---

BRAND_APPLE_SURFACE: list[str] = [
    "Apple", "iPhone", "iPad", "MacBook", "AirPods", "AirPod",
    "AirPods Max", "Apple Watch", "Apple Pencil", "Magic Mouse", "AirTag",
    "Airpod", "airpods", "airpod",
]

BRAND_SAMSUNG_SURFACE: list[str] = [
    "Samsung", "Galaxy",
    "S25", "S25+", "S25 FE", "S25 Edge", "S25 Ultra",
    "S26", "S26+", "S26 Ultra",
    "A16", "A17", "A26", "A27", "A37", "A56", "A57",
    "Z Flip7", "Flip7 FE", "Z Fold7", "Tri Fold",
    "Tab A11", "Tab A11+", "Tab S10", "Tab S10+", "Tab S11 Ultra",
    "Buds3", "Buds4", "Buds",
    "Watch 7", "Watch 8",
    "XCover",
]

BRAND_NON_TARGET: list[str] = [
    "Google", "Pixel", "Fitbit",
    "Xiaomi", "Redmi",
    "OnePlus", "Nord",
    "Oppo", "realme",
    "Motorola", "Moto",
    "Nokia", "Honor", "Huawei",
    "Nothing", "Fairphone", "Gigaset", "CAT", "Mobitel",
    "DJI", "Osmo", "GoPro", "Kodak", "Charmera",
    "Whoop", "Starlink",
    "PS5", "Xbox",
    "Amazon", "Fire Stick",
    "ASUS", "Zenbook", "Dell", "Lenovo", "IdeaPad",
    "NVIDIA", "RTX",
    "Air Conditioner", "BTU",
]

BRAND_NON_TARGET_SAMSUNG_SSD: list[re.Pattern] = [
    re.compile(r"Samsung\s+SSD", re.IGNORECASE),
    re.compile(r"Samsung\s+990", re.IGNORECASE),
    re.compile(r"Samsung\s+T\d", re.IGNORECASE),
]

# --- Pass C: Category ---

CATEGORY_PATTERNS: dict[str, list[re.Pattern]] = {
    "CAT_SMARTPHONE": [
        re.compile(r"\biPhone\b", re.IGNORECASE),
        re.compile(r"\bGalaxy\b", re.IGNORECASE),
        re.compile(r"\d+\s*(Pro|Pro Max|Plus|Ultra|e|FE|Edge)\b", re.IGNORECASE),
        re.compile(r"\bS\d\d\b"),
        re.compile(r"\bA\d\d\b"),
        re.compile(r"\bZ\s*(Flip|Fold)\d", re.IGNORECASE),
        re.compile(r"\bTri Fold\b", re.IGNORECASE),
    ],
    "CAT_TABLET": [
        re.compile(r"\biPad\b", re.IGNORECASE),
        re.compile(r"\bTab\s+(A|S)\d", re.IGNORECASE),
        re.compile(r"\bTab\s+\d+", re.IGNORECASE),
    ],
    "CAT_LAPTOP": [
        re.compile(r"\bMacBook\b", re.IGNORECASE),
        re.compile(r"\bMac\s*(Book|Air|Pro)\b", re.IGNORECASE),
    ],
    "CAT_SMARTWATCH": [
        re.compile(r"Apple\s*Watch", re.IGNORECASE),
        re.compile(r"\bWatch\s*(SE|Ultra|Series|\d)", re.IGNORECASE),
        re.compile(r"\bUltra\s*\d", re.IGNORECASE),
        re.compile(r"\bS\d\d\s*(4[026]mm)", re.IGNORECASE),
        re.compile(r"\bWatch\s*(7|8|Ultra)\b", re.IGNORECASE),
    ],
    "CAT_EARBUDS": [
        re.compile(r"\bAirPods?\b", re.IGNORECASE),
        re.compile(r"\bAirPods?\s*(Pro|Max)\b", re.IGNORECASE),
        re.compile(r"\bBuds\d?\b", re.IGNORECASE),
        re.compile(r"\bSamsung\s*Buds", re.IGNORECASE),
    ],
    "CAT_ACCESSORY": [
        re.compile(r"\bcharger\b", re.IGNORECASE),
        re.compile(r"\badapter\b", re.IGNORECASE),
        re.compile(r"\badopter\b", re.IGNORECASE),
        re.compile(r"\bcable\b", re.IGNORECASE),
        re.compile(r"\bC to C\b", re.IGNORECASE),
        re.compile(r"Apple\s*Pencil", re.IGNORECASE),
        re.compile(r"Magic\s*Mouse", re.IGNORECASE),
        re.compile(r"\bAirTag\b", re.IGNORECASE),
        re.compile(r"\b20W\s*USB", re.IGNORECASE),
        re.compile(r"\bSport Band\b", re.IGNORECASE),
        re.compile(r"\bMilanese Loop\b", re.IGNORECASE),
        re.compile(r"\bcase\b", re.IGNORECASE),
        re.compile(r"\bscreen protector\b", re.IGNORECASE),
    ],
}

# --- Pass C: Model numbers ---

MODEL_NUMBER_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b\d{13}\b"),                          # EAN
    re.compile(r"\b[A-Z]{2,4}\d{2,3}[A-Z]{2}/A\b"),    # Apple MPN suffix
    re.compile(r"\b[SFA]\d{3,4}[A-Z]?\b"),              # Samsung internal
]

# --- Pass C: Storage ---

STORAGE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(64|128|256|512)\s*GB\b", re.IGNORECASE),
    re.compile(r"\b(1|2)\s*TB\b", re.IGNORECASE),
    re.compile(r"\b\d{2,3}\s*g[bB]\b"),
    re.compile(r"\b\d\s*t[bB]\b"),
]

# --- Pass C: RAM ---

RAM_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b([48]|12|16|24|32)\s*GB\s*(RAM|Memory)?\b", re.IGNORECASE),
    re.compile(r"\b\d/\d{2,3}\b"),  # 4/64, 8/256 combined notation
]

# --- Pass C: Color ---

COLOR_MAP: dict[str, list[str]] = {
    "Black": ["black", "bank", "blk", "🖤"],
    "White": ["white", "wht", "🤍"],
    "Blue": ["blue", "blu", "💙"],
    "Deep Blue": ["deep blue"],
    "Sky Blue": ["sky blue"],
    "Cobalt Violet": ["cobalt violet"],
    "Violet": ["violet", "violett"],
    "Silver": ["silver", "siilver", "slvr"],
    "Grey": ["grey", "gray", "space gray", "graphite"],
    "Navy": ["navy"],
    "Mint": ["mint"],
    "Olive": ["olive"],
    "Lavender": ["lavender", "levander"],
    "Sage": ["sage"],
    "Lilac": ["lilac"],
    "Icy Blue": ["icy blue", "icyblue"],
    "Pink": ["pink"],
    "Green": ["green", "light green"],
    "Yellow": ["yellow", "💛"],
    "Gold": ["gold", "rose gold"],
    "Orange": ["orange", "cosmic orange", "🍊"],
    "Midnight": ["midnight"],
    "Starlight": ["starlight"],
    "Cream": ["cream"],
    "Desert": ["desert"],
    "Natural": ["natural"],
    "Titanium Black": ["titanium black"],
    "Titanium Grey": ["titanium grey", "titanium gray"],
    "Titanium Silver": ["titanium silver"],
    "Titanium Icyblue": ["titanium icyblue", "titanium icy blue"],
    "Titanium Jetblack": ["titanium jetblack", "titanium jet black"],
    "Titanium Silverblue": ["titanium silverblue", "titanium silver blue"],
    "Titanium Blue": ["titanium blue"],
    "Titanium Whitesilver": ["titanium whitesilver", "titanium white silver"],
    "Blue/Silver Shadow": ["blue/silver shadow", "silver shadow"],
    "Obsidian": ["obsidian"],
    "Moonstone": ["moonstone"],
    "Teal": ["teal"],
    "Purple": ["purple", "💜"],
}

# --- Pass C: Region ---

REGION_PATTERNS: dict[str, list[str | re.Pattern]] = {
    "REGION_UK": [
        re.compile(r"\bUK\b"),
        "🇬🇧",
        re.compile(r"\bUK Spec\b"),
        re.compile(r"\bUK ONLY\b"),
        re.compile(r"/B\b"),
        re.compile(r"£\s*\d"),
    ],
    "REGION_USA": [
        re.compile(r"\bUSA\b"),
        re.compile(r"\bUS Spec\b"),
        "🇺🇸",
        re.compile(r"\bLL/A\b"),
        re.compile(r"\bFOB\s+NY\b"),
        re.compile(r"\bFOB\s+US\b"),
    ],
    "REGION_JAPAN": [
        re.compile(r"\bJP\b"),
        re.compile(r"\bJp\b"),
        "🇯🇵",
    ],
    "REGION_CHINA": [
        re.compile(r"\bChina\b"),
        "🇨🇳",
    ],
    "REGION_HONGKONG": [
        re.compile(r"\bHK\b"),
        "🇭🇰",
    ],
    "REGION_INDIA": [
        re.compile(r"\bIndia\b"),
        re.compile(r"\bInd\b"),
        re.compile(r"\bINDIA\b"),
        "🇮🇳",
    ],
    "REGION_EU": [
        re.compile(r"\bEU\b"),
        re.compile(r"\bEU spec\b", re.IGNORECASE),
        re.compile(r"\bDE\b"),
        re.compile(r"ZE/A\b"),
        re.compile(r"€\s*\d"),
        re.compile(r"\bnon\s*EU\b", re.IGNORECASE),
    ],
    "REGION_UAE": [
        re.compile(r"\bUAE\b"),
        "🇦🇪",
        re.compile(r"\bTRA\b"),
        re.compile(r"Ready In Local", re.IGNORECASE),
        re.compile(r"\bLocal\b"),
    ],
    "REGION_KSA": [
        re.compile(r"\bKSA\b"),
        re.compile(r"Desert.*KSA", re.IGNORECASE),
        re.compile(r"\bSaudi\b", re.IGNORECASE),
    ],
    "REGION_AUSTRALIA": [
        re.compile(r"\bAustralia\b", re.IGNORECASE),
    ],
    "REGION_ANY": [
        re.compile(r"Any spec", re.IGNORECASE),
        re.compile(r"we just want to buy", re.IGNORECASE),
        re.compile(r"\bMix\b"),
        re.compile(r"\bAny\b.*\bspec\b", re.IGNORECASE),
    ],
    "SIM_ESIM": [
        re.compile(r"\bESIM\b", re.IGNORECASE),
        re.compile(r"\beSIM\b"),
        re.compile(r"\be-sim\b", re.IGNORECASE),
    ],
    "SIM_PHYSICAL": [
        re.compile(r"physical SIM", re.IGNORECASE),
        re.compile(r"physical sim"),
        re.compile(r"\bHK\b"),
        re.compile(r"\bUK\b"),
        re.compile(r"\bAU\b"),
    ],
}

# --- Pass C: Activation ---

ACTIVATION_PATTERNS: dict[str, list[re.Pattern]] = {
    "ACT_NON_ACTIVE": [
        re.compile(r"Non[- ]?Active", re.IGNORECASE),
        re.compile(r"\bNON ACTIVE\b"),
        re.compile(r"Non Active Stock", re.IGNORECASE),
    ],
    "ACT_ACTIVE": [
        re.compile(r"(?<!Non[ -])(?<!NON[ -])\bActive\b", re.IGNORECASE),
        re.compile(r"\bA/A\+\b"),
    ],
    "ACT_LOCKED": [
        re.compile(r"Locked\s*🔒", re.IGNORECASE),
        re.compile(r"\bLocked\b"),
        re.compile(r"Brand New\s*\|\s*Locked", re.IGNORECASE),
    ],
    "ACT_SIMFREE": [
        re.compile(r"\bSimfree\b", re.IGNORECASE),
        re.compile(r"\bOEM Simfree\b", re.IGNORECASE),
        re.compile(r"All OEM Simfree stock", re.IGNORECASE),
    ],
    "ACT_OEM": [
        re.compile(r"\bOEM\b", re.IGNORECASE),
        re.compile(r"OEM\s*[-–]\s*Brand New", re.IGNORECASE),  # noqa: RUF001
    ],
}

# --- Pass C: Condition ---

CONDITION_PATTERNS: dict[str, list[re.Pattern]] = {
    "COND_NEW": [
        re.compile(r"Brand New", re.IGNORECASE),
        re.compile(r"New stock", re.IGNORECASE),
        re.compile(r"OEM Brand New", re.IGNORECASE),
        re.compile(r"Original Brand New", re.IGNORECASE),
    ],
    "COND_OPEN_BOX": [
        re.compile(r"Open box", re.IGNORECASE),
        re.compile(r"Open box units", re.IGNORECASE),
    ],
    "COND_GRADE_A": [
        re.compile(r"Grade\s*A", re.IGNORECASE),
        re.compile(r"\bA/A\+\b"),
        re.compile(r"A-type", re.IGNORECASE),
    ],
    "COND_GRADE_B": [
        re.compile(r"Grade\s*B", re.IGNORECASE),
        re.compile(r"\bB-type\b", re.IGNORECASE),
    ],
    "COND_GRADE_C": [
        re.compile(r"Grade\s*C", re.IGNORECASE),
        re.compile(r"\bC-type\b", re.IGNORECASE),
    ],
    "COND_USED_REFURB": [
        re.compile(r"\bused\b", re.IGNORECASE),
        re.compile(r"\brefurbished\b", re.IGNORECASE),
        re.compile(r"gift/refund", re.IGNORECASE),
    ],
}

# --- Pass C: Quantity ---

QUANTITY_PATTERNS: dict[str, list[re.Pattern]] = {
    "QTY_EXACT": [re.compile(r"(\d+)\s*(pcs|units?|qty|pieces)", re.IGNORECASE)],
    "QTY_OPEN_ENDED": [re.compile(r"(\d+)\+"), re.compile(r"(\d+)K\+")],
    "QTY_SINGLE": [
        re.compile(r"\b1\s*pc\b", re.IGNORECASE),
        re.compile(r"\b1pc\b", re.IGNORECASE),
        re.compile(r"\bsingle\b", re.IGNORECASE),
    ],
    "QTY_BULK": [
        re.compile(r"\bBulk\b", re.IGNORECASE),
        re.compile(r"Master Box", re.IGNORECASE),
        re.compile(r"\bWholesale\b", re.IGNORECASE),
    ],
    "QTY_MIXED_LIST": [re.compile(r"(?:\d+\s*(pcs|units).*){3,}", re.IGNORECASE)],
    "MOQ_APPLIES": [
        re.compile(r"\bMOQ\b", re.IGNORECASE),
        re.compile(r"MOQ Applies", re.IGNORECASE),
    ],
    "QTY_LIMITED": [
        re.compile(r"Last quantity", re.IGNORECASE),
        re.compile(r"Limited stock", re.IGNORECASE),
        re.compile(r"Limited qty left", re.IGNORECASE),
        re.compile(r"LIMITED STOCK"),
    ],
}

# --- Pass C: Logistics ---

LOGISTICS_PATTERNS: dict[str, list[str | re.Pattern]] = {
    "LOC_LOCAL_READY": [
        re.compile(r"Ready In Local", re.IGNORECASE),
        re.compile(r"Ready Stock", re.IGNORECASE),
        re.compile(r"READY IN LOCAL"),
        re.compile(r"Available In Shop", re.IGNORECASE),
    ],
    "LOC_FZCO": [
        re.compile(r"\bFZCO\b", re.IGNORECASE),
        re.compile(r"\bFzco\b"),
        re.compile(r"Ready stock in Fzco", re.IGNORECASE),
    ],
    "LOC_OVERSEAS_DROPSHIP": [
        re.compile(r"Delivery:\s*\d+[-–]\d+\s*days to us", re.IGNORECASE),  # noqa: RUF001
        re.compile(r"\d+[-–]\d+\s*days to us", re.IGNORECASE),  # noqa: RUF001
        re.compile(r"\bFOB\s+", re.IGNORECASE),
    ],
    "LOC_DELIVERY_DAYS": [
        re.compile(r"Delivery:\s*(\d+)\s*days?", re.IGNORECASE),
        re.compile(r"(\d+)\s*to\s*(\d+)\s*days?", re.IGNORECASE),
        re.compile(r"(\d+)\s*days?(?:\s*delivery)?", re.IGNORECASE),
    ],
    "LOC_PICKUP_STORE": [
        re.compile(r"Pay in-store", re.IGNORECASE),
        re.compile(r"Available In Shop", re.IGNORECASE),
    ],
    "LOC_CITY": [
        re.compile(r"London,\s*UK", re.IGNORECASE),
        re.compile(r"\bHong Kong\b", re.IGNORECASE),
        re.compile(r"\bDubai\b", re.IGNORECASE),
        re.compile(r"\bNew York\b", re.IGNORECASE),
        re.compile(r"\bSingapore\b", re.IGNORECASE),
        re.compile(r"\bShenzhen\b", re.IGNORECASE),
    ],
}

# --- Pass C: Currency ---

CURRENCY_PATTERNS: dict[str, list[str | re.Pattern]] = {
    "CUR_GBP": [re.compile(r"£\s*\d+"), re.compile(r"GBP", re.IGNORECASE)],
    "CUR_EUR": [re.compile(r"€\s*\d+"), re.compile(r"EUR", re.IGNORECASE)],
    "CUR_AED": [
        re.compile(r"\bAED\b", re.IGNORECASE),
        re.compile(r"AED/each", re.IGNORECASE),
        re.compile(r"\bDhs?\b", re.IGNORECASE),
    ],
    "CUR_MASKED": [re.compile(r"£\*+"), re.compile(r"Price on ask", re.IGNORECASE)],
}

# --- Pass C: Contact CC ---

CONTACT_CC_PATTERN: re.Pattern = re.compile(r"\+\d{1,3}")

NON_LOCALITY_COUNTRY_CODES: frozenset[str] = frozenset([
    "+971", "+49", "+44", "+1", "+81", "+86", "+852", "+91", "+61", "+966",
])

# --- Pass C: Variants ---

VARIANT_PATTERNS: dict[str, list[str | re.Pattern]] = {
    "VAR_ENTERPRISE": [
        re.compile(r"Enterprise Edition", re.IGNORECASE),
        re.compile(r"\bEE\b"),
    ],
    "VAR_REGION_EAST": [re.compile(r"Region East", re.IGNORECASE)],
    "VAR_REGION_WEST": [re.compile(r"Region West", re.IGNORECASE)],
    "VAR_CELLULAR": [
        re.compile(r"GPS\s*\+\s*Cellular", re.IGNORECASE),
        re.compile(r"\b5G\b"),
        re.compile(r"\b4G\b"),
        re.compile(r"\bCellular\b", re.IGNORECASE),
    ],
    "VAR_WIFI": [
        re.compile(r"\bWiFi\b", re.IGNORECASE),
        re.compile(r"\bBT\b", re.IGNORECASE),
        re.compile(r"\bBluetooth\b", re.IGNORECASE),
    ],
    "VAR_BUNDLE": [
        re.compile(r"\bcombo\b", re.IGNORECASE),
        re.compile(r"\bbundle\b", re.IGNORECASE),
        re.compile(r"CaseWith", re.IGNORECASE),
    ],
    "VAR_WATCH_SIZE": [re.compile(r"\b(4[026]|49)mm\b")],
    "VAR_WATCH_BAND": [
        re.compile(r"Milanese Loop", re.IGNORECASE),
        re.compile(r"Sport Band", re.IGNORECASE),
        re.compile(r"Alpine Loop", re.IGNORECASE),
        re.compile(r"Ocean Band", re.IGNORECASE),
        re.compile(r"Trail Loop", re.IGNORECASE),
    ],
}


# =============================================================================
# Pass B — Intent / side detection
# =============================================================================


def extract_side(text: str) -> str:
    """Port of JS passB(text). Returns one of: buy, sell, price_discovery,
    prebook, status_close, unknown."""
    text_upper = text.upper()

    # Fast-path WTB/WTS detection (most common)
    if re.search(r"\bWTB\b", text):
        return "buy"
    if re.search(r"\bW\s*T\s*S\b", text) or re.search(r"\bW\.T\.S\b", text):
        return "sell"

    # Count buy / sell hits
    buy_hits = 0
    for p in INTENT_PATTERNS["SIDE_BUY"]:
        if isinstance(p, str):
            if p.upper() in text_upper:
                buy_hits += 1
        elif p.search(text):
            buy_hits += 1

    sell_hits = 0
    for p in INTENT_PATTERNS["SIDE_SELL"]:
        if isinstance(p, str):
            if p.upper() in text_upper:
                sell_hits += 1
        elif p.search(text):
            sell_hits += 1

    price_disc = False
    for p in INTENT_PATTERNS["INTENT_PRICE_DISCOVERY"]:
        if isinstance(p, str):
            if p.upper() in text_upper:
                price_disc = True
                break
        elif p.search(text):
            price_disc = True
            break

    pre_book = any(
        p.search(text) for p in INTENT_PATTERNS["INTENT_PREBOOK"]
        if not isinstance(p, str)
    )
    status_close = any(
        p.search(text) for p in INTENT_PATTERNS["INTENT_STATUS_CLOSE"]
        if not isinstance(p, str)
    )

    # Priority chain
    if status_close:
        return "status_close"
    if buy_hits > sell_hits:
        return "buy"
    if sell_hits > buy_hits:
        return "sell"
    if price_disc:
        return "price_discovery"
    if pre_book:
        return "prebook"

    # Heuristic fallback
    if re.search(r"\b(I need|looking for|anyone have|anyone got|want to buy|wtb)\b",
                 text, re.IGNORECASE):
        return "buy"
    if re.search(r"\b(selling|for sale|stock available|stock update|want to sell|wts)\b",
                 text, re.IGNORECASE):
        return "sell"

    return "unknown"


# =============================================================================
# Pass C — Attribute extraction
# =============================================================================


def has_target_brand(text: str) -> dict[str, Any]:
    """Port of JS hasTargetBrand(text). Returns {brand: str, samsung_ssd?: bool}."""
    # Samsung SSD check first — "Samsung SSD" is not target
    if any(p.search(text) for p in BRAND_NON_TARGET_SAMSUNG_SSD):
        if any(s.lower() in text.lower() for s in BRAND_APPLE_SURFACE):
            return {"brand": "apple", "samsung_ssd": True}
        return {"brand": "non_target"}

    lower = text.lower()
    has_apple = any(s.lower() in lower for s in BRAND_APPLE_SURFACE)
    has_samsung = any(s.lower() in lower for s in BRAND_SAMSUNG_SURFACE)
    has_non_target = any(s.lower() in lower for s in BRAND_NON_TARGET)

    if has_apple and has_samsung:
        return {"brand": "mixed"}
    if has_apple:
        return {"brand": "apple"}
    if has_samsung:
        return {"brand": "samsung"}
    if has_non_target:
        return {"brand": "non_target"}
    return {"brand": "unknown"}


def parse_category(text: str, brand: str) -> list[str]:
    """Port of JS parseCategory(text, brand)."""
    hits = match_named_patterns(text, CATEGORY_PATTERNS)
    found = [k for k in hits if hits[k]]

    if brand == "apple":
        apple_cats = [
            c for c in found
            if c not in ("CAT_SAMSUNG_WATCH", "CAT_SAMSUNG_TAB", "CAT_SAMSUNG_BUDS")
        ]
        return apple_cats if apple_cats else ["CAT_SMARTPHONE"]
    if brand == "samsung":
        samsung_cats = [c for c in found if c != "CAT_LAPTOP"]
        return samsung_cats if samsung_cats else ["CAT_SMARTPHONE"]
    return found


def parse_storage(text: str) -> list[str]:
    """Port of JS parseStorage(text). Deduplicates, preserves insertion order."""
    seen: dict[str, None] = {}
    for p in STORAGE_PATTERNS:
        for m in p.finditer(text):
            val = m.group(0).upper().replace(" ", "")
            seen[val] = None
    return list(seen)


def parse_ram(text: str) -> list[str]:
    """Port of JS parseRam(text)."""
    seen: dict[str, None] = {}
    for p in RAM_PATTERNS:
        for m in p.finditer(text):
            val = m.group(0).upper().replace(" ", "")
            seen[val] = None
    return list(seen)


def parse_color(text: str) -> list[str]:
    """Port of JS parseColor(text)."""
    lower = text.lower()
    hits: list[str] = []
    for canonical, aliases in COLOR_MAP.items():
        for alias in aliases:
            if alias in lower:
                hits.append(canonical)
                break
    return hits


def parse_region(text: str) -> list[str]:
    """Port of JS parseRegion(text)."""
    return list(match_named_patterns(text, REGION_PATTERNS))


def parse_activation(text: str) -> list[str]:
    """Port of JS parseActivation(text)."""
    return list(match_named_patterns(text, ACTIVATION_PATTERNS))


def parse_condition(text: str) -> list[str]:
    """Port of JS parseCondition(text)."""
    return list(match_named_patterns(text, CONDITION_PATTERNS))


def parse_quantity(text: str) -> dict[str, Any]:
    """Port of JS parseQuantity(text). Returns dict with bool flags + optional qty_value."""
    qtys: dict[str, Any] = {}
    for tag, patterns in QUANTITY_PATTERNS.items():
        for p in patterns:
            if p.search(text):
                qtys[tag] = True
                if tag == "QTY_EXACT":
                    m = re.search(r"(\d+)\s*(pcs|units?|qty|pieces)", text, re.IGNORECASE)
                    if m:
                        qtys["qty_value"] = int(m.group(1))
                break
    return qtys


def parse_logistics(text: str) -> list[str]:
    """Port of JS parseLogistics(text)."""
    return list(match_named_patterns(text, LOGISTICS_PATTERNS))


def parse_currency(text: str) -> list[str]:
    """Port of JS parseCurrency(text)."""
    return list(match_named_patterns(text, CURRENCY_PATTERNS))


def parse_variants(text: str) -> list[str]:
    """Port of JS parseVariants(text)."""
    return list(match_named_patterns(text, VARIANT_PATTERNS))


def parse_model_numbers(text: str) -> list[str]:
    """Port of JS parseModelNumbers(text). Deduplicates, preserves insertion order."""
    seen: dict[str, None] = {}
    for p in MODEL_NUMBER_PATTERNS:
        for m in p.finditer(text):
            seen[m.group(0)] = None
    return list(seen)


def extract_contact_cc(text: str) -> dict[str, Any] | None:
    """Port of the contact CC extraction in JS passC. Returns {cc, is_foreign} or None."""
    m = CONTACT_CC_PATTERN.search(text)
    if m:
        cc = m.group(0)
        return {"cc": cc, "is_foreign": cc in NON_LOCALITY_COUNTRY_CODES}
    return None


# =============================================================================
# Top-level orchestrators
# =============================================================================


def extract_intent(text: str) -> dict[str, Any]:
    """Full Pass B equivalent. Returns {side, is_chatter, status_close, prebook,
    price_discovery}.

    is_chatter is always False from the Python path (Pass A noise gate is not
    ported — noise rejection stays listener-side).
    """
    cleaned = clean_text(text)
    working = cleaned or text

    side = extract_side(working)

    # Recompute the boolean flags that went into the side decision so callers
    # can inspect them.
    text_upper = working.upper()
    price_disc = any(
        (p.upper() in text_upper) if isinstance(p, str) else bool(p.search(working))
        for p in INTENT_PATTERNS["INTENT_PRICE_DISCOVERY"]
    )
    pre_book = any(
        p.search(working) for p in INTENT_PATTERNS["INTENT_PREBOOK"]
        if not isinstance(p, str)
    )
    status_close = any(
        p.search(working) for p in INTENT_PATTERNS["INTENT_STATUS_CLOSE"]
        if not isinstance(p, str)
    )

    return {
        "side": side,
        "is_chatter": False,  # Pass A not ported
        "status_close": status_close,
        "prebook": pre_book,
        "price_discovery": price_disc,
    }


def extract_attributes(text: str) -> dict[str, Any]:
    """Full Pass C equivalent. Returns {passed, brand, categories, storage, ram,
    color, region, activation, condition, quantity, logistics, currency,
    variants, model_numbers, contact_cc}."""
    cleaned = clean_text(text)
    working = cleaned or text

    brand_result = has_target_brand(working)

    if brand_result["brand"] in ("non_target", "unknown"):
        return {
            "passed": False,
            "reason": "non_target_brand",
            "brand": brand_result["brand"],
        }

    result: dict[str, Any] = {
        "passed": True,
        "brand": brand_result["brand"],
        "samsung_ssd": brand_result.get("samsung_ssd", False),
    }

    result["categories"] = parse_category(working, result["brand"])
    result["storage"] = parse_storage(working)
    result["ram"] = parse_ram(working)
    result["color"] = parse_color(working)
    result["region"] = parse_region(working)
    result["activation"] = parse_activation(working)
    result["condition"] = parse_condition(working)
    result["quantity"] = parse_quantity(working)
    result["logistics"] = parse_logistics(working)
    result["currency"] = parse_currency(working)
    result["variants"] = parse_variants(working)
    result["model_numbers"] = parse_model_numbers(working)

    cc = extract_contact_cc(working)
    if cc:
        result["contact_cc"] = cc

    return result
