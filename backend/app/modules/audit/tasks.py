"""Audit module — no Celery tasks live here.

Audit rows are written transactionally co-located with the domain change
via direct `AuditRepository.append(...)` calls inside each domain service.
There is currently no event-bus subscriber that writes audit rows out-of-
band, so the previously-registered `audit.tasks.record_audit_event_task`
NotImplementedError stub is removed entirely. If a bus-subscriber path is
ever added (DSD §9), reintroduce a real task here.
"""
