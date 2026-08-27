"""Settings module — no Celery tasks live here.

Settings reads/writes are synchronous through the HTTP API (P1.2). There
is no current async settings pipeline. Autodiscover tolerates an empty
tasks module; the previous `settings.tasks.placeholder_task` no-op is
removed.
"""
