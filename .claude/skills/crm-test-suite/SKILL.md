---
name: crm-test-suite
description: Test infrastructure for the WA CRM backend. Use PROACTIVELY when writing, extending, or debugging tests, devising regression tests for bug fixes, or when the user mentions coverage, test failures, or the 85% gate. Encodes the 4-tier layout, committed_db rule, e2e worker bridge pattern, and JWT/auth conventions.
---

# WA CRM test suite

Write and run tests following the project's established test infrastructure. Authoritative details live in
`C:\Users\HP\.claude\projects\D--Documents-Claude-WA-CRM\memory\test_setup.md` — read it first; it may have newer specifics than this skill.

## Structure

- Four tiers under `backend/tests/`: `unit/`, `integration/`, `e2e/`, `live/`.
- Run via `backend/scripts/test.ps1 {unit|int|e2e|all|cov}`. Test stack = `backend/docker-compose.test.yml` (Postgres on 55432, Redis on 56379).
- **Coverage gate is 85%** — enforced in `pyproject.toml` (`fail_under = 85`), the `cov` tier, and `.github/workflows/test.yml`. New code must keep total coverage >= 85%. Respect the existing `[tool.coverage.run] omit` list; do NOT omit repositories used transitively.

## The committed_db rule (critical)

**Any test that invokes a Celery task, or hits an HTTP endpoint that itself opens a session, MUST seed via the `committed_db` fixture — not `pg_session`.** Celery tasks use their own `sync_session_factory()` connection and request handlers use the async engine; uncommitted SAVEPOINT data in `pg_session` is invisible to them. `pg_session` / `async_pg_session` (SAVEPOINT-rollback) are correct only for pure service/repo tests sharing the one session.

## Patterns

- e2e web->worker: patch `request_ai_reply_task.delay` to capture, then run the task via `await asyncio.to_thread(task.run, ...)` — the worker bridge uses `asyncio.run()` which cannot run inside the test event loop. respx routes are process-global so mocks still intercept in the thread.
- API tests authenticate with a real JWT: `create_access_token(str(user.id), user.role)` (overriding `get_current_user_db` alone is insufficient). EmailStr rejects `.local` — use `@example.com`.
- Webhook endpoint is mounted at `/webhooks/meta` (root), NOT `/api/v1/webhooks/meta`.
- Factories at `tests/factories.py` (`make_template/make_campaign/make_campaign_recipient/make_ai_event`, etc.); `freezegun` available for time-dependent tests.
- Alembic `revision` ids must be <= 32 chars.

## Regression tests for bug fixes

When tests accompany bug fixes, cross-check `bugs.txt`: for each fixed entry, add a test that fails against the pre-fix behavior and passes after, and reference the bug ID in the test name/docstring (matches the existing B-/C-/I- guard convention).

## Finish

Run the relevant tier (or `cov` for the gate) via `backend/scripts/test.ps1` and confirm green + coverage >= 85% before claiming completion. Report the actual command output, not an assumption.
