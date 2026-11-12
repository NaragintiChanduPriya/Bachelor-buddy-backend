"""Shared FastAPI dependencies: settings, clock, the current user and the service context."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import SessionDep
from app.services import users as user_service
from app.services.context import Ctx

logger = logging.getLogger(__name__)

#: `auto_error=False`: a missing header becomes our UNAUTHORIZED envelope, not FastAPI's 403.
bearer_scheme = HTTPBearer(auto_error=False, description="Access token from /auth/login")


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
ClockDep = Annotated[Clock, Depends(get_clock)]


async def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        if settings.dev_auth_bypass_email:
            user = await user_service.load_user_by_email(session, settings.dev_auth_bypass_email)
            if user is not None:
                return user
        raise UnauthorizedError("Sign in to continue.")
    user_id = decode_access_token(credentials.credentials, settings)
    user = await user_service.load_user(session, user_id)
    if user is None:
        raise UnauthorizedError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_onboarded_user(user: CurrentUser) -> User:
    prefs = user.preferences
    if not user.onboarded or prefs is None or not prefs.home_area_id or not prefs.office_area_id:
        raise ConflictError("Finish setting up your profile first.", {"onboarded": False})
    return user


OnboardedUser = Annotated[User, Depends(get_onboarded_user)]


async def get_ctx(
    session: SessionDep, user: OnboardedUser, clock: ClockDep, settings: SettingsDep
) -> Ctx:
    return Ctx(session=session, user=user, clock=clock, settings=settings)


CtxDep = Annotated[Ctx, Depends(get_ctx)]
