"""Liveness and readiness probes. Public, outside the `/api` prefix, never rate limited."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter

from app import __version__
from app.api.deps import ClockDep, SettingsDep
from app.core.errors import ServiceUnavailableError
from app.db.session import DatabaseDep
from app.schemas.common import CamelModel, Envelope, ErrorEnvelope, UtcDateTime, ok

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthStatus(CamelModel):
    status: Literal["ok"] = "ok"
    version: str
    server_now: UtcDateTime


class ReadyStatus(CamelModel):
    status: Literal["ready"] = "ready"
    checks: dict[str, Literal["ok"]]


@router.get("/health", summary="Liveness: the process is up")
async def health(clock: ClockDep) -> Envelope[HealthStatus]:
    """Does not touch the database, so a database outage never restarts the API."""
    return ok(HealthStatus(version=__version__, server_now=clock.now()))


@router.get(
    "/ready",
    summary="Readiness: the database answers",
    responses={503: {"model": ErrorEnvelope, "description": "The database is not reachable"}},
)
async def ready(db: DatabaseDep, settings: SettingsDep) -> Envelope[ReadyStatus]:
    try:
        async with asyncio.timeout(settings.db_ready_timeout_seconds):
            await db.ping()
    except Exception as exc:
        logger.warning("readiness_failed", extra={"error": type(exc).__name__})
        raise ServiceUnavailableError(
            "The database is not reachable.", {"database": "unavailable"}
        ) from exc
    return ok(ReadyStatus(checks={"database": "ok"}))
