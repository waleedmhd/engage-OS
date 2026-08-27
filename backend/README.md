# EngageOS — Backend

FastAPI modular monolith with Celery workers, PostgreSQL, and Redis.

## Layout

```
app/
├── core/           Cross-cutting infrastructure (config, logging, security, ...)
├── api/            HTTP/WS API aggregator
├── db/             SQLAlchemy session & base
├── integrations/   External API clients (Meta, Anthropic Claude, notifications)
├── modules/        Business modules (one folder per domain)
├── workers/        Celery beat schedule + queue routing
├── schemas/        Cross-module shared schemas
├── services/       Cross-module shared services (rare)
├── utils/          Pure helpers
├── main.py         FastAPI factory
└── celery_app.py   Celery instance
```

Each module under `app/modules/` follows the same shape:

```
<name>/
├── router.py       FastAPI endpoints (no business logic)
├── service.py      Business logic
├── repository.py   DB access only
├── models.py       SQLAlchemy models
├── schemas.py      Pydantic request/response
├── tasks.py        Celery tasks
└── constants.py    Enums / state definitions
```

See [`../docs/coding-standards.md`](../docs/coding-standards.md) for the full rules.

## Local development

```bash
python -m venv .venv && source .venv/Scripts/activate
pip install -e ".[dev]"
cp .env.example .env

# Run API (from backend/)
bash scripts/start-api.sh

# Run worker (set WAIT_FOR_SCHEMA=0 if running the API in the same shell flow)
bash scripts/start-worker.sh

# Run scheduler
bash scripts/start-scheduler.sh
```

## Tests / lint

```bash
pytest
ruff check .
mypy app
```
