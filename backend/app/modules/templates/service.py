"""Template service — submit to Meta and sync approval status.

Mirrors the ContactService pattern: takes a session, builds its own
repository, flushes only. The router commits the unit of work.

External Meta calls go through the integrations client (never another
service) — same boundary rule as messaging.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.integrations.meta.client import MetaWhatsAppClient
from app.modules.templates.constants import TemplateStatus, map_meta_status
from app.modules.templates.models import Template
from app.modules.templates.repository import TemplateRepository

logger = get_logger(__name__)


class TemplateService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        meta_client: MetaWhatsAppClient | None = None,
    ) -> None:
        self._session = session
        self._repo = TemplateRepository(session)
        self._settings = get_settings()
        self._meta = meta_client or MetaWhatsAppClient(self._settings)

    # ----------------------------------------------------------------- reads

    async def list_templates(
        self, *, page: int, page_size: int, status: str | None = None
    ) -> tuple[list[Template], int]:
        items, total = await self._repo.list_with_total(
            page=page, page_size=page_size, status=status
        )
        return list(items), total

    async def get_template(self, template_id: uuid.UUID) -> Template:
        return await self._repo.get_or_404(template_id)

    # ---------------------------------------------------------------- writes

    @property
    def _meta_configured(self) -> bool:
        return bool(self._settings.META_WABA_ID and self._settings.META_ACCESS_TOKEN)

    @staticmethod
    def _extract_body(components: list[dict] | None) -> str | None:
        """Extract the BODY component text from a Meta template components list."""
        if not components:
            return None
        for comp in components:
            if isinstance(comp, dict) and comp.get("type", "").upper() == "BODY":
                text = comp.get("text")
                return str(text) if text else None
        return None

    async def submit_template(
        self, *, name: str, category: str, language: str, body: str
    ) -> Template:
        """Create the local template row, then submit it to Meta.

        If Meta credentials are not configured (dev/test), the row is
        persisted as PENDING with no remote id and the remote call is
        skipped — the campaign approval gate then correctly blocks any
        campaign on this template until it is genuinely approved.
        """
        existing = await self._repo.get_by_name(name)
        if existing is not None:
            raise ConflictError(
                f"Template named {name!r} already exists.",
                details={"template_id": str(existing.id)},
            )

        template = await self._repo.create(
            name=name,
            category=category,
            language=language,
            status=TemplateStatus.PENDING.value,
            body=body,
        )

        if self._meta_configured:
            response = self._meta.submit_message_template(
                name=name, language=language, category=category, body=body
            )
            meta_id = response.get("id")
            mapped = map_meta_status(response.get("status"))
            await self._repo.update_status(
                template.id,
                mapped.value,
                meta_template_id=str(meta_id) if meta_id else None,
            )
        else:
            logger.warning(
                "template_submit_meta_not_configured",
                template_id=str(template.id),
                name=name,
            )

        await self._session.flush()
        return template

    async def sync_status_from_meta(self, template_id: uuid.UUID) -> Template:
        """Refresh a single template's status (and body) from Meta on demand."""
        template = await self._repo.get_or_404(template_id)
        if not template.meta_template_id:
            raise NotFoundError(
                f"Template {template_id} has no meta_template_id to sync"
            )

        response = self._meta.get_message_template(
            meta_template_id=template.meta_template_id
        )
        mapped = map_meta_status(response.get("status"))
        body = self._extract_body(response.get("components"))
        updated = await self._repo.update_status(
            template.id, mapped.value, body=body
        )
        await self._session.flush()
        return updated or template

    async def import_from_meta(self) -> dict[str, int]:
        """Fetch all templates from the WABA and upsert them locally.

        Returns a summary dict with ``imported`` (new rows) and
        ``updated`` (existing rows refreshed) counts.
        """
        raw_templates = self._meta.get_message_templates()
        imported = 0
        updated = 0
        for raw in raw_templates:
            meta_id = raw.get("id")
            name = raw.get("name")
            if not meta_id or not name:
                continue
            status = map_meta_status(raw.get("status")).value
            category_raw = (raw.get("category") or "utility").lower()
            language = raw.get("language") or "en"
            body = self._extract_body(raw.get("components"))

            existing = await self._repo.get_by_name(name)
            await self._repo.upsert_from_meta(
                name=name,
                meta_template_id=str(meta_id),
                status=status,
                category=category_raw,
                language=language,
                body=body,
            )
            if existing is None:
                imported += 1
            else:
                updated += 1

        await self._session.flush()
        logger.info(
            "templates_imported_from_meta", imported=imported, updated=updated
        )
        return {"imported": imported, "updated": updated}
