"""Populate the instance with internally-consistent demo CRM + ERP data.

Writes ~90 days of history: contacts, conversations, messages, campaigns,
market leads, and a full ERP document cycle (PO -> GRN -> bill -> payment,
SO -> dispatch -> invoice -> payment) driven through the real service layer
so the ledger bridge posts correct double-entry journals.

Every row's id is uuid5(NAMESPACE, "<kind>:<key>") so re-running is
idempotent. Nothing is written unless SEED_DEMO=1.

Usage (from backend/):
  SEED_DEMO=1 python -m scripts.seed_demo
  SEED_DEMO=1 SEED_DEMO_MODE=refresh-market python -m scripts.seed_demo
  SEED_DEMO=1 SEED_DEMO_MODE=wipe SEED_DEMO_ALLOW_WIPE=1 python -m scripts.seed_demo

On Railway (wired into start-api.sh, gated on SEED_DEMO):
  set SEED_DEMO=1 on the service and redeploy
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.base import import_all_models

# Models are imported lazily inside each phase, after import_all_models().

MODE = os.environ.get("SEED_DEMO_MODE", "").strip().lower()

# Tables emptied by wipe mode. TRUNCATE ... CASCADE handles ordering; the list
# is filtered against information_schema first so a renamed table cannot abort
# the whole statement. Reference data seeded by migrations (accounts, tags,
# products, currencies, uoms, erp_permissions) is deliberately absent.
WIPE_TABLES = [
    "outreach_sends", "deals", "search_events", "saved_searches",
    "contact_product_tags", "market_message_products", "market_messages",
    "campaign_recipients", "campaigns", "campaign_categories",
    "tag_suggestions", "contact_tags",
    "ai_events", "media_assets", "messages", "conversations", "client_memories",
    "payment_allocations", "credit_notes", "customer_payments",
    "sales_invoice_lines", "sales_invoices",
    "bill_allocations", "debit_notes", "supplier_payments",
    "supplier_bill_lines", "supplier_bills",
    "dispatch_lines", "dispatches", "sales_order_lines", "sales_orders",
    "grn_lines", "goods_receipt_notes", "purchase_order_lines", "purchase_orders",
    "stock_ledger_entries", "stock_units", "stock_balances", "serial_nos",
    "items", "locations", "warehouses",
    "journal_lines", "journal_entries", "fiscal_periods", "number_sequences",
    "analytics_daily_metrics", "analytics_campaign_daily_metrics",
    "analytics_template_daily_metrics", "analytics_hourly_metrics",
    "audit_logs", "contacts", "templates",
]


class Report:
    """Accumulates per-phase counts for the closing summary."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []
        self.failed = False

    def add(self, phase: str, detail: str) -> None:
        self.rows.append((phase, detail))
        print(f"  seed_demo | {phase:<24} {detail}", flush=True)

    def fail(self, phase: str, detail: str) -> None:
        self.failed = True
        self.rows.append((phase, f"FAILED: {detail}"))
        print(f"  seed_demo | {phase:<24} FAILED: {detail}", file=sys.stderr, flush=True)


# ------------------------------------------------------------------ helpers


def _jline(account_id, description, *, dr=None, cr=None,
           party_type=None, party_id=None):
    """One-sided journal line with the base-currency columns filled in.

    ``JournalLineRequest.dr_base``/``cr_base`` default to zero and are NOT
    derived from ``dr``/``cr``. PostingService gate 5 balances on the *base*
    columns, so a line that sets only ``dr``/``cr`` posts as a zero-value
    entry while still passing validation. Always build lines through here.
    """
    from app.core.money import money_zero
    from app.modules.ledger.schemas import JournalLineRequest

    z = money_zero()
    return JournalLineRequest(
        account_id=account_id, description=description,
        dr=dr if dr is not None else z, cr=cr if cr is not None else z,
        dr_base=dr if dr is not None else z, cr_base=cr if cr is not None else z,
        party_type=party_type, party_id=party_id,
    )


async def _account_ids(session: AsyncSession) -> dict[str, uuid.UUID]:
    from app.modules.ledger.models import Account

    rows = (await session.execute(select(Account.code, Account.id))).all()
    return {code: aid for code, aid in rows}


async def _upsert(session: AsyncSession, model, values: dict) -> None:
    """Insert, ignoring a conflict on ANY unique constraint.

    Bare ``on_conflict_do_nothing()`` rather than naming the primary key: demo
    rows also collide on natural keys (``templates.name``, ``items.sku``,
    ``users.email``), and an arbiter limited to ``id`` would let those raise.
    """
    await session.execute(pg_insert(model).values(**values).on_conflict_do_nothing())


# ------------------------------------------------------------------- phases


async def phase_periods(session: AsyncSession, rep: Report, run_at: datetime) -> None:
    """Fiscal periods. Must run first: JournalEntry.period_id is RESTRICT NOT NULL."""
    from app.modules.ledger.models import FiscalPeriod
    from app.demo.dataset import did

    made = 0
    # Backdated ERP documents reach ~180 days back, which can cross a year
    # boundary, so open the previous year too.
    for year in (run_at.year - 1, run_at.year):
        for month in range(1, 13):
            start = date(year, month, 1)
            end = (
                date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            ) - timedelta(days=1)
            await _upsert(session, FiscalPeriod, {
                "id": did("period", f"{year}-{month:02d}"),
                "fiscal_year": year, "month": month,
                "start_date": start, "end_date": end, "status": "open",
            })
            made += 1
    await session.commit()
    rep.add("fiscal periods", f"{made} open months ({run_at.year - 1}-{run_at.year})")


async def phase_users(session: AsyncSession, rep: Report) -> list[uuid.UUID]:
    from app.modules.auth.models import User
    from app.demo.dataset import DEMO_EMAIL_DOMAIN, USER_SPECS, did

    pw = hash_password("DemoPass123!")
    ids: list[uuid.UUID] = []
    for handle, name, role, active in USER_SPECS:
        uid = did("user", handle)
        ids.append(uid)
        await _upsert(session, User, {
            "id": uid, "email": f"{handle}@{DEMO_EMAIL_DOMAIN}", "name": name,
            "hashed_password": pw, "role": role, "is_active": active,
        })
    await session.commit()
    rep.add("users", f"{len(ids)} demo agents (password DemoPass123!)")
    return ids


