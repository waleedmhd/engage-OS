"""Campaign lifecycle service (DSD §4.7).

State transitions are validated against ALLOWED_TRANSITIONS. Compliance
checks gate DRAFT → SCHEDULED. Recipient materialisation snapshots the
audience filter into campaign_recipients so recurring runs are reproducible.

Following the messaging Msg-C4 pattern: this service flushes the session
but never commits, and never calls task.delay(). Routers commit and
dispatch tasks after this returns.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    StateTransitionError,
)
from app.modules.audit.constants import ActorType, AuditAction
from app.modules.audit.repository import AuditRepository
from app.modules.campaigns.constants import (
    ALLOWED_TRANSITIONS,
    CampaignRecipientStatus,
    CampaignStatus,
    CampaignType,
    ComplianceCode,
)
from app.modules.campaigns.models import Campaign, CampaignCategory
from app.modules.campaigns.repository import (
    CampaignCategoryRepository,
    CampaignRecipientRepository,
    CampaignRepository,
)
from app.modules.campaigns.schemas import (
    CampaignCategoryCreateRequest,
    CampaignCategoryListResponse,
    CampaignCategoryResponse,
    CampaignCategoryUpdateRequest,
    CampaignCategoryWithUsageResponse,
    CampaignCreateRequest,
    CampaignErrorBreakdownItem,
    CampaignReportResponse,
    CampaignUpdateRequest,
    CampaignValidationResponse,
    ComplianceError,
)
from app.modules.templates.constants import TemplateStatus
from app.modules.templates.models import Template

logger = structlog.get_logger(__name__)


class CampaignService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CampaignRepository(session)
        self._recipient_repo = CampaignRecipientRepository(session)
        self._audit = AuditRepository(session)

    # --------------------------------------------------------------- helpers

    def _assert_transition(
        self, current: str | CampaignStatus, target: CampaignStatus
    ) -> None:
        try:
            current_enum = CampaignStatus(current)
        except ValueError as exc:
            raise StateTransitionError(
                f"unknown campaign status: {current!r}"
            ) from exc
        allowed = ALLOWED_TRANSITIONS.get(current_enum, set())
        if target not in allowed:
            raise StateTransitionError(
                f"cannot transition campaign from {current_enum.value} → {target.value}"
            )

    async def _get_or_404(self, campaign_id: uuid.UUID) -> Campaign:
        campaign = await self._repo.get(campaign_id)
        if campaign is None:
            raise NotFoundError(f"Campaign {campaign_id} not found")
        return campaign

    async def _audit_event(
        self,
        *,
        action: str,
        campaign: Campaign,
        actor_id: uuid.UUID | None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        await self._audit.append(
            actor_type=ActorType.USER.value if actor_id else ActorType.SYSTEM.value,
            actor_id=actor_id,
            action=action,
            entity_type="campaign",
            entity_id=campaign.id,
            before_state=before,
            after_state=after,
        )

    # ----------------------------------------------------------------- create

    async def create_campaign(
        self,
        payload: CampaignCreateRequest,
        *,
        actor_id: uuid.UUID | None,
    ) -> Campaign:
        if payload.category_id is not None:
            if await self._session.get(CampaignCategory, payload.category_id) is None:
                raise NotFoundError(f"CampaignCategory:{payload.category_id}")
        campaign = await self._repo.create(
            template_id=payload.template_id,
            name=payload.name,
            type=payload.type,
            status=CampaignStatus.DRAFT.value,
            scheduled_at=payload.scheduled_at,
            cron_expression=payload.cron_expression,
            audience_filter=payload.audience_filter.model_dump(mode="json"),
            rate_limit_per_second=payload.rate_limit_per_second,
            created_by=actor_id,
            category_id=payload.category_id,
        )
        await self._audit_event(
            action="campaign.created",
            campaign=campaign,
            actor_id=actor_id,
            after={"status": campaign.status, "type": campaign.type},
        )
        await self._session.flush()
        return campaign

    async def update_campaign(
        self,
        campaign_id: uuid.UUID,
        payload: CampaignUpdateRequest,
        *,
        actor_id: uuid.UUID | None,
    ) -> Campaign:
        campaign = await self._get_or_404(campaign_id)
        if campaign.status != CampaignStatus.DRAFT.value:
            raise StateTransitionError(
                f"campaign {campaign_id} cannot be edited in status={campaign.status}"
            )
        fields: dict[str, Any] = {}
        if payload.name is not None:
            fields["name"] = payload.name
        if payload.scheduled_at is not None:
            fields["scheduled_at"] = payload.scheduled_at
        if payload.cron_expression is not None:
            fields["cron_expression"] = payload.cron_expression
        if payload.audience_filter is not None:
            fields["audience_filter"] = payload.audience_filter.model_dump(mode="json")
        if payload.rate_limit_per_second is not None:
            fields["rate_limit_per_second"] = payload.rate_limit_per_second
        if payload.category_id is not None:
            if await self._session.get(CampaignCategory, payload.category_id) is None:
                raise NotFoundError(f"CampaignCategory:{payload.category_id}")
            fields["category_id"] = payload.category_id
        if not fields:
            return campaign
        updated = await self._repo.update(campaign_id, **fields)
        assert updated is not None
        await self._audit_event(
            action="campaign.updated",
            campaign=updated,
            actor_id=actor_id,
            after={k: str(v) for k, v in fields.items()},
        )
        await self._session.flush()
        return updated

    # --------------------------------------------------------------- validate

    async def validate_campaign(
        self,
        campaign_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None,
    ) -> CampaignValidationResponse:
        campaign = await self._get_or_404(campaign_id)
        if campaign.status not in {
            CampaignStatus.DRAFT.value,
            CampaignStatus.VALIDATING.value,
        }:
            raise StateTransitionError(
                f"campaign {campaign_id} cannot be validated in status={campaign.status}"
            )

        # transient state: VALIDATING — surfaces in API while we work.
        self._assert_transition(campaign.status, CampaignStatus.VALIDATING)
        await self._repo.update(
            campaign_id, status=CampaignStatus.VALIDATING.value
        )

        errors: list[ComplianceError] = []

        # 1. Template approval gate.
        template = await self._session.get(Template, campaign.template_id)
        if template is None:
            errors.append(
                ComplianceError(
                    code=ComplianceCode.TEMPLATE_NOT_APPROVED.value,
                    message="template not found",
                )
            )
        elif template.status != TemplateStatus.APPROVED.value:
            errors.append(
                ComplianceError(
                    code=ComplianceCode.TEMPLATE_NOT_APPROVED.value,
                    message=f"template is in status={template.status}, must be approved",
                    details={"template_id": str(template.id)},
                )
            )

        # 2. Schedule sanity.
        if campaign.type == CampaignType.SCHEDULED.value:
            if campaign.scheduled_at is None:
                errors.append(
                    ComplianceError(
                        code=ComplianceCode.SCHEDULED_AT_IN_PAST.value,
                        message="scheduled_at is required for scheduled campaigns",
                    )
                )
            else:
                ts = campaign.scheduled_at
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < datetime.now(UTC):
                    errors.append(
                        ComplianceError(
                            code=ComplianceCode.SCHEDULED_AT_IN_PAST.value,
                            message="scheduled_at is in the past",
                        )
                    )

        if campaign.type == CampaignType.RECURRING.value:
            if not campaign.cron_expression:
                errors.append(
                    ComplianceError(
                        code=ComplianceCode.INVALID_CRON.value,
                        message="cron_expression is required for recurring campaigns",
                    )
                )
            else:
                try:
                    from croniter import croniter

                    if not croniter.is_valid(campaign.cron_expression):
                        errors.append(
                            ComplianceError(
                                code=ComplianceCode.INVALID_CRON.value,
                                message=f"invalid cron expression: {campaign.cron_expression}",
                            )
                        )
                except ImportError:
                    errors.append(
                        ComplianceError(
                            code=ComplianceCode.INVALID_CRON.value,
                            message="croniter not installed on server",
                        )
                    )

        # 3. Audience materialisation. We snapshot here so recurring runs
        # can be re-materialised against the same filter; this also lets
        # validation surface "no recipients" before launch.
        contact_ids = await self._repo.select_audience_contact_ids(
            filter_payload=campaign.audience_filter or {},
        )
        if not contact_ids:
            errors.append(
                ComplianceError(
                    code=ComplianceCode.NO_RECIPIENTS.value,
                    message="no contacts match the audience filter",
                )
            )
        else:
            inserted = await self._recipient_repo.bulk_insert(
                campaign_id=campaign.id,
                contact_ids=contact_ids,
            )
            await self._repo.update(
                campaign_id, audience_count=len(contact_ids)
            )
            logger.info(
                "campaign_recipients_materialised",
                campaign_id=str(campaign_id),
                requested=len(contact_ids),
                inserted=inserted,
            )

        ok = not errors

        # Persist validation results + transition.
        # On failure we return to DRAFT (not FAILED) so the user can fix
        # the campaign (e.g. swap the template, widen the audience filter)
        # and re-validate. VALIDATING → DRAFT is an allowed transition.
        next_status = (
            CampaignStatus.SCHEDULED if ok else CampaignStatus.DRAFT
        )
        next_run_at: datetime | None = None
        if ok and campaign.type == CampaignType.SCHEDULED.value:
            next_run_at = campaign.scheduled_at
        elif ok and campaign.type == CampaignType.RECURRING.value:
            from croniter import croniter

            next_run_at = croniter(
                campaign.cron_expression, datetime.now(UTC)
            ).get_next(datetime)

        self._assert_transition(CampaignStatus.VALIDATING, next_status)
        await self._repo.update(
            campaign_id,
            status=next_status.value,
            validation_errors=[e.model_dump() for e in errors],
            next_run_at=next_run_at,
        )

        await self._audit_event(
            action="campaign.validated" if ok else "campaign.validation_failed",
            campaign=await self._get_or_404(campaign_id),
            actor_id=actor_id,
            after={
                "status": next_status.value,
                "errors": [e.code for e in errors],
                "audience_count": len(contact_ids),
            },
        )
        await self._session.flush()

        return CampaignValidationResponse(
            ok=ok,
            recipient_count=len(contact_ids),
            errors=errors,
        )

    # ----------------------------------------------------------------- launch

    async def launch_campaign(
        self,
        campaign_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None,
    ) -> Campaign:
        """Move SCHEDULED → QUEUED for an immediate campaign.

        For SCHEDULED/RECURRING types the launch is a no-op: the scheduler
        tick task picks them up at next_run_at. We still record an audit
        event so operators can see the explicit launch action.
        """
        campaign = await self._get_or_404(campaign_id)

        if campaign.status != CampaignStatus.SCHEDULED.value:
            raise StateTransitionError(
                f"campaign must be SCHEDULED to launch (was {campaign.status}); "
                "validate first."
            )

        if campaign.type == CampaignType.IMMEDIATE.value:
            self._assert_transition(campaign.status, CampaignStatus.QUEUED)
            await self._repo.update(
                campaign_id, status=CampaignStatus.QUEUED.value
            )
            campaign = await self._get_or_404(campaign_id)

        await self._audit_event(
            action="campaign.launched",
            campaign=campaign,
            actor_id=actor_id,
            after={"status": campaign.status, "type": campaign.type},
        )
        await self._session.flush()
        return campaign

    # ----------------------------------------------------------------- cancel

    async def cancel_campaign(
        self,
        campaign_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None,
    ) -> Campaign:
        campaign = await self._get_or_404(campaign_id)
        self._assert_transition(campaign.status, CampaignStatus.CANCELLED)
        cancelled = await self._recipient_repo.cancel_pending(campaign_id)
        await self._repo.update(
            campaign_id,
            status=CampaignStatus.CANCELLED.value,
            failed_count=campaign.failed_count + cancelled,
            completed_at=datetime.now(UTC),
        )
        updated = await self._get_or_404(campaign_id)
        await self._audit_event(
            action="campaign.cancelled",
            campaign=updated,
            actor_id=actor_id,
            after={"cancelled_recipients": cancelled},
        )
        await self._session.flush()
        return updated

    # ----------------------------------------------------------------- report

    async def get_report(self, campaign_id: uuid.UUID) -> CampaignReportResponse:
        campaign = await self._get_or_404(campaign_id)
        breakdown = await self._recipient_repo.count_by_status(campaign_id)
        errors = await self._recipient_repo.error_breakdown(campaign_id)
        pending = breakdown.get(CampaignRecipientStatus.PENDING.value, 0)
        sent = campaign.sent_count
        delivered = campaign.delivered_count
        failed = campaign.failed_count
        responses = campaign.response_count
        audience = campaign.audience_count

        delivery_rate = (delivered / sent) if sent else 0.0
        failure_rate = (failed / audience) if audience else 0.0
        response_rate = (responses / delivered) if delivered else 0.0

        duration: float | None = None
        if campaign.started_at and campaign.completed_at:
            duration = (campaign.completed_at - campaign.started_at).total_seconds()

        return CampaignReportResponse(
            campaign_id=campaign.id,
            status=campaign.status,
            audience_count=audience,
            sent_count=sent,
            delivered_count=delivered,
            failed_count=failed,
            response_count=responses,
            pending_count=pending,
            delivery_rate=round(delivery_rate, 4),
            failure_rate=round(failure_rate, 4),
            response_rate=round(response_rate, 4),
            started_at=campaign.started_at,
            completed_at=campaign.completed_at,
            duration_seconds=duration,
            status_breakdown=breakdown,
            error_breakdown=[
                CampaignErrorBreakdownItem(error_message=msg, error_code=ec, count=cnt)
                for msg, ec, cnt in errors
            ],
        )


class CampaignCategoryService:
    """Admin-managed display taxonomy. Flush only; router commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CampaignCategoryRepository(session)
        self._audit = AuditRepository(session)

    async def list_categories(
        self, *, q: str | None, limit: int, offset: int
    ) -> CampaignCategoryListResponse:
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        rows, total = await self._repo.list_paginated(q=q, limit=limit, offset=offset)
        items = [
            CampaignCategoryWithUsageResponse.model_validate(
                {
                    **CampaignCategoryResponse.model_validate(cat).model_dump(),
                    "usage_count": usage,
                }
            )
            for cat, usage in rows
        ]
        return CampaignCategoryListResponse(
            items=items, total=total, limit=limit, offset=offset
        )

    async def get_category(self, category_id: uuid.UUID) -> CampaignCategoryResponse:
        category = await self._repo.get(category_id)
        if category is None:
            raise NotFoundError(f"CampaignCategory:{category_id}")
        return CampaignCategoryResponse.model_validate(category)

    async def create_category(
        self,
        payload: CampaignCategoryCreateRequest,
        *,
        actor_id: uuid.UUID,
    ) -> CampaignCategoryResponse:
        existing = await self._repo.get_by_name(payload.name)
        if existing is not None:
            raise ConflictError("campaign_category_name_taken")

        category = await self._repo.create_category(
            name=payload.name,
            description=payload.description,
            color=payload.color,
        )
        await self._audit.append(
            actor_type=ActorType.USER.value,
            actor_id=actor_id,
            action=AuditAction.CREATE.value,
            entity_type="campaign_category",
            entity_id=category.id,
            before_state=None,
            after_state={
                "name": category.name,
                "description": category.description,
                "color": category.color,
            },
        )
        return CampaignCategoryResponse.model_validate(category)

    async def update_category(
        self,
        category_id: uuid.UUID,
        payload: CampaignCategoryUpdateRequest,
        *,
        actor_id: uuid.UUID,
    ) -> CampaignCategoryResponse:
        category = await self._repo.get(category_id)
        if category is None:
            raise NotFoundError(f"CampaignCategory:{category_id}")

        proposed = payload.model_dump(exclude_unset=True)
        diff = {k: v for k, v in proposed.items() if getattr(category, k) != v}
        if not diff:
            raise ConflictError("no_changes")

        if "name" in diff:
            taken = await self._repo.get_by_name(diff["name"])
            if taken is not None and taken.id != category.id:
                raise ConflictError("campaign_category_name_taken")

        before = {
            "name": category.name,
            "description": category.description,
            "color": category.color,
        }
        updated = await self._repo.apply_updates(category, diff)
        after = {
            "name": updated.name,
            "description": updated.description,
            "color": updated.color,
        }
        await self._audit.append(
            actor_type=ActorType.USER.value,
            actor_id=actor_id,
            action=AuditAction.UPDATE.value,
            entity_type="campaign_category",
            entity_id=updated.id,
            before_state=before,
            after_state=after,
        )
        return CampaignCategoryResponse.model_validate(updated)

    async def delete_category(
        self,
        category_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
    ) -> None:
        category = await self._repo.get(category_id)
        if category is None:
            raise NotFoundError(f"CampaignCategory:{category_id}")

        campaigns = await self._repo.count_campaign_links(category_id)
        if campaigns > 0:
            raise ConflictError(
                "campaign_category_in_use",
                details={"campaigns": campaigns},
            )

        snapshot = {
            "name": category.name,
            "description": category.description,
            "color": category.color,
        }
        await self._repo.delete_category(category)
        await self._audit.append(
            actor_type=ActorType.USER.value,
            actor_id=actor_id,
            action=AuditAction.DELETE.value,
            entity_type="campaign_category",
            entity_id=category_id,
            before_state=snapshot,
            after_state=None,
        )
