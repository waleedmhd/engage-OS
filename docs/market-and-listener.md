# Market Intelligence Pipeline — Authoritative Reference

> **Audience:** Developers working on the market pipeline. Read the [root README](../README.md) for the system overview first; this document is the deep-dive.

The market intelligence pipeline ingests raw WhatsApp group messages, classifies them as buy/sell leads, extracts structured product attributes, resolves them against a product catalog, routes low-confidence items to a human review queue, surfaces everything in a split-pane matching dashboard, and feeds an outreach-to-deal training chain. This document describes every stage end-to-end.

---

## 1. Architecture overview

```
┌──────────────────────────────────────────────────────────────────────┐
│  LISTENER (Node.js, whatsapp-web.js)                                 │
│                                                                      │
│  WhatsApp group → persistent WebSocket → group_messages (PG, 24h TTL)│
│       │                                                              │
│       │  Pass A: noise gate (divider / opt-out / signup / spam /     │
│       │           chatter deprioritisation / text cleaning)          │
│       │                                                              │
│       ▼                                                              │
│  filter_status='passed' + crm_sync_status='pending'                  │
│       │                                                              │
│       │  Batch POST /api/v1/market/messages                          │
│       │  dedup_hash = SHA-256(source_type | source_id)               │
│       │  Retry with exponential backoff, dead-letter after max       │
└───────┼──────────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────────────────┐
│  BACKEND (FastAPI + Celery)                                          │
│                                                                      │
│  POST /market/messages                                               │
│       │                                                              │
│       ├─ 1. Idempotency: dedup_hash lookup → return existing         │
│       ├─ 2. Contact resolution: upsert_by_phone(sender_raw)          │
│       ├─ 3. Normalize: lowercase, collapse whitespace                │
│       ├─ 4. Side classification: keyword patterns (BUY/SELL/UNKNOWN) │
│       ├─ 5. Brand detection: Apple/Samsung/mixed/non_target          │
│       ├─ 6. Attribute extraction: 14 families (Python port of Pass B+C)│
│       ├─ 7. Product resolution: alias substring match → product IDs  │
│       ├─ 8. Fingerprint dedup: Redis SET NX (soft), hash-only (hard) │
│       ├─ 9. Confidence routing: AUTO / PENDING / UNRESOLVED          │
│       ├─ 10. ContactProductTag increment (AUTO only)                 │
│       └─ 11. LLM fallback dispatch (zero keyword matches or UNKNOWN) │
│                                                                      │
│  Celery tasks:                                                       │
│  • classify_message_task — Haiku 4.5 fallback, acks_late, 3 retries  │
│  • expire_market_messages_task — TTL sweep every 5 min (Celery beat) │
│  • backfill_extracted_attributes_task — one-shot, idempotent         │
└──────────────────────────────────────────────────────────────────────┘
```

**Post-P9 topology:** The listener performs only capture and noise gate (Pass A). Extraction (Pass B + C), product resolution, fingerprinting, confidence routing, and all downstream processing run in the backend. The listener forwards raw messages to `POST /api/v1/market/messages` with retry and dead-letter semantics.

---

## 2. Capture (listener)

### whatsapp-web.js persistent WebSocket

The listener uses `whatsapp-web.js` to maintain a single persistent WebSocket connection to WhatsApp. It connects once on startup (QR scan) and receives every message in real time with 1–5 second latency. There is no polling or group cycling.

Monitored groups are configured via the `MONITORED_GROUPS` env var (comma-separated WhatsApp group JIDs).

### `group_messages` transient buffer

Raw messages land in the listener's PostgreSQL `group_messages` table. Rows are automatically deleted after 24 hours (configurable via `DATA_RETENTION_HOURS`). The table is transient scratch space — the CRM's `market_messages` table is the system of record.

### `filter_status` lifecycle

