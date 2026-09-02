"""Static payloads and deterministic generators for the demo dataset.

Pure data + pure functions: no I/O, no ORM, no database access. Everything is
derived from a fixed namespace and a fixed RNG seed, so two runs produce byte
-identical output and re-seeding is idempotent.

Times are expressed as offsets (``days_ago``, ``hour``) rather than absolute
timestamps, and resolved against a single ``run_at`` captured once per run.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

# Bump to invalidate a previous seed run's ledger and force a fresh pass.
DATASET_VERSION = 1

# Fixed namespace — every demo row's id is uuid5(NAMESPACE, "<kind>:<key>"),
# so re-running collides on the primary key instead of inserting duplicates.
NAMESPACE = uuid.UUID("7d3f0a12-5c48-4e91-a6b2-0d1e2f3a4b5c")

# Marks demo-owned users so a wipe can find them without touching real accounts.
DEMO_EMAIL_DOMAIN = "demo.engageos.local"

# Reserved/non-routable UAE test range: even an escaped send hits nothing real.
DEMO_PHONE_PREFIX = "+97155501"

HISTORY_DAYS = 90
ERP_HISTORY_DAYS = 150


def did(kind: str, key: str) -> uuid.UUID:
    """Deterministic id for a demo row."""
    return uuid.uuid5(NAMESPACE, f"{kind}:{key}")


def rng(*parts: str) -> random.Random:
    """Deterministic RNG seeded from a stable string key."""
    digest = hashlib.sha256(("|".join(parts)).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


# --------------------------------------------------------------- name pools

FIRST_NAMES = [
    "Ahmed", "Fatima", "Mohammed", "Aisha", "Omar", "Layla", "Yusuf", "Noor",
    "Hassan", "Mariam", "Ali", "Zainab", "Khalid", "Huda", "Rashid", "Amina",
    "Tariq", "Salma", "Bilal", "Rania", "Imran", "Nadia", "Faisal", "Leena",
    "Sami", "Dina", "Karim", "Yasmin", "Nabil", "Hana", "Ravi", "Priya",
    "Arjun", "Meera", "Vikram", "Anjali", "Chen", "Li", "Wei", "Mei",
]

LAST_NAMES = [
    "Al Mansouri", "Khan", "Al Farsi", "Sharma", "Al Balushi", "Patel",
    "Hussain", "Al Zaabi", "Rahman", "Nair", "Al Suwaidi", "Iqbal",
    "Chowdhury", "Al Hashimi", "Menon", "Siddiqui", "Wang", "Zhang",
    "Abdullah", "Kapoor",
]

COMPANY_PREFIX = [
    "Gulf", "Emirates", "Desert", "Falcon", "Oasis", "Pearl", "Skyline",
    "Horizon", "Delta", "Summit", "Crescent", "Marina", "Atlas", "Zenith",
]
COMPANY_SUFFIX = [
    "Electronics", "Trading", "Mobiles", "Distribution", "Technologies",
    "Cell Point", "Wholesale", "Communications", "Digital", "Traders",
]

GROUP_NAMES = [
    "UAE Mobile Wholesale", "Gulf Electronics Traders", "Dubai Phone Market",
    "GCC Bulk Deals", "Mobile Traders Network", "Electronics Exchange DXB",
]

# --------------------------------------------------------------- CRM content

INBOUND_LINES = [
    "assalam o alaikum", "hi, do you have stock?", "what's your best price?",
    "how many pcs available?", "can you do 50 units?", "is this UK spec?",
    "send me your list please", "what about warranty?",
    "do you deliver to Sharjah?", "any discount for bulk?",
    "still available?", "ok noted, will confirm tomorrow",
    "what payment terms?", "can I pick up from your office?",
    "do you have it in black?", "please add me to your broadcast list",
    "thanks for the update", "price is too high bro",
    "I need 200 pcs, urgent", "sending payment today",
]

OUTBOUND_LINES = [
    "walaikum assalam", "yes we have stock", "let me check and confirm",
    "sending you the list now", "MOQ is 10 pcs", "yes UK spec available",
    "we can do AED 2,450 per unit", "delivery in 2 working days",
    "sure, adding you to the broadcast list", "office is in Deira",
    "payment 50% advance, rest on delivery", "yes black is available",
    "will update you when new shipment lands", "noted, thanks",
    "that's our best price", "we deal in iphones samsung laptops accessories",
    "stock is limited, please confirm soon", "invoice sent, please check",
]

MARKET_BUY_TEMPLATES = [
    "WTB {product} {storage} {region} — need {qty} pcs, best price",
    "Looking to buy {product} {storage}, {qty} units, {region} spec",
    "Need {product} {storage} {color} urgently, qty {qty}",
    "WTB: {product} — {qty} pcs, non active, {region}",
    "Buying {product} {storage}, payment ready, {qty} pieces",
]

MARKET_SELL_TEMPLATES = [
    "WTS {product} {storage} {region} @ AED {price} — {qty} pcs available",
    "Available: {product} {storage} {color}, {qty} units, AED {price}",
    "Stock ready {product} {storage} — AED {price}, MOQ 10",
    "WTS: {product} {region} spec, {qty} pcs, AED {price} each",
    "Selling {product} {storage} {color} — {qty} available, AED {price}",
]

STORAGES = ["128GB", "256GB", "512GB", "1TB"]
REGIONS = ["UK", "US", "HK", "JP", "UAE", "EU"]
COLORS = ["Black", "Blue", "Silver", "Natural", "White", "Midnight"]

TEMPLATE_SPECS = [
    ("new_stock_alert", "approved", "marketing",
     "New stock just landed! {{1}} now available at {{2}}. Reply for details."),
    ("price_list_weekly", "approved", "marketing",
     "Weekly price list for {{1}} is ready. Reply LIST to receive it."),
    ("order_confirmation", "approved", "utility",
     "Hi {{1}}, your order {{2}} is confirmed. Total: AED {{3}}."),
    ("payment_reminder", "approved", "utility",
     "Reminder: invoice {{1}} of AED {{2}} is due on {{3}}."),
    ("shipment_dispatched", "approved", "utility",
     "Your shipment {{1}} has been dispatched and arrives on {{2}}."),
    ("reengage_cold", "approved", "marketing",
     "Hi {{1}}, we have new arrivals this week. Interested?"),
    ("eid_promo", "pending", "marketing",
     "Eid offer: {{1}}% off on selected models until {{2}}."),
    ("legacy_blast", "rejected", "marketing",
     "Big discounts today only, reply now!"),
]

CAMPAIGN_CATEGORIES = [
    ("Stock Alerts", "New arrival announcements", "#2563eb"),
    ("Price Lists", "Recurring price list broadcasts", "#16a34a"),
    ("Re-engagement", "Win back dormant contacts", "#d97706"),
    ("Transactional", "Order and payment notices", "#7c3aed"),
    ("Seasonal", "Holiday and seasonal promotions", "#db2777"),
]

# name, status, type, days_ago (None = not yet run), audience, sent/deliv/fail/resp
CAMPAIGN_SPECS = [
    ("June Stock Alert - iPhone", "completed", "immediate", 78, 145, 142, 136, 6, 38),
    ("July Price List Blast", "completed", "immediate", 52, 180, 176, 170, 6, 47),
    ("Samsung S25 Launch Push", "completed", "immediate", 34, 120, 118, 112, 6, 41),
    ("August Re-engagement", "completed", "immediate", 16, 95, 93, 88, 5, 22),
    ("Ramadan Bulk Offer", "failed", "immediate", 61, 60, 12, 4, 8, 1),
    ("Laptop Clearance", "cancelled", "immediate", 45, 40, 0, 0, 0, 0),
    ("Q4 Accessories Promo", "draft", "immediate", None, 0, 0, 0, 0, 0),
    ("New Supplier Announcement", "draft", "immediate", None, 0, 0, 0, 0, 0),
]

USER_SPECS = [
    ("sara.ahmed", "Sara Ahmed", "admin", True),
    ("omar.khalid", "Omar Khalid", "admin", True),
    ("layla.hassan", "Layla Hassan", "agent", True),
    ("bilal.rahman", "Bilal Rahman", "agent", True),
    ("nadia.iqbal", "Nadia Iqbal", "agent", True),
    ("former.agent", "Former Agent", "agent", False),
]

WAREHOUSE_SPECS = [
    ("DXB-MAIN", "Dubai Main Warehouse"),
    ("AUH-01", "Abu Dhabi Store"),
]

LOCATION_SPECS = [
    ("DXB-MAIN", "A-01", "Aisle A Rack 1"),
    ("DXB-MAIN", "A-02", "Aisle A Rack 2"),
    ("DXB-MAIN", "B-01", "Bulk Storage B1"),
    ("AUH-01", "S-01", "Shelf 1"),
    ("AUH-01", "S-02", "Shelf 2"),
]

# sku, name, brand, category, nature, purchase, sale
ITEM_SPECS = [
    ("IPH-17PM-256", "iPhone 17 Pro Max 256GB", "Apple", "Smartphone", "serialized", 4200, 5250),
    ("IPH-17P-256", "iPhone 17 Pro 256GB", "Apple", "Smartphone", "serialized", 3600, 4500),
    ("IPH-17-128", "iPhone 17 128GB", "Apple", "Smartphone", "serialized", 2900, 3625),
    ("IPH-16PM-256", "iPhone 16 Pro Max 256GB", "Apple", "Smartphone", "serialized", 3400, 4250),
    ("IPH-16-128", "iPhone 16 128GB", "Apple", "Smartphone", "serialized", 2400, 3000),
    ("SAM-S25U-512", "Samsung Galaxy S25 Ultra 512GB", "Samsung", "Smartphone", "serialized", 3800, 4750),
    ("SAM-S25-256", "Samsung Galaxy S25 256GB", "Samsung", "Smartphone", "serialized", 2600, 3250),
    ("SAM-ZF7-512", "Samsung Galaxy Z Fold7 512GB", "Samsung", "Smartphone", "serialized", 5600, 7000),
    ("APL-APP-PRO2", "AirPods Pro 2", "Apple", "Accessory", "bulk", 620, 775),
    ("APL-WCH-S10", "Apple Watch Series 10", "Apple", "Wearable", "bulk", 1100, 1375),
    ("SAM-BUDS3", "Samsung Buds3 Pro", "Samsung", "Accessory", "bulk", 380, 475),
    ("APL-IPD-A11", "iPad A11 128GB", "Apple", "Tablet", "bulk", 1500, 1875),
    ("APL-MBA-M4", "MacBook Air M4 512GB", "Apple", "Laptop", "bulk", 4400, 5500),
    ("GOO-PX10-256", "Google Pixel 10 Pro 256GB", "Google", "Smartphone", "bulk", 2700, 3375),
    ("ACC-CHG-65W", "65W USB-C Charger", "Generic", "Accessory", "bulk", 45, 68),
    ("ACC-CAS-UNI", "Protective Case Assorted", "Generic", "Accessory", "bulk", 18, 32),
]

# bucket, days_overdue, amount  (AR)
AR_AGEING_PLAN = [
    ("current", 0, 24500), ("current", 0, 13200), ("current", 0, 18750),
    ("1_30", 5, 32000), ("1_30", 12, 8900), ("1_30", 18, 41500),
    ("1_30", 25, 15600), ("1_30", 30, 27300),
    ("31_60", 35, 52000), ("31_60", 44, 19800), ("31_60", 52, 36400),
    ("31_60", 60, 44900),
    ("61_90", 65, 28700), ("61_90", 78, 33200), ("61_90", 88, 21400),
    ("over_90", 95, 47600), ("over_90", 110, 18300), ("over_90", 125, 59800),
]

AP_AGEING_PLAN = [
    ("current", 0, 88000), ("current", 0, 42500),
    ("1_30", 9, 126000), ("1_30", 21, 67400), ("1_30", 28, 95300),
    ("31_60", 38, 143000), ("31_60", 49, 71200), ("31_60", 58, 108500),
    ("61_90", 70, 84600), ("61_90", 85, 52900),
    ("over_90", 98, 119400), ("over_90", 132, 63700),
]

AUDIT_ACTIONS = [
    ("login", "user"), ("create", "contact"), ("update", "contact"),
    ("assign", "conversation"), ("approve", "tag_suggestion"),
    ("reject", "tag_suggestion"), ("launch_campaign", "campaign"),
    ("pause_ai", "conversation"), ("resume_ai", "conversation"),
    ("update", "app_setting"), ("delete", "tag"), ("create", "user"),
]

# Message volume weights: peaks mid-morning and late afternoon, quiet overnight
# but never zero, so all 24 bars of the hour-of-day chart render.
HOUR_WEIGHTS = (
    1, 1, 1, 1, 1, 2, 4, 8, 16, 26, 30, 27,
    18, 15, 22, 28, 32, 30, 24, 17, 11, 7, 4, 2,
)
# Mon..Sun — Fri/Sat are the UAE weekend.
DOW_WEIGHTS = (26, 30, 29, 24, 11, 9, 19)


@dataclass
class ContactSpec:
    key: str
    name: str
    company: str
    phone: str
    status: str
    role: str | None  # "customer" | "supplier" | None
    agent_idx: int | None
    ai_assigned: bool
    do_not_contact: bool
    marketing_opt_out: bool
    revenue: int
    ltv: int
    tag_names: list[str] = field(default_factory=list)


CONTACT_STATUSES = [
    "active", "active", "active", "contacted", "contacted", "follow_up",
    "interested", "interested", "not_interested", "inactive", "blocked",
]


def build_contacts(count: int = 60) -> list[ContactSpec]:
    """Deterministically generate the contact roster."""
    out: list[ContactSpec] = []
    for i in range(count):
        r = rng("contact", str(i))
        first = FIRST_NAMES[i % len(FIRST_NAMES)]
        last = LAST_NAMES[(i * 7 + 3) % len(LAST_NAMES)]
        company = (
            f"{COMPANY_PREFIX[(i * 3) % len(COMPANY_PREFIX)]} "
            f"{COMPANY_SUFFIX[(i * 5) % len(COMPANY_SUFFIX)]}"
        )
        # First 12 are ERP customers, next 6 suppliers, rest plain CRM contacts.
        role = "customer" if i < 12 else ("supplier" if i < 18 else None)
        status = "active" if role else CONTACT_STATUSES[i % len(CONTACT_STATUSES)]
        out.append(
            ContactSpec(
                key=f"c{i:03d}",
                name=f"{first} {last}",
                company=company,
                phone=f"{DEMO_PHONE_PREFIX}{i:04d}",
                status=status,
                role=role,
                agent_idx=(i % 3) + 2 if i % 3 != 2 else None,
                ai_assigned=(i % 4 == 0),
                do_not_contact=(i in (37, 48, 55)),
                marketing_opt_out=(i in (21, 33, 41, 52, 58)),
                revenue=(r.randint(4, 340) * 250) if i < 30 else 0,
                ltv=r.randint(8, 520) * 250,
                tag_names=[],
            )
        )
    return out


# Conversation state mix — covers all six states the inbox filters on.
CONVERSATION_STATES = (
    ["NEW"] * 6
    + ["AI_ACTIVE"] * 10
    + ["AWAITING_APPROVAL"] * 5
    + ["HUMAN_ASSIGNED"] * 6
    + ["AI_PAUSED"] * 4
    + ["CLOSED"] * 17
)


def pick_weighted(r: random.Random, weights: tuple[int, ...]) -> int:
    """Index sampled proportionally to *weights*."""
    total = sum(weights)
    x = r.randrange(total)
    acc = 0
    for i, w in enumerate(weights):
        acc += w
        if x < acc:
            return i
    return len(weights) - 1


def message_timestamp(r: random.Random, run_at: datetime, days_ago: int) -> datetime:
    """A timestamp *days_ago* days back, with realistic hour-of-day shape.

    Replacing the hour can push the result past ``run_at`` when *days_ago* is
    0 and the sampled hour is later than the current one, which would date
    messages in the future. Shift those back a day rather than re-rolling, so
    the hour-of-day distribution is preserved.
    """
    hour = pick_weighted(r, HOUR_WEIGHTS)
    ts = (run_at - timedelta(days=days_ago)).replace(
        hour=hour, minute=r.randrange(60), second=r.randrange(60), microsecond=0,
        tzinfo=UTC,
    )
    if ts > run_at:
        ts -= timedelta(days=1)
    return ts


def weighted_day_offset(r: random.Random, run_at: datetime, max_days: int) -> int:
    """Day offset biased toward weekdays so the day-of-week chart has shape."""
    for _ in range(12):
        d = r.randrange(max_days)
        dow = (run_at - timedelta(days=d)).weekday()
        if r.randrange(30) < DOW_WEIGHTS[dow]:
            return d
    return r.randrange(max_days)
