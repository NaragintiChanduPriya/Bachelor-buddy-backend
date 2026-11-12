"""POST /auth/register, /auth/login, /auth/refresh, /auth/logout. Public, rate limited per IP."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import ClockDep, SettingsDep
from app.core.ratelimit import auth_limit, limiter
from app.db.session import SessionDep
from app.schemas.auth import (
    AuthResponse,
    AuthTokens,
    LoginRequest,
    LogoutResponse,
    RefreshRequest,
    RegisterRequest,
)
from app.schemas.common import Envelope, ok
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", summary="Create an account and sign in")
@limiter.limit(auth_limit)
async def register(
    request: Request,
    body: RegisterRequest,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> Envelope[AuthResponse]:
    return ok(await auth_service.register(session, settings, clock, body))


@router.post("/login", summary="Sign in with email and password")
@limiter.limit(auth_limit)
async def login(
    request: Request, body: LoginRequest, session: SessionDep, settings: SettingsDep
) -> Envelope[AuthResponse]:
    return ok(await auth_service.login(session, settings, body))


@router.post("/refresh", summary="Swap a refresh token for a new token pair (rotation)")
@limiter.limit(auth_limit)
async def refresh(
    request: Request, body: RefreshRequest, session: SessionDep, settings: SettingsDep
) -> Envelope[AuthTokens]:
    return ok(await auth_service.refresh(session, settings, body.refresh_token))


@router.post("/logout", summary="Revoke the refresh token (and every token from that login)")
async def logout(body: RefreshRequest, session: SessionDep) -> Envelope[LogoutResponse]:
    await auth_service.logout(session, body.refresh_token)
    return ok(LogoutResponse())
