"""Application factory. `app.main` builds the process-wide app; tests build their own."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app import __version__
from app.agents.llm import GroqClient, LLMClient
from app.api.health import router as health_router
from app.api.router import api_router
from app.core.clock import Clock, build_clock
from app.core.config import Settings, get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.core.ratelimit import limiter, rate_limit_handler
from app.db.session import Database

logger = logging.getLogger(__name__)

DESCRIPTION = """
Backend for **BachelorBuddy**: budgets, expenses and the cheapest good options for food,
groceries, shopping and housing in Bangalore, plus the AI agents behind Ask Buddy.

Every response uses the envelope
`{ "success", "data", "meta", "error" }`. JSON is camelCase, money is integer rupees and
timestamps are UTC ISO 8601 strings.
"""


def build_llm(settings: Settings) -> LLMClient | None:
    if not settings.llm_available or settings.groq_api_key is None:
        return None
    return GroqClient(settings.groq_api_key.get_secret_value(), settings.groq_timeout_seconds)


def create_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    clock: Clock | None = None,
    llm: LLMClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)
    db = database or Database.from_settings(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "startup",
            extra={
                "env": settings.app_env,
                "clock_mode": settings.clock_mode,
                "agent_mode": settings.agent_mode,
            },
        )
        yield
        await db.dispose()
        logger.info("shutdown")

    app = FastAPI(
        title="BachelorBuddy API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    app.state.db = db
    app.state.clock = clock or build_clock(settings)
    app.state.llm = llm or build_llm(settings)
    app.state.limiter = limiter
    limiter.enabled = settings.rate_limit_enabled
    if settings.dev_auth_bypass_email:
        logger.warning(
            "dev_auth_bypass_enabled",
            extra={"note": "requests without a token act as the configured user"},
        )

    install_exception_handlers(app)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_prefix)

    # Middleware added last runs first: CORS wraps the request context, so CORS headers are
    # present even on the 500 the request middleware produces for an unhandled exception.
    app.add_middleware(RequestContextMiddleware, hsts=settings.is_production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # bearer tokens travel in a header, not cookies
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, "Retry-After"],
        max_age=600,
    )
    return app
