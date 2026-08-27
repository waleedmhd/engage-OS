# Phase 4.5 — Foundation Stabilization
## Fix Tracking Document

**Date:** 2026-05-08
**Status:** Complete — 15 files replaced

---

## Fix Map

| Bug ID | Severity | File | Resolution |
|--------|----------|------|------------|
| DB-C1 | Critical | `alembic/versions/0001_initial_schema.py` | `refresh_tokens` table + 3 indexes added |
| DB-C2 | Critical | `alembic/versions/0001_initial_schema.py` | `ck_conversations_lock_invariant` CHECK added |
| DB-C3 | Critical | `app/db/repository.py` | UPDATE via ORM attribute assignment + refresh(); identity map no longer bypassed |
| DB-C4 | Critical | `app/modules/messaging/repository.py` | Removed `if last_error is not None` guard; NULL can now be written to clear errors |
| Auth-C1 | Critical | `app/modules/auth/router.py` | `session.commit()` called after service returns in login, refresh, logout |
| Conv-C1 | Critical | `app/modules/conversations/service.py` | `approve()` and `reject()` assert `current == AWAITING_APPROVAL` |
| Conv-C2 | Critical | `app/modules/conversations/service.py` | `assert_transition()` runs before `acquire_lock()` in `assign()` |
| Conv-C3 | Critical | `app/modules/conversations/service.py` | `force_transition()` releases lock when leaving `HUMAN_ASSIGNED` |
| Conv-C4 | Critical | `app/modules/conversations/service.py` | `_transition()` is a single flush unit; caller's session commit makes both state+audit atomic |
| Conv-C5 | Critical | `app/core/events.py` | `event=` kwarg renamed to `event_name=`; structlog collision eliminated |
| Msg-C3 | Critical | `app/modules/messaging/router.py` | Fail-closed when `META_APP_SECRET` empty + `ENV != development` |
| Msg-C4 | Critical | `app/modules/messaging/router.py` + `service.py` | Task dispatched after `session.commit()` in router; removed from service |
| Msg-C1 | Critical | `app/modules/messaging/tasks.py` | Dedup key set only after successful persistence |
| Msg-C2 | Critical | `app/modules/messaging/tasks.py` | Dedup key set only after successful status update |
| Auth-I1 | Important | `app/core/security.py` | Reserved claims written last; `ValueError` raised on collision |
| Auth-I2 | Important | `app/core/config.py` | `field_validator` rejects default/weak `JWT_SECRET` in staging/production |
| Auth-I3 | Important | `app/modules/auth/service.py` | `.replace(tzinfo=utc)` → `.astimezone(utc)` |
| Conv-S1 | Important | `app/modules/conversations/router.py` | `force_transition` gated on `require_role("admin")` |
| Conv-S3 | Important | `app/modules/conversations/router.py` | Role gates on all override endpoints |
| Conv-I2 | Important | `app/modules/conversations/service.py` | `update_state` uses `WHERE state = :expected`; raises on 0 rows |
| Conv-I5 | Important | `app/modules/conversations/service.py` | `FIRST_ACTIVATED` event emitted after NEW→AI_ACTIVE |
| DB-I2 | Important | `alembic/versions/0001_initial_schema.py` | Indexes declared migration-level only; no model-level `index=True` duplication |
| DB-I3 | Important | `alembic/versions/0001_initial_schema.py` | `ix_campaigns_created_by` added |
| DB-I4 | Important | `alembic/versions/0001_initial_schema.py` | `ix_audit_logs_action` standalone index added |
| DB-I5 | Important | `alembic/versions/0001_initial_schema.py` | `UniqueConstraint` used for `app_settings.key` |
| DB-I7 | Important | `app/modules/contacts/repository.py` | `upsert_by_phone` race recovery wrapped in `begin_nested()` SAVEPOINT |
| DB-I8 | Important | `app/modules/messaging/repository.py` | Atomic `UPDATE SET retry_count = retry_count + 1` |
| Msg-I7 | Important | `app/modules/messaging/tasks.py` | `ai_enabled` checked before NEW→AI_ACTIVE transition |
| Msg-M11 | Minor | `app/core/config.py` | `META_VERIFY_TOKEN` defaults to empty; validator rejects empty in prod |
| DB-M4 | Minor | `app/db/uow.py` | Explicit rollback if `commit()` raises |
| DB-M5 | Minor | `app/db/uow.py` | `session.begin()` called in `__aenter__` |
| DB-M6 | Minor | `app/db/repository.py` | Relationship names rejected in `order_by` |
| DB-M7 | Minor | `app/db/repository.py` | `count()` uses subquery pattern |
| DB-M10 | Minor | `alembic/versions/0001_initial_schema.py` | Tag seed uses `ON CONFLICT DO NOTHING` |
| DB-M15 | Minor | `app/db/repository.py` | `update()` returns `None` only for missing row; no-op returns instance |
| DB-M17 | Minor | `app/modules/contacts/repository.py` | `when` param typed as `datetime` |
| Conv-M1 | Minor | `app/modules/conversations/router.py` | `get_conversation` routes through service layer |
| Msg-M5 | Minor | `app/modules/messaging/router.py` | Bad signature returns 200+log, not 401 |
| Msg-I2 | Minor | `app/modules/messaging/service.py` | `list_messages` returns real total from `count()` query |
| Msg-M13 | Minor | `app/modules/messaging/service.py` | `actor_id` coerced to UUID before logging |

