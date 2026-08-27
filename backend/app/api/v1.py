"""Versioned API aggregator. Each module exposes a `router` symbol it registers here."""

from fastapi import APIRouter

from app.modules.ai.router import router as ai_router
from app.modules.analytics.router import router as analytics_router
from app.modules.assignments.router import router as assignments_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.campaigns.router import (
    categories_router as campaign_categories_router,
)
from app.modules.campaigns.router import (
    router as campaigns_router,
)
from app.modules.categorization.router import router as categorization_router
from app.modules.contacts.router import router as contacts_router
from app.modules.conversations.router import router as conversations_router
from app.modules.ledger.router import router as ledger_router
from app.modules.payables.router import router as payables_router
from app.modules.receivables.router import router as receivables_router
from app.modules.media.router import router as media_router
from app.modules.messaging.router import messages_router as messaging_router
from app.modules.settings.router import router as settings_router
from app.modules.templates.router import router as templates_router
from app.modules.users.router import router as users_router
from app.modules.inventory.router import router as inventory_router
from app.modules.procurement.router import router as procurement_router
from app.modules.fulfilment.router import router as fulfilment_router
from app.modules.erp_reporting.router import router as erp_reporting_router
from app.modules.market.router import router as market_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router)
api_router.include_router(contacts_router)
api_router.include_router(conversations_router)
api_router.include_router(messaging_router)
api_router.include_router(media_router)
api_router.include_router(ai_router)
api_router.include_router(campaigns_router)
api_router.include_router(campaign_categories_router)
api_router.include_router(templates_router)
api_router.include_router(categorization_router)
api_router.include_router(analytics_router)
api_router.include_router(assignments_router)
api_router.include_router(audit_router)
api_router.include_router(settings_router)
api_router.include_router(ledger_router)
api_router.include_router(payables_router)
api_router.include_router(receivables_router)
api_router.include_router(users_router)
api_router.include_router(inventory_router)
api_router.include_router(procurement_router)
api_router.include_router(fulfilment_router)
api_router.include_router(erp_reporting_router)
api_router.include_router(market_router)