| Status | Meaning |
|---|---|
| `pending` | Unprocessed — awaiting noise gate |
| `passed` | Passed Pass A — eligible for CRM sync |
| `noise_divider` | Pure divider / emoji-only — dropped |
| `opt_out` | Opt-out / STOP — flagged for compliance, not forwarded |
| `signup_request` | Platform signup prompt — parked, not a lead |
| `noise_network_spam` | GSM-B2B broadcast wrapper — dropped |
| `noise_promo_cta` | Promotional CTA — dropped |
| `noise_join_link` | Registration link — dropped |

### Noise gate (Pass A)

The noise gate runs on a configurable interval (`FILTER_INTERVAL_MINUTES`, default 5). Processing order:

1. **Divider detection** — pure emoji/separator lines below 20 chars → `noise_divider`
2. **Opt-out flagging** — STOP/UNSUBSCRIBE patterns → `opt_out` (never drop, flag for compliance)
3. **Signup parking** — platform signup prompts → `signup_request`
4. **Network spam** — GSM-B2B wrapper text, promo CTAs, join links → dropped
5. **Chatter deprioritisation** — single-word replies ("ok", "thanks") → flagged as `isChatter` but still `passed`
6. **Text cleaning** — strip known wrapper lines, divider characters, long runs of underscores/asterisks

### Batch forwarding

Messages with `filter_status='passed'` and `crm_sync_status='pending'` are forwarded to the CRM in batches of up to 50. Each message is `POST`ed individually to `POST /api/v1/market/messages`.

The `dedup_hash` is computed client-side:

```
dedup_hash = SHA-256(source_type | source_id).hex[:32]
```

This provides at-least-once idempotency — duplicate posts return the existing record.

**Retry:** Exponential backoff starting at 1 minute, capped at 30 minutes. After `CRM_SYNC_MAX_ATTEMPTS` (default 5), the row is marked `dead` and never retried.

---

## 3. Ingestion (backend)

### Endpoint contracts

**`POST /market/messages`** — single message ingest:

| Field | Type | Required | Notes |
|---|---|---|---|
| `source_type` | string | Yes | `whatsapp_group`, `whatsapp_channel`, `whatsapp_dm` |
| `source_id` | string | No | WhatsApp message ID |
| `sender_raw` | string | No | Phone number for contact resolution |
| `raw_text` | string | Yes | Original message body |
| `captured_at` | datetime | Yes | Original capture timestamp |
| `dedup_hash` | string | Yes | SHA-256 idempotency key (max 64 chars) |
| `group_name` | string | No | WhatsApp group name |
| `sender_name` | string | No | WhatsApp display name |
| `msg_type` | string | No | `text`, `image`, etc. |
| `precomputed` | object | No | Listener Pass B-D output (trusted when `MARKET_TRUST_LISTENER=true`) |

**`POST /market/messages/batch`** — batch of up to 50. Each item gets a per-item result (`created` / `duplicate` / `error`), so one bad payload never fails the whole batch.

### Idempotency

`get_by_dedup_hash(dedup_hash)` is called before any write. If a row with the same hash exists, the existing row is returned and no new row is created. Batch ingestion also checks for intra-batch duplicates (same hash appearing twice in one batch → second item marked `duplicate`).

### Contact resolution

`sender_raw` (phone number) is resolved server-side via `upsert_by_phone`. If a contact with the phone number already exists, it is reused; otherwise a new contact row is created. The resulting `contact_id` is stored on the `market_messages` row.

### Normalizer

