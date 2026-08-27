"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import register_middleware
from app.modules.conversations.ws import ws_inbox
from app.modules.messaging.router import router as webhook_router
from app.schemas.common import HealthResponse


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    logger = get_logger(__name__)

    app = FastAPI(
        title="EngageOS API",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_middleware(app)
    register_exception_handlers(app)

    # Mount routers.
    app.include_router(api_router)
    app.include_router(webhook_router)  # /webhooks/meta lives outside /api/v1

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        # DSD §11: surface read-only emergency mode so ops/loadbalancers
        # can see degraded state. Flag is read fresh (not the closured
        # `settings`) so a runtime flip is reflected without redeploy.
        read_only = get_settings().READ_ONLY_MODE
        return HealthResponse(
            status="degraded" if read_only else "ok",
            service=settings.SERVICE_NAME,
            version=__version__,
            read_only=read_only,
        )

    app.websocket("/ws/inbox")(ws_inbox)

    logger.info("app_started", env=settings.ENV, version=__version__)
    return app


app = create_app()
