# Architecture

## Module layout

The backend is organised as a modular monolith under `backend/app/modules/`. Each module follows the 7-file layout convention:

```
module/
  __init__.py      # Public API re-exports
  models.py        # SQLAlchemy ORM models
  schemas.py       # Pydantic request/response schemas
  service.py       # Business logic
  repository.py    # Data access
  router.py        # FastAPI route definitions
  tasks.py         # Celery tasks (if any)
```

### Module inventory

| Module | Domain |
|---|---|
| `ai` | AI conversation orchestration, Haiku/Sonnet routing |
| `analytics` | Daily rollup tables, last-touch 30d ROI attribution |
| `assignments` | Contact assignment locking, round-robin, lock-expiry reaper |
| `audit` | Audit log write-path and admin viewer |
| `auth` | JWT authentication, role-based permissions |
| `campaigns` | Broadcast campaign scheduling, throttle, compliance gates |
| `categorization` | Tag taxonomy, AI suggestion intake, approve/reject |
| `contacts` | Contact CRUD, bulk actions, CSV import |
| `conversations` | Conversation state machine, inbox, WebSocket |
| `engagement` | Outbound message delivery tracking |
| `erp_reporting` | Financial report generation |
| `fulfilment` | Order fulfilment workflows |
| `inventory` | Items, stock management |
| `ledger` | Double-entry accounts, journals |
| `market` | Market intelligence pipeline (ingestion, extraction, search, review, outreach, deals) |
| `media` | Media upload and serving |
| `messaging` | WhatsApp webhook, manual send, message store |
| `payables` | Accounts payable |
| `procurement` | Procurement workflows |
| `receivables` | Accounts receivable |
| `settings` | Typed settings registry (admin-tunable at runtime) |
| `templates` | WhatsApp template management (Meta API submit/sync) |
| `users` | User management |

## Service map

```
Frontend (Next.js 14, App Router, TypeScript, Tailwind)
    │
    │  REST + WebSocket (/ws/inbox)
    ▼
FastAPI (backend/app/)
    │
    ├─ Async HTTP: ai, audit, auth, contacts, conversations,
    │              market (search/review/outreach), messaging, settings,
    │              templates, users
    │
    ├─ WebSocket: /ws/inbox (Redis pub/sub fan-out)
    │
    └─ Celery Workers (5 queues: default, outbound, ai, analytics, categorization)
         │
         ├─ classify_message_task (market LLM fallback, Haiku 4.5)
         ├─ expire_market_messages_task (TTL sweep, every 5 min)
         └─ Celery Beat (analytics daily rollup 00:15 UTC, market expiry sweep)

Listener (Node.js, whatsapp-web.js)
    │
    │  HTTP POST /api/v1/market/messages
    ▼
FastAPI → market ingestion pipeline
```

## Dependency direction

- Services depend on repositories, not on other services
- Repositories depend on models and `AsyncSession`
- Routers depend on services, schemas, and FastAPI dependencies
- Tasks depend on services (sync path) and `sync_session_factory`

The async (HTTP) and sync (Celery) paths share core business logic through service classes that accept either an `AsyncSession` or a `SyncSession`. The `asyncio.run` bridge pattern is used for Celery tasks that need to call async APIs (e.g. Claude API).

## Domain events

Events are emitted via Redis pub/sub and consumed by the WebSocket fan-out layer:

- `conversation.created` — new conversation from incoming message
- `conversation.state_changed` — state transition in the conversation FSM
- `message.received` — inbound message persisted
- `message.sent` — outbound message delivered

## Authoritative documents

| Document | What it covers |
|---|---|
| [`docs/market-and-listener.md`](market-and-listener.md) | Market intelligence pipeline end-to-end (capture, extraction, confidence routing, search, review queue, fingerprint dedup, contact intelligence, training chain) |
| [`docs/conversation-state-machine.md`](conversation-state-machine.md) | State transitions, actor model, audit pattern |
| [`docs/coding-standards.md`](coding-standards.md) | Module conventions, 7-file layout, async/sync split |
| [`docs/runbook.md`](runbook.md) | Local dev, tests, migrations, troubleshooting |
| [`docs/railway-deployment.md`](railway-deployment.md) | Full Railway setup, per-service env matrix, healthchecks |
