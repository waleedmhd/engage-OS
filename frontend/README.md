# EngageOS — Frontend

WhatsApp CRM dashboard, powered by EngageOS.

Next.js 14 (App Router) admin dashboard. Mirrors backend domain modules.

## Layout

```
app/
├── (dashboard)/        Routes inside the sidebar shell
│   ├── inbox/
│   ├── contacts/
│   ├── campaigns/
│   ├── templates/
│   ├── tag-review/
│   ├── analytics/
│   ├── settings/
│   └── audit-logs/
├── api/health          Frontend health probe
└── layout.tsx          Root layout
components/
├── shared/             Sidebar / Topbar / PageHeader
├── inbox/
├── crm/
└── analytics/
hooks/                  React hooks (useLiveEvents, ...)
lib/                    Plain modules (api, ws, env)
types/                  Shared TS interfaces
```

## Dev

```bash
npm install
cp .env.example .env.local
npm run dev
```

The dashboard is available at http://localhost:3000 (redirects to `/inbox`).
