"""Media module — no Celery tasks live here.

Media download/upload runs inline within messaging.tasks (inbound prefetch
and outbound upload are both part of the message send/receive pipeline).
There is no async media processing to dispatch into a separate task.
"""
