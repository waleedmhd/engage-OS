"""Conversations module — no Celery tasks live here.

Lock-expiry sweeping is owned by `app.modules.assignments.tasks.
expire_stale_locks_task` (Phase 5.5). This file is intentionally empty
so that Celery's autodiscover_tasks() finds nothing to register for the
`conversations` module; the previously-registered
`conversations.tasks.expire_conversation_locks_task` was a
NotImplementedError stub whose name collided with the real assignments
task and is therefore removed entirely.
"""
