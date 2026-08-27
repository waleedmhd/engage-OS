# EngageOS Backend Test Suite

Four tiers, layered by infrastructure cost and fidelity.

| Tier | What runs | Infra | Speed | When |
|---|---|---|---|---|
| `unit` | Pure logic, AST guards, property tests, mocked HTTP | None | <10s | every save |
| `integration` | DB + Redis + Celery routing, webhook signatures | Postgres + Redis (compose) | ~30s | every PR |
| `e2e` | Full user-journey workflows (webhook → AI → send) | Compose + Celery eager | ~1–2min | every PR |
| `live` | Real Meta WhatsApp + Anthropic API calls | External services | ~10s | manual / nightly |

## Quick start (Windows / PowerShell)

```powershell
# unit only — no Docker required
backend\scripts\test.ps1 unit

# bring up Postgres + Redis (port 55432 / 56379) and run integration
backend\scripts\test.ps1 int

# full mocked suite (unit + integration + e2e)
backend\scripts\test.ps1 all

# coverage report → backend/htmlcov/
backend\scripts\test.ps1 cov

# tear down compose
backend\scripts\test.ps1 down
```

## Live tier

Live tests **send real WhatsApp messages** and call the Anthropic API with billable
requests. They are **excluded by default** via `addopts = -m 'not live'`
in `pyproject.toml`.

To run:

```powershell
$env:RUN_LIVE_TESTS = "1"
$env:META_TEST_RECIPIENT = "+1XXXXXXXXXX"   # verified test number
backend\scripts\test.ps1 live
```

The `tests/live/conftest.py` autouse fixture refuses to run unless
`RUN_LIVE_TESTS=1` AND real (non-`test-`-prefixed) credentials are present in
`.env`.

## Markers

```
integration  — requires Postgres + Redis from docker-compose.test.yml
e2e          — full-stack workflow; requires compose + Celery eager
live         — hits real Meta / Anthropic APIs; costs money
slow         — >2s test
```

Auto-marked by directory: `tests/integration/*` → `integration`,
`tests/e2e/*` → `e2e`, `tests/live/*` → `live`.

## Fixtures (`tests/conftest.py`)

| Fixture | Scope | Purpose |
|---|---|---|
| `app` | session | FastAPI app instance |
| `client` | function | `httpx.AsyncClient` against ASGI transport |
| `pg_engine` | session | sync engine; runs `alembic upgrade head` once |
| `pg_session` | function | sync session, SAVEPOINT-rollback isolation |
| `async_pg_session` | function | async session, same isolation pattern |
| `redis_client` | function | real Redis, `FLUSHDB` per test |
| `fake_redis` | function | `fakeredis.FakeRedis` for unit tests |
| `celery_eager` | function | flips `task_always_eager=True` |
| `respx_mock` | function | `respx` router for httpx interception |
| `override_db_dep` | function | replace `get_db_session` in the app |

## Adding a webhook fixture

Drop a JSON file into `tests/fixtures/payloads/` and load it via the helper:

```python
from tests.fixtures.payloads import load_payload_bytes, sign_meta

body = load_payload_bytes("meta_inbound_text")
sig = sign_meta(body, os.environ["META_APP_SECRET"])
```

## Architectural invariant guards

`tests/unit/test_msg_c4_commit_order.py` is an AST guard that walks every
`app/modules/*/service.py` and `router.py`. If a future PR commits inside a
service or dispatches a task before committing in a router, this test fails
loudly with a file:line citation. Treat its failures as required fixes — they
indicate a regression of the Msg-C4 / Auth-C1 invariants documented in
`memory/architectural_invariants.md`.

## Coverage target

CI gates merge on `--cov-fail-under=80`. To inspect uncovered lines locally:

```powershell
backend\scripts\test.ps1 cov
start backend\htmlcov\index.html
```
