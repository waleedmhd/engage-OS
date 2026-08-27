# EngageOS — WhatsApp AI CRM

Internal WhatsApp-centric platform with CRM, AI-assisted conversations (Claude API: Haiku 4.5 bulk / Sonnet 4.6 escalation), market intelligence pipeline (WhatsApp group listener → extraction → matching dashboard → review queue → deals/outreach), broadcast campaigns, ERP modules (ledger, AR/AP, inventory, procurement, fulfilment), and analytics.

**Stack:** FastAPI + Python 3.12 · Celery · Redis · PostgreSQL · Next.js 14 · Railway · Meta WhatsApp Cloud API · Claude API (Haiku 4.5 / Sonnet 4.6) · whatsapp-web.js (listener)

**Architecture:** Modular monolith (see [`docs/architecture.md`](docs/architecture.md)).

---

## Repository layout

```
backend/    FastAPI app + Celery workers + Alembic migrations
frontend/   Next.js dashboard (App Router, TypeScript, Tailwind)
listener/   Node.js WhatsApp group listener (capture + noise gate → CRM ingest)
infra/      Railway service configs · Docker · startup scripts
docs/       Architecture · coding standards · runbook · market pipeline deep-dive
```

---

## Quick start (local dev)

```bash
# 1. Copy env templates
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local

# 2. Boot infrastructure
docker compose -f infra/docker/docker-compose.yml up -d postgres redis

# 3. Backend
cd backend
python -m venv .venv && source .venv/Scripts/activate
pip install -e ".[dev]"
bash scripts/start-api.sh

# 4. Worker / scheduler (separate terminals, from backend/)
bash scripts/start-worker.sh
bash scripts/start-scheduler.sh

# 5. Frontend (separate terminal)
cd frontend
npm install
npm run dev

# 6. Listener (separate terminal)
cd listener
npm install
cp .env.example .env
# Edit .env with DATABASE_URL, CRM_API_URL, CRM_USER_EMAIL, CRM_USER_PASSWORD, MONITORED_GROUPS
node src/index.js
# Scan QR, done — see listener/README.md for full setup
```

API: http://localhost:8000 · Docs: http://localhost:8000/docs · Dashboard: http://localhost:3000 · Listener health: http://localhost:3001/health

---

## Feature overview

### CRM Core
- Multi-channel inbox (WhatsApp webhook + manual send)
- AI-assisted conversations with supervised qualification and human takeover
- Contact management (CRUD, bulk actions, import)
- Conversation state machine (NEW → AI_ACTIVE → AWAITING_APPROVAL → HUMAN_ASSIGNED → CLOSED)
- Assignment locking with round-robin and lock-expiry reaper
- Live inbox WebSocket (Redis pub/sub fan-out)

### Campaigns & Templates
- Broadcast campaigns with cron scheduling, per-campaign throttle, compliance gates
- WhatsApp template management (Meta API submit/sync, admin-only)
- Campaign failure reporting and delivery-failure retry

### Market Intelligence
- WhatsApp group listener (real-time capture, 24/7, persistent WebSocket)
- Deterministic extraction pipeline (side detection, attribute parse, brand/product resolution)
- LLM fallback for low-confidence messages (Haiku 4.5)
- Three-band confidence routing (AUTO / PENDING review queue / UNRESOLVED)
- Human review queue with teach/correction loop
- Matching dashboard (split BUY/SELL panes, full-text search, freshness scoring)
- Fingerprint dedup across groups (seen_count + source_groups)
- Contact intelligence profiles (product interests, attribute preferences, price ranges)
- Outreach → Deal training chain (SearchEvent → OutreachSend → Deal)
- Attribute vocabulary as editable data (no-deploy taxonomy updates)

### Finance & Inventory
- Double-entry ledger (accounts, journals, receivables, payables)
- Inventory management (items, stock, procurement, fulfilment)

### Admin
- Analytics dashboard with daily rollup tables and last-touch 30d ROI attribution
- Audit log viewer (admin-only)
- Settings registry (typed, admin-tunable at runtime)
- User management, role-based permissions
- Tag taxonomy management

---

## Railway topology

Seven services: `api`, `worker`, `scheduler`, `frontend`, `postgres`, `redis`, **`listener`**.

The listener service runs Node 22+, requires `DATABASE_URL`, `CRM_API_URL`, `CRM_EMAIL`, `CRM_PASSWORD`, and `MONITORED_GROUPS` env vars, exposes a health endpoint on `:3001`, and uses QR pairing for WhatsApp auth.

See [`docs/railway-deployment.md`](docs/railway-deployment.md) for the full per-service env matrix and healthcheck configuration.

---

## Documentation index

| Document | What it covers |
|---|---|
| `docs/architecture.md` | Module layout, service map, dependency direction, domain events |
| `docs/market-and-listener.md` | Market pipeline deep-dive (authoritative reference) |
| `docs/railway-deployment.md` | Full Railway setup, per-service env matrix, healthchecks |
| `docs/runbook.md` | Local dev, tests, migrations, troubleshooting |
| `docs/coding-standards.md` | Module conventions, 7-file layout, async/sync split |
| `docs/conversation-state-machine.md` | State transitions, actor model, audit pattern |
| `listener/README.md` | Listener setup, env vars, QR pairing, PM2 |