Text normalisation is minimal and deterministic:
- Lowercase
- Collapse multiple whitespace characters to a single space
- No language detection — English-only extraction (Decision #5)

---

## 4. Extraction

The Python extractor (`backend/app/modules/market/extractor.py`) is an exact port of the JS listener's Pass B and Pass C pattern constants. It runs at ingestion time when `MARKET_TRUST_LISTENER` is `false` (the default post-P9).

### Side classification

Regex-based keyword detection, ported from the JS Pass B. Returns one of:

`BUY` | `SELL` | `MIXED` | `PRICE_DISCOVERY` | `PREBOOK` | `STATUS_CLOSE` | `UNKNOWN`

Fast-path WTB/WTS detection triggers first. When both buy and sell signals are present, the higher-count side wins. `PRICE_DISCOVERY`, `PREBOOK`, and `STATUS_CLOSE` are secondary signals that don't override a clear buy/sell signal.

### Brand detection

Three-target classification:
- **Apple** — iPhone, iPad, MacBook, AirPods, Apple Watch, etc.
- **Samsung** — Galaxy S/Z/A/Tab/Buds/Watch lines
- **Non-target** — Google Pixel, Xiaomi, OnePlus, Motorola, Nokia, DJI, PS5, etc.
- **Mixed** — both Apple and Samsung surface terms present
- **Samsung SSD carve-out** — `Samsung SSD`, `Samsung 990`, `Samsung T\d` patterns are non-target even though they mention "Samsung"

### Attribute extraction (14 families)

All 14 attribute families from the JS Pass C are ported:

| Family | Examples |
|---|---|
| Category | Smartphone, tablet, laptop, smartwatch, earbuds, accessory |
| Storage | 64GB, 128GB, 256GB, 512GB, 1TB, 2TB |
| RAM | 4GB, 8GB, 12GB, 16GB, 24GB; 4/64, 8/256 combined notation |
| Color | 40+ canonical colors with typo-tolerant alias matching |
| Region | UK, US, Japan, China, HK, India, EU, UAE, KSA, Australia |
| Activation | Non-active, active, locked, SIM-free, OEM |
| Condition | Brand new, open box, Grade A/B/C, used/refurbished |
| Quantity | Exact (N pcs), open-ended (N+), single, bulk, MOQ |
| Logistics | Local ready, FZCO, overseas dropship, delivery days, pickup |
| Currency | GBP (£), EUR (€), AED, masked (£***) |
| Variants | Enterprise, cellular/WiFi, bundle, watch size/band |
| Model numbers | EAN (13-digit), Apple MPN (XX123XX/A), Samsung internal |
| Contact CC | Country code extraction (+971, +44, etc.) |

### Resolution order

1. **Exact alias match** — case-insensitive substring match against `product_aliases.alias`
2. **LLM fallback** — when keyword resolution produces zero matches or side is UNKNOWN

Trigram fuzzy matching is a future enhancement (not implemented).

### Per-field confidence

- Keyword match: `0.95` (constant `KEYWORD_CONFIDENCE`)
- LLM match: varies, floored at `0.60` (`LLM_CONFIDENCE_FLOOR`)
- Each `MarketMessageProduct` row stores its per-field confidence map in `attributes._confidence`

### `extracted_attributes` JSONB

Every `market_messages` row has an `extracted_attributes` JSONB column storing the full Pass B+C output. When `MARKET_TRUST_LISTENER` is true, this comes from the listener's `precomputed` block. When false, the Python extractor populates it. Messages without this column populated can be backfilled via `backfill_extracted_attributes_task`.

---

## 5. LLM fallback

### `classify_message_task` Celery task

Dispatched at ingestion time when:
- Keyword+alias classification produces zero `MarketMessageProduct` rows, OR
- Side is `UNKNOWN`

Configuration:
- **Model:** Haiku 4.5 (`AI_MODEL_BULK` setting)
- **Max retries:** 3, with 30-second delay between retries
- **`acks_late=True`** — task survives worker restart mid-execution

### Execution flow

1. Task receives `message_id` as a string
2. Opens a sync SQLAlchemy session via `sync_session_factory()`
3. Calls `MarketClassificationService.classify_with_llm_sync(session, message_id)`
4. Uses `asyncio.run` bridge to call the Claude API (same pattern as other Celery tasks)
5. Sends the raw message text with a structured system prompt
6. Parses the JSON response for: `side`, `confidence`, `products[]`
7. For each product: creates `MarketMessageProduct` rows, learns new aliases (`source='llm_learned'`), applies three-band confidence routing

### System prompt

The prompt instructs Haiku to output a JSON object with side classification, confidence score, and per-product details (name, qty, price, currency, spec, condition, grade, color). Only products actually mentioned in the message are included.

---

## 6. Confidence bands & review queue

### Three-band routing

After resolution, each message is routed into one of three bands based on the **minimum** per-resolution confidence:

| Band | Threshold | Behaviour |
|---|---|---|
| **AUTO** | ≥ `market.confidence.auto_min` (default 0.85) | Applied immediately; `ContactProductTag` incremented; no human review needed |
| **PENDING** | Between `market.confidence.review_min` (default 0.55) and `auto_min` | Enters review queue for human correction |
| **UNRESOLVED** | < `market.confidence.review_min` | Stored as AUTO with `_unresolved: true` flag on each resolution; no `ContactProductTag` writes |

Thresholds are stored as `AppSetting` rows and are admin-tunable at runtime — no deploy needed.

### Urgency ordering

The review queue (`GET /market/review`) returns items in this order:
1. Non-expired items first
2. Within non-expired: `expires_at ASC` (soonest-to-expire on top)
3. Cursor is base64-encoded `expires_at|id`

### TTL auto-closure

The `expire_market_messages_task` Celery beat task runs every 5 minutes:
- ACTIVE messages past their TTL → `EXPIRED`
- PENDING messages past `expires_at` → `UNREVIEWED_EXPIRED`

### Corruption guard

Sub-threshold resolutions never mutate `ContactProductTag`. The `ContactProductTagRepository.increment_tag` method gates on `confidence >= auto_min` — if a sub-threshold `MarketMessageProduct` somehow reaches the tag increment path, it is silently skipped.

### Review endpoints

| Endpoint | Purpose |
|---|---|
| `GET /market/review` | Keyset-paginated queue of PENDING items |
| `POST /market/review/{id}/resolve` | Resolve with corrections (side, resolutions, teach entries) |
| `POST /market/review/{id}/dismiss` | Dismiss — no contact writes, audited |
| `GET /market/review/stats` | Queue depth, 7-day inflow/outflow, median review time, capacity estimate |

### Teach/correction loop

Human corrections in `POST /market/review/{id}/resolve` can include `teach` entries that write new aliases back to `product_aliases`. Currently stored with `source='llm_learned'` (renamed to `source='human'` when the enum constraint is corrected). These compound — each human correction improves future automated resolution.

---

## 7. Search

### Full-text search

A `search_tsv` GIN-indexed tsvector column is maintained on `market_messages`. It weights the `normalized_text` field and is queried via `websearch_to_tsquery('english', q)` for user-friendly syntax (supporting quoted phrases, `OR`, `-exclude`).

### Ranking

Results are ranked by: `ts_rank × recency_decay × max(resolution confidence)`. The recency decay factor prefers fresher messages.

### Keyset pagination

Pagination uses `(captured_at DESC, id DESC)` cursor. The cursor is base64-encoded JSON containing per-side positions (`b` for BUY, `s` for SELL). This is stable under concurrent inserts — new messages don't shift page boundaries.

### Split BUY/SELL panes

`GET /market/search` returns two independent result sets (`buy_items`, `sell_items`) with their own cursors, total counts, and pagination state. A `SearchEvent` is logged on every search for the training chain.

---

## 8. Virtual stock (TTL model)

Messages are treated as ephemeral listings with side-dependent TTL:

| Side | TTL | Rationale |
|---|---|---|
| **BUY** | 45 minutes | Buy intent is urgent and decays fast |
| **SELL** | 48 hours | Stock listings have longer shelf life |

### Supersede

A new post with the same `dedup_hash` supersedes the previous one — the old row's status is set to `SUPERSEDED`.

### Expiry sweep

`expire_market_messages_task` runs every 5 minutes via Celery beat. It marks ACTIVE messages past their TTL as `EXPIRED` and PENDING messages past `expires_at` as `UNREVIEWED_EXPIRED`.

---

## 9. Fingerprint dedup

### Structured fingerprint

A fingerprint captures the semantic identity of a lead independent of the raw message text:

```
fingerprint_hash = SHA-256(sender_phone | side | sorted(product_ids) | storage)
```

### Redis SET NX EX

The fingerprint hash is stored in Redis with a configurable TTL (`MARKET_FINGERPRINT_WINDOW_HOURS`, default 24). The `SET key value NX EX ttl` pattern ensures only the first sighting creates the key.

### Hit behaviour

When a fingerprint hits:
- The existing `market_messages` row is bumped: `seen_count += 1`
- The `source_groups[]` JSONB array is appended with `{source_id, group_name, at}`
- The earliest `captured_at` is preserved
- TTL is refreshed per side rules
- No new row is created

### Degradation

If Redis is unavailable, fingerprint dedup degrades gracefully — hash-only dedup (via `dedup_hash` unique constraint) still prevents exact duplicates. Fingerprint collapse across groups silently stops working but ingestion never blocks.

---

## 10. Contact intelligence

### `ContactProductTag`

Atomic per-contact-per-product counters, maintained via `ON CONFLICT DO UPDATE`:

```sql
INSERT INTO contact_product_tags (contact_id, product_id, side_buy_count, side_sell_count, …)
VALUES (…)
ON CONFLICT (contact_id, product_id) DO UPDATE
SET side_buy_count = contact_product_tags.side_buy_count + EXCLUDED.side_buy_count, …
```

Tag increment is gated on the AUTO confidence band — sub-threshold resolutions never reach this path (the corruption guard).

### Intelligence endpoints

| Endpoint | Purpose |
|---|---|
| `GET /market/contacts/{id}/intelligence` | Structured profile: products, attribute preferences (storage/RAM/color/region/condition), price range, activity timeline |
| `GET /market/contacts/ranked` | Ranked by activity volume, filterable by `side` and `product_id` |

### Profile rollups

Contact intelligence profiles are derived from source data (`market_messages` + `market_message_products` + `contact_product_tags`). A nightly Celery task can rebuild them from scratch if needed. The source tables are the system of record.

---

## 11. Training chain

### `SearchEvent` → `OutreachSend` → `Deal`

The training pipeline captures the full decision chain:

1. **SearchEvent** — logged on every `GET /market/search` (query text, resolved products, result counts, filters)
2. **OutreachSend** — created when an agent sends templated outreach to a contact (links to the originating `SearchEvent`)
3. **Deal** — auto-created in `contacted` state when outreach is sent; progresses through `MATCHED → CONTACTED → NEGOTIATING → WON/LOST`

### `GET /market/export/training`

Admin-only endpoint that exports full chains as structured JSON for future AI training. Each record links: search query → surfaced results → selected contacts → templates sent → deal outcomes.

### Deal stages

| Stage | Meaning |
|---|---|
| `matched` | Auto-created from outreach (default) or manual creation |
| `contacted` | Outreach was sent |
| `negotiating` | Active negotiation in progress |
| `won` | Deal closed successfully |
| `lost` | Deal lost or abandoned |

---

## 12. Settings reference

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `MARKET_TRUST_LISTENER` | `false` | When true, trust listener's `precomputed` block; when false, run Python extractor at ingestion |
| `MARKET_FINGERPRINT_WINDOW_HOURS` | `24` | Redis fingerprint TTL in hours; set to 0 to disable fingerprinting |
| `MARKET_BACKFILL_MAX_ROWS` | unlimited | Cap on `backfill_extracted_attributes_task` rows per run |
| `AI_MODEL_BULK` | — | Model used for LLM fallback classification (Haiku 4.5) |
| `ANTHROPIC_API_KEY` | — | Claude API key; LLM fallback is silently skipped if unset |

### AppSetting keys

| Key | Default | Admin-tunable | Effect |
|---|---|---|---|
| `market.confidence.auto_min` | `0.85` | Yes | Minimum confidence for AUTO band |
| `market.confidence.review_min` | `0.55` | Yes | Minimum confidence for PENDING band (below this → UNRESOLVED) |

`AppSetting` values are stored as `{"value": number}` JSONB. Changes take effect on the next ingestion — no deploy or restart needed.

---

## 13. Operational runbooks

### Queue overflow

If the review queue grows too large:
1. **Raise** `market.confidence.auto_min` temporarily — more messages route to AUTO, fewer enter PENDING (relief valve)
2. **Add reviewer capacity** — more agents working the queue
3. **Raise** `market.confidence.review_min` — sub-0.55 items route to UNRESOLVED instead of PENDING (more aggressive)

### Vocab editing

Add an alias in the `/market/vocab` UI → effective on the next ingest → no deploy required. Entries are `(category, kind, tag, canonical, aliases[])`. Both `closed` (fixed-set) and `open` (growable) kinds are supported.

### Listener re-pair

If the WhatsApp session is lost:
1. Delete the `AUTH_DATA_PATH` directory (default `./.wwebjs_auth`)
2. Restart the listener: `node src/index.js`
3. Scan the QR code with WhatsApp → Linked Devices → Link a Device

### Backfill re-run

```python
# In a Python shell or via Celery CLI:
from app.modules.market.tasks import backfill_extracted_attributes_task
backfill_extracted_attributes_task.delay()
```

Idempotent — skips rows that already have `extracted_attributes`. Resumable — can be run multiple times with `MARKET_BACKFILL_MAX_ROWS` to control batch size.

### Listener health check

```bash
curl http://localhost:3001/health
# → {"status":"healthy","uptime":123456,"groups":["...@g.us"],"ws":"connected"}
```

Restart if the health endpoint reports `ws: "disconnected"` — the WhatsApp WebSocket session has dropped and needs re-pairing.

---

## 14. Invariants

These constraints are the non-negotiable design rules for the market pipeline. Any proposed change must be checked against them.

1. **Precision over recall.** The AUTO band gate is strict (default 0.85). A false positive (wrong product tagged on a contact) is worse than a missed lead. AUTO-band mistakes corrupt `ContactProductTag` profiles; PENDING items get human review.

2. **Automation never silently corrupts.** The corruption guard ensures sub-threshold resolutions never write to `ContactProductTag`. If the guard fails, the side effect is a missing tag, not a wrong one.

3. **The alias/taxonomy table is the product.** Human corrections (`teach` entries in review resolution) compound over time. Every correction makes future automated resolution more accurate. The alias table is living data, not static configuration.

4. **Raw history inside backup perimeter.** `market_messages` is the system of record. Every raw message is preserved with its `raw_text`, `dedup_hash`, `extracted_attributes`, and resolution history. Nothing destructive happens to ingested data — updates change `status` and `review_status`, never delete rows.

5. **English-only extraction.** No language detection or multi-language support. The extractor patterns and LLM prompt are English-only. Non-English messages still flow through but won't match keywords or produce useful LLM output.

6. **Keyset pagination is stable under concurrent inserts.** The `(captured_at DESC, id DESC)` cursor does not shift when new messages arrive. A user paginating through results won't see duplicates or miss items.

7. **Dedup hash is the hard floor; fingerprint is the soft dedup.** The `dedup_hash` unique constraint on `market_messages` guarantees no exact duplicate ingestion. Fingerprint dedup is best-effort (Redis-dependent) and collapses semantically-equivalent posts across groups. If Redis is down, fingerprinting stops but hash dedup continues.

8. **Search is deterministic — no AI in query path.** `GET /market/search` uses PostgreSQL full-text search with GIN-indexed tsvectors. No LLM call is made during search. AI is only used at ingestion time (LLM fallback for classification).
