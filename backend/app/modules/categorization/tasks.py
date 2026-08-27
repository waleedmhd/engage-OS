"""Categorization module — no Celery tasks live here.

Tag-suggestion creation runs inline (sync) via
`CategorizationService.create_suggestion_sync` from `AIOrchestrator._decide`,
co-located in the same Celery task that processes the AI response.
The previously-registered `categorization.tasks.process_tag_suggestion_task`
NotImplementedError stub is removed; there is no async tag-suggestion
pipeline to dispatch into.
"""