async def phase_contacts(
    session: AsyncSession, rep: Report, agents: list[uuid.UUID], run_at: datetime
) -> list:
    from app.modules.contacts.models import Contact
    from app.modules.categorization.models import ContactTag, Tag, TagSuggestion
    from app.demo.dataset import build_contacts, did, rng

    specs = build_contacts()
    for s in specs:
        r = rng("contactrow", s.key)
        last_seen = run_at - timedelta(days=r.randrange(1, 80), hours=r.randrange(24))
        await _upsert(session, Contact, {
            "id": did("contact", s.key), "phone": s.phone, "name": s.name,
            "company": s.company, "status": s.status,
            "assigned_agent_id": agents[s.agent_idx] if s.agent_idx is not None else None,
            "ai_assigned": s.ai_assigned, "do_not_contact": s.do_not_contact,
            "marketing_opt_out": s.marketing_opt_out,
            "revenue_attributed": Decimal(s.revenue), "estimated_ltv": Decimal(s.ltv),
            "conversation_count": r.randrange(1, 9),
            "last_interaction_at": last_seen, "last_contacted_at": last_seen,
            "last_inbound_at": last_seen - timedelta(hours=r.randrange(1, 40)),
            "created_at": run_at - timedelta(days=r.randrange(80, 200)),
        })
    await session.commit()

    # Tag links drive the /settings/tags usage counts; suggestions drive
    # /tag-review, so seed all three review states.
    tags = (await session.execute(select(Tag.id, Tag.name))).all()
    links = sugg = 0
    if tags:
        for i, s in enumerate(specs):
            r = rng("tagging", s.key)
            for tid, _name in r.sample(tags, k=min(len(tags), r.randrange(0, 4))):
                await session.execute(
                    pg_insert(ContactTag)
                    .values(contact_id=did("contact", s.key), tag_id=tid,
                            approved_by=agents[0], approved_at=run_at)
                    .on_conflict_do_nothing()
                )
                links += 1
            if i % 3 == 0:
                tid, _name = r.choice(tags)
                status = ["pending", "approved", "rejected"][(i // 3) % 3]
                reviewed = status != "pending"
                await _upsert(session, TagSuggestion, {
                    "id": did("suggestion", s.key), "contact_id": did("contact", s.key),
                    "tag_id": tid,
                    "confidence": Decimal(str(round(r.uniform(0.62, 0.98), 3))),
                    "reason": "Mentioned matching products in a recent conversation.",
                    "status": status,
                    "reviewed_by": agents[0] if reviewed else None,
                    "reviewed_at": (
                        run_at - timedelta(days=r.randrange(1, 20)) if reviewed else None
                    ),
                    "created_at": run_at - timedelta(days=r.randrange(1, 40)),
                })
                sugg += 1
    await session.commit()
    rep.add("contacts", f"{len(specs)} contacts, {links} tag links, {sugg} suggestions")
    return specs


async def phase_conversations(
    session: AsyncSession, rep: Report, specs: list, agents: list[uuid.UUID],
    run_at: datetime,
) -> None:
    from app.modules.conversations.models import Conversation
    from app.modules.messaging.models import Message
    from app.modules.ai.models import AIEvent
    from app.demo.dataset import (
        CONVERSATION_STATES, HISTORY_DAYS, INBOUND_LINES, OUTBOUND_LINES,
        did, message_timestamp, rng, weighted_day_offset,
    )

    convs = msgs = events = 0
    for idx, state in enumerate(CONVERSATION_STATES):
        s = specs[idx % len(specs)]
        r = rng("conv", str(idx))
        cid = did("conversation", str(idx))
        locked = state == "HUMAN_ASSIGNED"
        # A terminal outreach_state keeps engagement_sweep_task from ever
        # selecting this row and firing a real Meta send.
        await _upsert(session, Conversation, {
            "id": cid, "contact_id": did("contact", s.key), "state": state,
            "outreach_state": "CONVERTED" if idx % 2 else "UNRESPONSIVE",
            "ai_enabled": state == "AI_ACTIVE",
            "locked_by": agents[2] if locked else None,
            # Far-future TTL so expire_stale_locks_task does not reap the lock.
            "lock_expires_at": run_at + timedelta(days=30) if locked else None,
            "created_at": run_at - timedelta(days=r.randrange(20, HISTORY_DAYS)),
        })
        convs += 1

        last_ts = None
        prev_id = None
        for m in range(r.randrange(8, 28)):
            ts = message_timestamp(r, run_at, weighted_day_offset(r, run_at, HISTORY_DAYS))
            inbound = r.random() < 0.45
            mid = did("message", f"{idx}:{m}")
            # Terminal delivery_status only — queued/pending/draft are exactly
            # what the outbound dispatch path picks up.
            status = "delivered" if inbound else r.choices(
                ["read", "delivered", "sent", "failed"], weights=[45, 30, 10, 4]
            )[0]
            await _upsert(session, Message, {
                "id": mid, "conversation_id": cid,
                "direction": "inbound" if inbound else "outbound",
                "sender_type": "contact" if inbound else ("ai" if r.random() < 0.5 else "agent"),
                "content": r.choice(INBOUND_LINES if inbound else OUTBOUND_LINES),
                "delivery_status": status,
                "msg_type": r.choices(["text", "image", "audio"], weights=[88, 8, 4])[0],
                "meta_message_id": f"wamid.DEMO{mid.hex[:20]}",
                "cost": None if inbound else Decimal(str(round(r.uniform(0.018, 0.049), 4))),
                "context_message_id": prev_id if (m and r.random() < 0.12) else None,
                "created_at": ts,
            })
            msgs += 1
            prev_id = mid
            last_ts = ts if last_ts is None or ts > last_ts else last_ts

            if not inbound and r.random() < 0.3:
                await _upsert(session, AIEvent, {
                    "id": did("aievent", f"{idx}:{m}"), "conversation_id": cid,
                    "request": {"prompt": "draft_reply"},
                    "response": {"usage": {"input_tokens": r.randrange(400, 2600),
                                           "output_tokens": r.randrange(20, 320)}},
                    "intent": r.choice(
                        ["price_query", "stock_query", "greeting", "negotiation"]
                    ),
                    "confidence": Decimal(str(round(r.uniform(0.55, 0.99), 3))),
                    "latency_ms": r.randrange(400, 3200),
                    "cost_estimate": Decimal(str(round(r.uniform(0.0008, 0.021), 4))),
                    "error": "rate_limited" if r.random() < 0.04 else None,
                    "created_at": ts,
                })
                events += 1

        if last_ts is not None:
            await session.execute(
                text("UPDATE conversations SET last_message_at = :t WHERE id = :i"),
                {"t": last_ts, "i": cid},
            )
        await session.commit()

    rep.add("conversations", f"{convs} convs, {msgs} messages, {events} AI events")


async def phase_campaigns(
    session: AsyncSession, rep: Report, specs: list, agents: list[uuid.UUID],
    run_at: datetime,
) -> None:
    from app.modules.templates.models import Template
    from app.modules.campaigns.models import Campaign, CampaignCategory, CampaignRecipient
    from app.demo.dataset import (
        CAMPAIGN_CATEGORIES, CAMPAIGN_SPECS, TEMPLATE_SPECS, did, rng,
    )

    for name, status, category, body in TEMPLATE_SPECS:
        await _upsert(session, Template, {
            "id": did("template", name), "name": name, "status": status,
            "category": category, "language": "en", "body": body,
            "meta_template_id": f"meta_{name}",
        })
    for cname, desc, color in CAMPAIGN_CATEGORIES:
        await _upsert(session, CampaignCategory, {
            "id": did("campcat", cname), "name": cname,
            "description": desc, "color": color,
        })
    await session.commit()

    approved = [t[0] for t in TEMPLATE_SPECS if t[1] == "approved"]
    recips = 0
    for i, (name, status, ctype, days_ago, aud, sent, deliv, failed, resp) in enumerate(
        CAMPAIGN_SPECS
    ):
        r = rng("campaign", name)
        started = run_at - timedelta(days=days_ago) if days_ago else None
        await _upsert(session, Campaign, {
            "id": did("campaign", name), "name": name, "status": status, "type": ctype,
            "template_id": did("template", approved[i % len(approved)]),
            "category_id": did("campcat", CAMPAIGN_CATEGORIES[i % 5][0]),
            "created_by": agents[0],
            "audience_filter": {"status": ["active", "interested"]},
            "audience_count": aud, "sent_count": sent, "delivered_count": deliv,
            "failed_count": failed, "response_count": resp,
            "started_at": started,
            "completed_at": (
                started + timedelta(hours=2) if started and status != "draft" else None
            ),
            "scheduled_at": None, "next_run_at": None,
            "created_at": started or run_at,
        })
        if sent:
            # Spread the sends over two weeks so the campaign and template
            # daily rollups have shape instead of one spike.
            delivered_cut = int(45 * deliv / max(sent, 1))
            for k in range(min(sent, 45)):
                # (i*13 + k) mod 60 is distinct across k in 0..44, satisfying
                # uq_campaign_recipients_campaign_contact.
                s = specs[(i * 13 + k) % len(specs)]
                day = run_at - timedelta(days=days_ago - (k % 14))
                ok = k < delivered_cut
                await session.execute(
                    pg_insert(CampaignRecipient).values(
                        id=did("recipient", f"{name}:{k}"),
                        campaign_id=did("campaign", name),
                        contact_id=did("contact", s.key),
                        status="delivered" if ok else "failed",
                        sent_at=day, delivered_at=day if ok else None,
                        failed_at=None if ok else day,
                        responded=r.random() < 0.26,
                        # Never OUTREACH_SENT — that is what the cold-followup
                        # branch of the engagement sweep selects on.
                        outreach_state="CONVERTED" if r.random() < 0.3 else "UNRESPONSIVE",
                        attempt_count=1, created_at=day,
                    ).on_conflict_do_nothing()
                )
                recips += 1
        await session.commit()

    # One future-dated scheduled campaign: exercises the scheduling UI while
    # staying outside find_due_for_scheduler's `scheduled_at <= now` predicate.
    await _upsert(session, Campaign, {
        "id": did("campaign", "Upcoming Diwali Promo"), "name": "Upcoming Diwali Promo",
        "status": "scheduled", "type": "scheduled",
        "template_id": did("template", approved[0]),
        "category_id": did("campcat", "Seasonal"), "created_by": agents[0],
        "audience_filter": {"status": ["active"]}, "audience_count": 88,
        "scheduled_at": run_at + timedelta(days=21), "created_at": run_at,
    })
    await session.commit()
    rep.add("campaigns", f"{len(CAMPAIGN_SPECS) + 1} campaigns, {recips} recipients, "
                         f"{len(TEMPLATE_SPECS)} templates")


async def phase_market(
    session: AsyncSession, rep: Report, specs: list, agents: list[uuid.UUID],
    run_at: datetime,
) -> None:
    from app.modules.market.models import (
        ContactProductTag, Deal, MarketMessage, MarketMessageProduct, Product,
        SavedSearch, SearchEvent,
    )
    from app.demo.dataset import (
        COLORS, GROUP_NAMES, MARKET_BUY_TEMPLATES, MARKET_SELL_TEMPLATES,
        REGIONS, STORAGES, did, rng,
    )

    products = (await session.execute(select(Product.id, Product.canonical_name))).all()
    if not products:
        rep.add("market", "skipped (products not seeded by migrations)")
        return

    made = resolved = 0
    for i in range(220):
        r = rng("market", str(i))
        buy = i % 2 == 0
        pid, pname = products[i % len(products)]
        # The first slice is timestamped inside the expiry window so /market is
        # populated immediately after seeding; the rest are the searchable
        # history that market-expire-messages has already aged out.
        fresh = i < 60
        if fresh:
            captured = run_at - timedelta(
                minutes=r.randrange(2, 35) if buy else r.randrange(5, 2000)
            )
        else:
            captured = run_at - timedelta(days=r.randrange(1, 60), hours=r.randrange(24))
        expires = captured + (timedelta(minutes=45) if buy else timedelta(hours=48))
        body = r.choice(MARKET_BUY_TEMPLATES if buy else MARKET_SELL_TEMPLATES).format(
            product=pname, storage=r.choice(STORAGES), region=r.choice(REGIONS),
            color=r.choice(COLORS), qty=r.randrange(5, 500),
            price=f"{r.randrange(900, 6200):,}",
        )
        review = r.choices(["AUTO", "PENDING", "REVIEWED", "DISMISSED"],
                           weights=[55, 20, 18, 7])[0]
        # A stale PENDING row would be flipped to UNREVIEWED_EXPIRED by the
        # sweep anyway, so only fresh leads sit in the review queue.
        if review == "PENDING" and not fresh:
            review = "REVIEWED"
        mid = did("marketmsg", str(i))
        contact = specs[i % len(specs)]
        await _upsert(session, MarketMessage, {
            "id": mid, "source_type": "group", "source_id": f"grp-{i % 6}",
            "sender_raw": contact.phone, "sender_name": contact.name,
            "group_name": GROUP_NAMES[i % len(GROUP_NAMES)],
            "side": "BUY" if buy else "SELL",
            "raw_text": body, "normalized_text": body.lower(),
            "captured_at": captured, "expires_at": expires,
            "status": "ACTIVE" if expires > run_at else "EXPIRED",
            "review_status": review,
            "dedup_hash": did("dedup", str(i)).hex,
            "contact_id": did("contact", contact.key),
            "msg_type": "text", "seen_count": r.randrange(1, 4),
            "extracted_attributes": {"storage": r.choice(STORAGES),
                                     "region": r.choice(REGIONS)},
            "created_at": captured,
            "updated_at": captured + timedelta(seconds=r.randrange(45, 900)),
        })
        made += 1
        await session.execute(
            pg_insert(MarketMessageProduct).values(
                id=did("mmp", str(i)), market_message_id=mid, product_id=pid,
                qty=r.randrange(5, 400),
                unit_price=Decimal(str(r.randrange(900, 6200))), currency="AED",
                confidence=Decimal(str(round(r.uniform(0.62, 0.99), 3))),
                resolver="keyword" if r.random() < 0.75 else "llm",
                side="BUY" if buy else "SELL",
                spec=r.choice(REGIONS), color=r.choice(COLORS),
            ).on_conflict_do_nothing()
        )
        resolved += 1

        if i < 90:
            await session.execute(
                pg_insert(ContactProductTag).values(
                    contact_id=did("contact", contact.key), product_id=pid,
                    side_buy_count=r.randrange(0, 6), side_sell_count=r.randrange(0, 6),
                    observation_count=r.randrange(1, 12),
                    first_seen_at=captured - timedelta(days=20), last_seen_at=captured,
                ).on_conflict_do_nothing()
            )
        if i % 40 == 0:
            await session.commit()
    await session.commit()

    for i in range(6):
        pid, pname = products[i % len(products)]
        await _upsert(session, SavedSearch, {
            "id": did("savedsearch", str(i)), "user_id": agents[i % len(agents)],
            "name": f"{pname} watchlist", "query_text": pname,
            "resolved_product_ids": [str(pid)], "filters": {"side": "SELL"},
        })
    for i in range(40):
        r = rng("searchevent", str(i))
        pid, pname = products[i % len(products)]
        await _upsert(session, SearchEvent, {
            "id": did("searchevent", str(i)), "user_id": agents[i % len(agents)],
            "query_text": pname, "resolved_product_ids": [str(pid)],
            "buy_result_count": r.randrange(0, 14),
            "sell_result_count": r.randrange(0, 20),
            "executed_at": run_at - timedelta(days=r.randrange(0, 30)),
        })
    for i in range(12):
        r = rng("deal", str(i))
        pid, _ = products[i % len(products)]
        await _upsert(session, Deal, {
            "id": did("deal", str(i)),
            "buyer_contact_id": did("contact", specs[i].key),
            "seller_contact_id": did("contact", specs[i + 20].key),
            "product_id": pid, "qty": r.randrange(10, 300),
            "target_price": Decimal(str(r.randrange(900, 6000))),
            "status": ["matched", "contacted", "negotiating",
                       "confirmed", "closed", "lost"][i % 6],
            "created_by": agents[0],
            "created_at": run_at - timedelta(days=r.randrange(1, 50)),
        })
    await session.commit()
    rep.add("market", f"{made} messages, {resolved} resolutions, 6 searches, 12 deals")


async def phase_inventory(session: AsyncSession, rep: Report, accounts: dict) -> None:
    from app.modules.inventory.models import Item, Location, Warehouse
    from app.modules.ledger.models import Uom
    from app.demo.dataset import ITEM_SPECS, LOCATION_SPECS, WAREHOUSE_SPECS, did

    uom_id = (
        await session.execute(select(Uom.id).where(Uom.code == "PCS"))
    ).scalar_one_or_none()
    if uom_id is None:
        uom_id = (await session.execute(select(Uom.id).limit(1))).scalar_one()

    for code, name in WAREHOUSE_SPECS:
        await _upsert(session, Warehouse, {
            "id": did("warehouse", code), "code": code, "name": name, "is_active": True,
        })
    await session.commit()
    # GRN confirm resolves the receiving location as the first active one in
    # the warehouse, so every warehouse needs at least one.
    for wcode, lcode, _desc in LOCATION_SPECS:
        await _upsert(session, Location, {
            "id": did("location", f"{wcode}:{lcode}"),
            "warehouse_id": did("warehouse", wcode), "code": lcode, "is_active": True,
        })
    await session.commit()

    for sku, name, brand, category, nature, pcost, sprice in ITEM_SPECS:
        await _upsert(session, Item, {
            "id": did("item", sku), "sku": sku, "name": name, "brand": brand,
            "model": name, "category": category, "nature": nature,
            "uom_id": uom_id, "valuation_method": "moving_average",
            "reorder_level": 10, "reorder_qty": Decimal("25"),
            "default_purchase_price": Decimal(pcost),
            "default_sale_price": Decimal(sprice),
            "inventory_account_id": accounts["1200"],
            "cogs_account_id": accounts["5100"],
            "revenue_account_id": accounts["4100"],
            "is_sales_item": True, "is_purchase_item": True, "is_active": True,
        })
    await session.commit()
    rep.add("inventory", f"{len(WAREHOUSE_SPECS)} warehouses, "
                         f"{len(LOCATION_SPECS)} locations, {len(ITEM_SPECS)} items")


async def phase_opening(
    session: AsyncSession, rep: Report, accounts: dict, actor: uuid.UUID, run_at: datetime
) -> None:
    """Fund the bank before any supplier payment can overdraw it."""
    from app.modules.ledger.posting import PostingService
    from app.modules.ledger.schemas import JournalEntryCreateRequest

    try:
        await PostingService(session).post(
            JournalEntryCreateRequest(
                posting_date=date(run_at.year, 1, 5),
                description="Opening share capital",
                voucher_type="opening_entry", is_opening=True,
                lines=[
                    _jline(accounts["1020"], "Bank opening balance",
                           dr=Decimal("5000000")),
                    _jline(accounts["3100"], "Share capital", cr=Decimal("5000000")),
                ],
            ),
            actor_id=actor, source_type="demo_opening",
            source_id=uuid.uuid5(uuid.NAMESPACE_DNS, "demo-opening"),
        )
        await session.commit()
        rep.add("opening entry", "Dr 1020 5,000,000 / Cr 3100")
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        rep.fail("opening entry", f"{type(exc).__name__}: {exc}")


async def phase_procurement(
    session: AsyncSession, rep: Report, specs: list, agents: list[uuid.UUID],
    run_at: datetime,
) -> dict[int, int]:
    """PO -> GRN(confirm) -> bill(issue) -> partial payment.

    Returns received qty per ITEM_SPECS index so the dispatch phase can stay
    inside what is actually on the shelf.
    """
    from app.modules.procurement.schemas import (
        GRNCreateRequest, GRNLineRequest, POCreateRequest, POLineRequest,
    )
    from app.modules.procurement.service import GRNService, POService
    from app.modules.payables.schemas import (
        BillCreateRequest, BillLineRequest, PaymentAllocationRequest,
        PaymentCreateRequest,
    )
    from app.modules.payables.service import BillService, SupplierPaymentService
    from app.demo.dataset import AP_AGEING_PLAN, ITEM_SPECS, did

    today = run_at.date()
    suppliers = [s for s in specs if s.role == "supplier"]
    actor = agents[0]
    received: dict[int, int] = {}
    grns = bills = payments = 0

    for i, (_bucket, overdue, amount) in enumerate(AP_AGEING_PLAN):
        sup = suppliers[i % len(suppliers)]
        item_idx = i % len(ITEM_SPECS)
        sku, name = ITEM_SPECS[item_idx][0], ITEM_SPECS[item_idx][1]
        pcost = ITEM_SPECS[item_idx][5]
        qty = max(1, amount // pcost)
        order_date = today - timedelta(days=overdue + 45)
        try:
            po = await POService(session).create(POCreateRequest(
                supplier_id=did("contact", sup.key), order_date=order_date,
                expected_date=order_date + timedelta(days=14),
                lines=[POLineRequest(item_id=did("item", sku), description=name,
                                     qty=Decimal(qty), unit_cost=Decimal(pcost))],
                remarks=f"Demo purchase {i + 1}",
            ))
            await POService(session).issue(po.id, actor)
            # No serial_no: GRN confirm takes the non-serialized path and
            # updates StockBalance, which is what DispatchService draws down.
            grn = await GRNService(session).create(GRNCreateRequest(
                po_id=po.id, warehouse_id=did("warehouse", "DXB-MAIN"),
                receipt_date=order_date + timedelta(days=10),
                lines=[GRNLineRequest(item_id=did("item", sku),
                                      qty_received=Decimal(qty),
                                      unit_cost=Decimal(pcost))],
            ))
            await GRNService(session).confirm(grn.id, actor)
            await session.commit()
            grns += 1
            received[item_idx] = received.get(item_idx, 0) + qty
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            rep.fail("procurement", f"{type(exc).__name__}: {exc}")
            return received

        try:
            # Bill total matches the GRN value, so 2200 GRN Accrual nets to zero.
            bill = await BillService(session).create(BillCreateRequest(
                supplier_id=did("contact", sup.key),
                posting_date=order_date + timedelta(days=12),
                due_date=today - timedelta(days=overdue),
                po_id=po.id, grn_id=grn.id,
                lines=[BillLineRequest(item_id=did("item", sku), description=name,
                                       qty=Decimal(qty), unit_cost=Decimal(pcost))],
            ))
            await BillService(session).issue(bill.id, actor)
            await session.commit()
            bills += 1
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            rep.fail("payables", f"{type(exc).__name__}: {exc}")
            return received

        # Part-pay every third bill: it stays ISSUED and keeps its ageing
        # bucket, while AP and Bank both show real movement.
        if i % 3 == 0:
            part = Decimal(qty * pcost) * Decimal("0.4")
            try:
                svc = SupplierPaymentService(session)
                pay = await svc.create(PaymentCreateRequest(
                    supplier_id=did("contact", sup.key),
                    payment_date=today - timedelta(days=max(overdue - 5, 1)),
                    amount=part, payment_method="bank_transfer",
                    reference=f"AP-TT-{i:04d}",
                ))
                await svc.allocate(
                    pay.id, PaymentAllocationRequest(bill_id=bill.id, amount=part)
                )
                # reconcile() posts Dr 2100 AP / Cr 1020 Bank itself.
                await svc.reconcile(pay.id, actor)
                await session.commit()
                payments += 1
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                rep.add("ap payments",
                        f"stopped at {payments}: {type(exc).__name__}: {exc}")

    rep.add("procurement", f"{grns} PO+GRN confirmed (Dr 1200 / Cr 2200)")
    rep.add("payables", f"{bills} bills issued (Dr 2200 / Cr 2100), {payments} part-paid")
    return received


async def phase_serialized(
    session: AsyncSession, rep: Report, agents: list[uuid.UUID], run_at: datetime
) -> None:
    """One serialized receipt + dispatch, so stock_units is not empty.

    GRN confirm branches on the presence of ``serial_no``, not on the item's
    ``nature``, so this is the only path that creates StockUnit rows.
    """
    from app.modules.procurement.schemas import GRNCreateRequest, GRNLineRequest
    from app.modules.procurement.service import GRNService
    from app.modules.inventory.models import StockUnit
    from app.modules.fulfilment.schemas import DispatchCreateRequest, DispatchLineRequest
    from app.modules.fulfilment.service import DispatchService
    from app.demo.dataset import ITEM_SPECS, did

    sku, name = ITEM_SPECS[0][0], ITEM_SPECS[0][1]
    pcost = ITEM_SPECS[0][5]
    # GRNLineRequest.serial_no is a single comma-joined string capped at 100
    # chars, so keep the tokens short: 8 x "DSN-0001" + separators = 71.
    serials = ",".join(f"DSN-{n:04d}" for n in range(1, 9))
    receipt_date = run_at.date() - timedelta(days=40)
    try:
        grn = await GRNService(session).create(GRNCreateRequest(
            po_id=None, warehouse_id=did("warehouse", "DXB-MAIN"),
            receipt_date=receipt_date,
            lines=[GRNLineRequest(item_id=did("item", sku), serial_no=serials,
                                  qty_received=Decimal("8"), unit_cost=Decimal(pcost))],
        ))
        await GRNService(session).confirm(grn.id, agents[0])
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        rep.add("serialized stock", f"skipped: {type(exc).__name__}: {exc}")
        return

    units = (await session.execute(
        select(StockUnit.id).where(StockUnit.serial_no.like("DSN-%")).limit(2)
    )).scalars().all()
    try:
        dp = await DispatchService(session).create(DispatchCreateRequest(
            so_id=None, dispatch_date=receipt_date + timedelta(days=6),
            lines=[DispatchLineRequest(stock_unit_id=u, item_id=did("item", sku),
                                       qty=Decimal("1"), unit_cost=Decimal(pcost))
                   for u in units],
        ))
        await DispatchService(session).confirm(dp.id, agents[0])
        await session.commit()
        rep.add("serialized stock", f"8 units of {name} received, {len(units)} dispatched")
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        rep.add("serialized stock",
                f"8 units received, dispatch skipped: {type(exc).__name__}: {exc}")


async def phase_fulfilment(
    session: AsyncSession, rep: Report, specs: list, agents: list[uuid.UUID],
    received: dict[int, int], run_at: datetime,
) -> None:
    from app.modules.fulfilment.schemas import (
        DispatchCreateRequest, DispatchLineRequest, SOCreateRequest, SOLineRequest,
    )
    from app.modules.fulfilment.service import DispatchService, SOService
    from app.demo.dataset import ITEM_SPECS, did, rng

    today = run_at.date()
    customers = [s for s in specs if s.role == "customer"]
    actor = agents[0]
    done = 0
    for i in range(8):
        r = rng("so", str(i))
        item_idx = i % len(ITEM_SPECS)
        on_hand = received.get(item_idx, 0)
        if on_hand < 3:
            continue
        # Stay well inside what the GRNs put on the shelf: dispatch confirm
        # raises ConflictError if no single location holds line.qty.
        qty = min(r.randrange(2, 9), on_hand - 1)
        cust = customers[i % len(customers)]
        sku, name = ITEM_SPECS[item_idx][0], ITEM_SPECS[item_idx][1]
        pcost, sprice = ITEM_SPECS[item_idx][5], ITEM_SPECS[item_idx][6]
        order_date = today - timedelta(days=r.randrange(10, 80))
        try:
            so = await SOService(session).create(SOCreateRequest(
                customer_id=did("contact", cust.key), order_date=order_date,
                lines=[SOLineRequest(item_id=did("item", sku), description=name,
                                     qty=Decimal(qty), unit_price=Decimal(sprice))],
            ))
            await SOService(session).confirm(so.id, actor)
            # unit_cost is passed explicitly: GRN confirm never populates
            # StockBalance.avg_cost, so COGS would otherwise post as zero.
            dp = await DispatchService(session).create(DispatchCreateRequest(
                so_id=so.id, dispatch_date=order_date + timedelta(days=3),
                lines=[DispatchLineRequest(item_id=did("item", sku), qty=Decimal(qty),
                                           unit_cost=Decimal(pcost))],
            ))
            await DispatchService(session).confirm(dp.id, actor)
            await session.commit()
            done += 1
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            rep.add("fulfilment", f"stopped after {done}: {type(exc).__name__}: {exc}")
            break
    rep.add("fulfilment", f"{done} SO+dispatch confirmed (Dr 5100 / Cr 1200)")


async def phase_receivables(
    session: AsyncSession, rep: Report, specs: list, accounts: dict,
    agents: list[uuid.UUID], run_at: datetime,
) -> None:
    from app.modules.ledger.posting import PostingService
    from app.modules.ledger.schemas import JournalEntryCreateRequest
    from app.modules.receivables.schemas import (
        InvoiceCreateRequest, InvoiceLineRequest, PaymentAllocationRequest,
        PaymentCreateRequest,
    )
    from app.modules.receivables.service import InvoiceService, PaymentService
    from app.demo.dataset import AR_AGEING_PLAN, ITEM_SPECS, did

    today = run_at.date()
    customers = [s for s in specs if s.role == "customer"]
    actor = agents[0]
    invoices = paid = 0

    for i, (_bucket, overdue, amount) in enumerate(AR_AGEING_PLAN):
        cust = customers[i % len(customers)]
        item_idx = i % len(ITEM_SPECS)
        sku, name = ITEM_SPECS[item_idx][0], ITEM_SPECS[item_idx][1]
        sprice = ITEM_SPECS[item_idx][6]
        qty = max(1, amount // sprice)
        total = Decimal(qty * sprice)
        due = today - timedelta(days=overdue)
        posting_date = due - timedelta(days=30)
        try:
            inv = await InvoiceService(session).create(InvoiceCreateRequest(
                customer_id=did("contact", cust.key), posting_date=posting_date,
                due_date=due,
                lines=[InvoiceLineRequest(item_id=did("item", sku), description=name,
                                          qty=Decimal(qty), unit_price=Decimal(sprice))],
                remarks=f"Demo invoice {i + 1}",
            ))
            await InvoiceService(session).issue(inv.id, actor)
            await session.commit()
            invoices += 1
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            rep.fail("receivables", f"{type(exc).__name__}: {exc}")
            return

        # Settle every third invoice so /finance/receivables shows paid rows.
        if i % 3 != 0:
            continue
        try:
            svc = PaymentService(session)
            pay = await svc.create(PaymentCreateRequest(
                customer_id=did("contact", cust.key),
                payment_date=due - timedelta(days=2), amount=total,
                payment_method="bank_transfer", reference=f"AR-TT-{i:04d}",
            ))
            await svc.allocate(
                pay.id, [PaymentAllocationRequest(invoice_id=inv.id, amount=total)]
            )
            await svc.reconcile(pay.id, actor)
            # AR reconcile() only emits finance.payment_reconciled, which no
            # bridge handler subscribes to, so the relief journal is posted
            # here. 1100 is a control account: is_system_generated=True.
            await PostingService(session).post(
                JournalEntryCreateRequest(
                    posting_date=due - timedelta(days=2),
                    description=f"Customer payment {pay.payment_no}",
                    voucher_type="bank_entry",
                    lines=[
                        _jline(accounts["1020"], "Bank receipt", dr=total),
                        _jline(accounts["1100"], "Clear receivable", cr=total,
                               party_type="customer",
                               party_id=did("contact", cust.key)),
                    ],
                ),
                actor_id=actor, source_type="customer_payment", source_id=pay.id,
                is_system_generated=True,
            )
            await session.commit()
            paid += 1
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            rep.add("ar payments", f"stopped at {paid}: {type(exc).__name__}: {exc}")

    rep.add("receivables", f"{invoices} invoices issued (Dr 1100 / Cr 4100), {paid} paid")


async def phase_opex(
    session: AsyncSession, rep: Report, accounts: dict, actor: uuid.UUID, run_at: datetime
) -> None:
    from app.modules.ledger.posting import PostingService
    from app.modules.ledger.schemas import JournalEntryCreateRequest
    from app.demo.dataset import rng

    today = run_at.date()
    posted = 0
    plan = [("6100", "Shipping & freight"), ("6200", "Bank charges"),
            ("6500", "Office rent"), ("6500", "Utilities"),
            ("6100", "Courier charges"), ("6200", "FX charges"),
            ("6500", "Software subscriptions"), ("6100", "Customs clearance")]
    for i, (code, label) in enumerate(plan):
        r = rng("opex", str(i))
        amt = Decimal(r.randrange(3, 60) * 500)
        try:
            await PostingService(session).post(
                JournalEntryCreateRequest(
                    posting_date=today - timedelta(days=r.randrange(5, 120)),
                    description=label, voucher_type="bank_entry",
                    lines=[_jline(accounts[code], label, dr=amt),
                           _jline(accounts["1020"], "Paid from bank", cr=amt)],
                ),
                actor_id=actor, source_type="demo_opex",
                source_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"demo-opex-{i}"),
            )
            await session.commit()
            posted += 1
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            rep.add("opex journals", f"stopped at {posted}: {type(exc).__name__}: {exc}")
            break
    rep.add("opex journals", f"{posted} posted")


async def phase_close_pl(
    session: AsyncSession, rep: Report, accounts: dict, run_at: datetime
) -> None:
    """Close every P&L account into 3300 Current Year Earnings.

    erp_reporting.balance_sheet() sums only asset/liability/equity accounts and
    never derives retained earnings from the P&L, so without this entry the
    balance sheet is out by exactly the net profit. Closing each revenue/COGS/
    OPEX account individually (rather than netting them into one) leaves every
    P&L account at zero, which is what makes A = L + E hold.
    """
    from app.modules.ledger.posting import PostingService
    from app.modules.ledger.schemas import JournalEntryCreateRequest

    rows = (await session.execute(text("""
        SELECT a.code,
               COALESCE(SUM(jl.dr_base), 0) - COALESCE(SUM(jl.cr_base), 0) AS net_dr
        FROM journal_lines jl
        JOIN accounts a ON a.id = jl.account_id
        JOIN journal_entries je ON je.id = jl.entry_id
        WHERE je.status = 'posted' AND a.type IN ('revenue', 'cogs', 'opex')
        GROUP BY a.code
        HAVING COALESCE(SUM(jl.dr_base), 0) - COALESCE(SUM(jl.cr_base), 0) <> 0
    """))).mappings().all()
    if not rows:
        rep.add("close P&L", "nothing to close")
        return

    lines = []
    net_dr = Decimal("0")
    for row in rows:
        bal = Decimal(str(row["net_dr"]))
        net_dr += bal
        # Reverse each account's balance: credit a debit balance, debit a credit one.
        lines.append(
            _jline(accounts[row["code"]], f"Close {row['code']}", cr=bal) if bal > 0
            else _jline(accounts[row["code"]], f"Close {row['code']}", dr=-bal)
        )

    # Revenue carries a credit balance, so a profit means net_dr < 0.
    profit = -net_dr
    lines.append(
        _jline(accounts["3300"], "Current year earnings", cr=profit) if profit > 0
        else _jline(accounts["3300"], "Current year loss", dr=-profit)
    )
    try:
        await PostingService(session).post(
            JournalEntryCreateRequest(
                posting_date=run_at.date(),
                description="Period close - transfer P&L to current year earnings",
                voucher_type="journal_entry", lines=lines,
            ),
            actor_id=None, is_system_generated=True,
            source_type="demo_period_close",
            source_id=uuid.uuid5(uuid.NAMESPACE_DNS, "demo-close"),
        )
        await session.commit()
        rep.add("close P&L", f"{len(rows)} accounts closed, net profit {profit} -> 3300")
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        rep.add("close P&L", f"skipped: {type(exc).__name__}: {exc}")


async def phase_audit_settings(
    session: AsyncSession, rep: Report, agents: list[uuid.UUID], run_at: datetime
) -> None:
    from app.modules.audit.models import AuditLog
    from app.modules.settings.models import AppSetting
    from app.demo.dataset import AUDIT_ACTIONS, did, rng

    for i in range(120):
        r = rng("audit", str(i))
        action, entity = AUDIT_ACTIONS[i % len(AUDIT_ACTIONS)]
        await _upsert(session, AuditLog, {
            "id": did("audit", str(i)), "actor_type": "user",
            "actor_id": agents[i % len(agents)], "action": action,
            "entity_type": entity, "entity_id": did("contact", f"c{i % 60:03d}"),
            "after_state": {"note": "demo audit entry"},
            "created_at": run_at - timedelta(days=r.randrange(0, 60),
                                             hours=r.randrange(24)),
        })
    for key, value in [
        ("ops.timezone", {"tz": "Asia/Dubai"}),
        ("ops.business_hours", {"enabled": True, "start": "09:00", "end": "19:00"}),
        ("ops.campaign_daily_cap", {"enabled": True, "limit": 800}),
        ("campaign.global_rate_per_second", {"rate": 8}),
    ]:
        await session.execute(
            pg_insert(AppSetting)
            .values(id=did("setting", key), key=key, value=value, scope="global")
            .on_conflict_do_update(index_elements=["scope", "key"], set_={"value": value})
        )
    await session.commit()
    rep.add("audit + settings", "120 audit rows, 4 settings")


# --------------------------------------------------------------- sync tail


def backfill_analytics(days: int, rep: Report) -> None:
    """Roll the raw data up into the analytics tables.

    The aggregators are sync by design (they run under Celery), so this runs
    outside the async session once everything else has committed.
    """
    from app.db.session import sync_session_factory
    from app.modules.analytics.aggregator import (
        upsert_campaign_daily, upsert_global_daily, upsert_hourly_metrics,
        upsert_template_daily,
    )

    today = datetime.now(tz=UTC).date()
    ok = 0
    for offset in range(days, -1, -1):
        day = today - timedelta(days=offset)
        try:
            with sync_session_factory() as s:
                upsert_global_daily(s, day)
                upsert_campaign_daily(s, day)
                upsert_template_daily(s, day)
                upsert_hourly_metrics(s, day)
                s.commit()
            ok += 1
        except Exception as exc:  # noqa: BLE001
            rep.add("analytics", f"day {day} failed: {type(exc).__name__}: {exc}")
            break
    rep.add("analytics", f"{ok} days rolled up")


def verify(rep: Report) -> None:
    """Assert the ledger ties and that no seeded row can trigger a real send."""
    from app.db.session import sync_session_factory

    checks = [
        ("unbalanced entries", """
            SELECT count(*) FROM (
              SELECT entry_id FROM journal_lines
              GROUP BY entry_id HAVING sum(dr_base) <> sum(cr_base)) x"""),
        ("zero-value entries", """
            SELECT count(*) FROM (
              SELECT entry_id FROM journal_lines
              GROUP BY entry_id HAVING sum(dr_base) = 0) x"""),
        ("duplicate source posts", """
            SELECT count(*) FROM (
              SELECT source_type, source_id FROM journal_entries
              WHERE source_id IS NOT NULL
              GROUP BY 1, 2 HAVING count(*) > 1) x"""),
        ("campaigns due now", """
            SELECT count(*) FROM campaigns WHERE status = 'scheduled'
              AND (scheduled_at <= now() OR next_run_at <= now())"""),
        ("sweepable convs", """
            SELECT count(*) FROM conversations
              WHERE outreach_state IS NULL AND ai_enabled"""),
        ("cold-followup recips", """
            SELECT count(*) FROM campaign_recipients
              WHERE outreach_state = 'OUTREACH_SENT' AND responded IS FALSE"""),
        ("sendable messages", """
            SELECT count(*) FROM messages
              WHERE delivery_status IN ('queued', 'pending', 'draft')"""),
    ]
    with sync_session_factory() as s:
        for label, sql in checks:
            got = s.execute(text(sql)).scalar_one()
            if got:
                rep.fail(f"check {label}", f"expected 0, got {got}")
            else:
                rep.add(f"check {label}", "ok (0)")

        tb = s.execute(text("""
            SELECT COALESCE(sum(jl.dr_base) - sum(jl.cr_base), 0)
            FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id
            WHERE je.status = 'posted'""")).scalar_one()
        if Decimal(str(tb)) != 0:
            rep.fail("check trial balance", f"off by {tb}")
        else:
            rep.add("check trial balance", "balanced")

        bs = s.execute(text("""
            SELECT a.type, COALESCE(sum(jl.dr_base) - sum(jl.cr_base), 0) AS net
            FROM journal_lines jl
            JOIN accounts a ON a.id = jl.account_id
            JOIN journal_entries je ON je.id = jl.entry_id
            WHERE je.status = 'posted' AND a.type IN ('asset', 'liability', 'equity')
            GROUP BY a.type""")).mappings().all()
        amounts = {r["type"]: Decimal(str(r["net"])) for r in bs}
        assets = amounts.get("asset", Decimal("0"))
        le = -(amounts.get("liability", Decimal("0")) + amounts.get("equity", Decimal("0")))
        if assets == le:
            rep.add("check balance sheet", f"A = L+E = {assets}")
        else:
            rep.add("check balance sheet",
                    f"A={assets} vs L+E={le} (out by {assets - le})")

        for label, sql in [
            ("daily rollups", "SELECT count(*) FROM analytics_daily_metrics"),
            ("hourly buckets", "SELECT count(DISTINCT hour) FROM analytics_hourly_metrics"),
            ("conv states", "SELECT count(DISTINCT state) FROM conversations"),
            ("active market leads",
             "SELECT count(*) FROM market_messages WHERE status = 'ACTIVE'"),
            ("posted journals",
             "SELECT count(*) FROM journal_entries WHERE status = 'posted'"),
            ("stock units", "SELECT count(*) FROM stock_units"),
            ("unpaid invoices",
             "SELECT count(*) FROM sales_invoices WHERE status <> 'paid'"),
        ]:
            rep.add(f"count {label}", str(s.execute(text(sql)).scalar_one()))


def wipe(rep: Report) -> None:
    from app.db.session import sync_session_factory
    from app.demo.dataset import DEMO_EMAIL_DOMAIN

    with sync_session_factory() as s:
        present = {
            row[0] for row in s.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )).all()
        }
        targets = [t for t in WIPE_TABLES if t in present]
        quoted = ", ".join('"' + t + '"' for t in targets)
        s.execute(text("TRUNCATE " + quoted + " RESTART IDENTITY CASCADE"))
        s.execute(text("DELETE FROM users WHERE email LIKE :pat"),
                  {"pat": "%@" + DEMO_EMAIL_DOMAIN})
        s.commit()
    rep.add("wipe", f"{len(targets)} tables truncated, demo users removed")


def refresh_market(rep: Report) -> None:
    """Re-stamp the newest demo market leads to now.

    market-expire-messages runs every 300s and expires BUY leads 45 minutes and
    SELL leads 48 hours after captured_at, so the /market board empties on its
    own. Run this right before a demo to repopulate it.
    """
    from app.db.session import sync_session_factory

    with sync_session_factory() as s:
        n = s.execute(text("""
            UPDATE market_messages SET
              captured_at = now() - (random() * interval '30 minutes'),
              expires_at  = now() + CASE WHEN side = 'BUY'
                                    THEN interval '45 minutes'
                                    ELSE interval '48 hours' END,
              status = 'ACTIVE',
              review_status = CASE WHEN review_status = 'UNREVIEWED_EXPIRED'
                              THEN 'PENDING' ELSE review_status END
            WHERE id IN (SELECT id FROM market_messages ORDER BY created_at DESC LIMIT 60)
        """)).rowcount
        s.commit()
    rep.add("refresh-market", f"{n} leads re-stamped to now")


# ------------------------------------------------------------------- driver


async def seed_async(rep: Report, run_at: datetime) -> None:
    # Importing anything under app.modules.ledger registers the bridge
    # subscribers at import time (app/modules/ledger/__init__.py). Do NOT call
    # register_bridge_handlers() here: subscribe_async appends without
    # de-duplicating, so a second call double-posts every bridge journal.
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        accounts = await _account_ids(session)
        required = {"1020", "1100", "1200", "2100", "2200", "3100", "3300",
                    "4100", "5100", "6100", "6200", "6500"}
        missing = required - set(accounts)
        if missing:
            rep.fail("preflight", f"chart of accounts missing {sorted(missing)}")
            return

        await phase_periods(session, rep, run_at)
        agents = await phase_users(session, rep)
        specs = await phase_contacts(session, rep, agents, run_at)
        await phase_conversations(session, rep, specs, agents, run_at)
        await phase_campaigns(session, rep, specs, agents, run_at)
        await phase_market(session, rep, specs, agents, run_at)
        await phase_inventory(session, rep, accounts)
        await phase_opening(session, rep, accounts, agents[0], run_at)
        received = await phase_procurement(session, rep, specs, agents, run_at)
        await phase_serialized(session, rep, agents, run_at)
        await phase_fulfilment(session, rep, specs, agents, received, run_at)
        await phase_receivables(session, rep, specs, accounts, agents, run_at)
        await phase_opex(session, rep, accounts, agents[0], run_at)
        await phase_close_pl(session, rep, accounts, run_at)
        await phase_audit_settings(session, rep, agents, run_at)


def main() -> int:
    if os.environ.get("SEED_DEMO") != "1":
        return 0

    import_all_models()
    rep = Report()

    if MODE == "wipe":
        if os.environ.get("SEED_DEMO_ALLOW_WIPE") != "1":
            print("seed_demo: wipe requires SEED_DEMO_ALLOW_WIPE=1", file=sys.stderr)
            return 1
        print("seed_demo: wiping demo data", flush=True)
        wipe(rep)
        return 0

    if MODE == "refresh-market":
        print("seed_demo: refreshing market leads", flush=True)
        refresh_market(rep)
        return 0

    from app.demo.dataset import HISTORY_DAYS

    run_at = datetime.now(tz=UTC)
    print(f"seed_demo: seeding (run_at={run_at.isoformat()})", flush=True)
    asyncio.run(seed_async(rep, run_at))
    if rep.failed:
        print("seed_demo: FAILED - see errors above", file=sys.stderr, flush=True)
        return 1
    backfill_analytics(HISTORY_DAYS, rep)
    verify(rep)
    print("seed_demo: done" if not rep.failed
          else "seed_demo: completed with failed checks", flush=True)
    return 1 if rep.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