---

## Critical Test Gaps — Must Write Before Phase 5

These are the test gaps identified in the bug file that directly correspond
to fixes made in this phase. Write these tests before proceeding.

### conversations/
- `test_approve_rejects_non_awaiting_approval_source` (covers Conv-C1)
- `test_reject_rejects_non_awaiting_approval_source` (covers Conv-C1)
- `test_assign_illegal_transition_does_not_acquire_lock` (covers Conv-C2)
- `test_force_transition_from_human_assigned_releases_lock` (covers Conv-C3)
- `test_concurrent_transition_raises_concurrent_modification` (covers Conv-I2)
- `test_force_transition_requires_admin_role` (covers Conv-S1)

### messaging/
- `test_inbound_dedup_key_not_set_on_persist_failure` (covers Msg-C1)
- `test_status_update_dedup_key_not_set_on_failure` (covers Msg-C2)
- `test_signed_webhook_accepted` (covers Msg-C3)
- `test_unsigned_webhook_rejected_in_production` (covers Msg-C3)
- `test_outbound_task_dispatched_after_commit` (covers Msg-C4)
- `test_webhook_round_trip` (covers Msg-C1/C3/C4 together)

### auth/
- `test_refresh_token_persisted_after_login` (covers Auth-C1)
- `test_refresh_token_rotation_is_durable` (covers Auth-C1)
- `test_refresh_token_expiry_uses_astimezone` (covers Auth-I3)

### db/
- `test_base_repository_update_no_identity_map_staleness` (covers DB-C3)
- `test_upsert_by_phone_concurrent_race` (covers DB-I7)
- `test_increment_retry_is_atomic` (covers DB-I8)

---

## Files NOT Changed in This Phase

The following referenced files require no changes for the bugs addressed here.
They retain their existing implementations:

- `app/modules/conversations/state_machine.py` (transition table; M3 case-sensitivity is a separate concern)
- `app/modules/conversations/repository.py` (update_state signature assumed correct; optimistic concurrency is enforced in service layer)
- `app/modules/audit/repository.py` (append method; structure unchanged)
- `app/core/dependencies.py` (M1/M2 type annotation improvements deferred to Phase 5 cleanup)
- `app/core/logging.py` (M5 wrong wrapper class deferred)
- `app/core/redis.py` (I8 lru_cache/loop issue deferred — separate Celery infrastructure concern)

---

## Deployment Notes

1. This phase includes a new migration (`0001_initial_schema.py`).
   If the database was previously migrated with the old version, you must
   run a new migration to add the `refresh_tokens` table and the
   `ck_conversations_lock_invariant` CHECK constraint.

2. Set `META_APP_SECRET` in all Railway environment variables before
   deploying to staging or production. The application will refuse to
   start without it.

3. Set a strong `JWT_SECRET` (≥32 chars, not the default string) in
   staging and production Railway service variables.

4. `META_VERIFY_TOKEN` must be set in staging/production or the webhook
   GET handshake will be rejected.
