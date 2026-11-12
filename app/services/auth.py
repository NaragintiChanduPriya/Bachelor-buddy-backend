"""Registration, login, refresh-token rotation and logout."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import (
    burn_password_check,
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    refresh_expiry,
    verify_password,
    wall_now,
)
from app.db.models import RefreshToken, User, UserPreferences
from app.schemas.auth import AuthResponse, AuthTokens, LoginRequest, RegisterRequest
from app.services.users import load_user, to_user_out

BAD_CREDENTIALS = "Email or password is incorrect."


async def _issue_tokens(
    session: AsyncSession, user_id: int, settings: Settings, family_id: str | None = None
) -> AuthTokens:
    access, access_ttl = create_access_token(user_id, settings)
    refresh = new_refresh_token()
    expires_at, refresh_ttl = refresh_expiry(settings)
    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_token(refresh),
            family_id=family_id or uuid.uuid4().hex,
            expires_at=expires_at,
        )
    )
    return AuthTokens(
        access_token=access,
        refresh_token=refresh,
        expires_in=access_ttl,
        refresh_expires_in=refresh_ttl,
    )


async def _auth_response(session: AsyncSession, user_id: int, tokens: AuthTokens) -> AuthResponse:
    user = await load_user(session, user_id)
    if user is None:  # pragma: no cover - the row was just written
        raise UnauthorizedError()
    return AuthResponse(user=to_user_out(user), tokens=tokens)


async def register(
    session: AsyncSession, settings: Settings, clock: Clock, body: RegisterRequest
) -> AuthResponse:
    if await session.scalar(select(User.id).where(User.email == body.email)) is not None:
        raise ConflictError("An account with this email already exists. Sign in instead.")
    # bcrypt is deliberately slow; keep it off the event loop.
    password_hash = await asyncio.to_thread(hash_password, body.password, settings.bcrypt_rounds)
    user = User(
        email=body.email,
        password_hash=password_hash,
        name=body.name,
        age=body.age,
        occupation=body.occupation,
        onboarded=False,
        joined_at=clock.now(),
    )
    user.preferences = UserPreferences(salary=0, savings_goal=0)
    session.add(user)
    await session.flush()
    tokens = await _issue_tokens(session, user.id, settings)
    await session.commit()
    return await _auth_response(session, user.id, tokens)


async def login(session: AsyncSession, settings: Settings, body: LoginRequest) -> AuthResponse:
    row = (
        await session.execute(select(User.id, User.password_hash).where(User.email == body.email))
    ).one_or_none()
    if row is None:
        await asyncio.to_thread(burn_password_check, body.password, settings.bcrypt_rounds)
        raise UnauthorizedError(BAD_CREDENTIALS)
    user_id, password_hash = row
    if not await asyncio.to_thread(verify_password, body.password, password_hash):
        raise UnauthorizedError(BAD_CREDENTIALS)
    tokens = await _issue_tokens(session, user_id, settings)
    await session.commit()
    return await _auth_response(session, user_id, tokens)


async def _revoke_family(session: AsyncSession, family_id: str) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=wall_now())
    )


async def refresh(session: AsyncSession, settings: Settings, token: str) -> AuthTokens:
    """Rotate: the presented token is revoked and a new one issued in the same family. Reusing a
    revoked token means it was stolen, so the whole family is revoked."""
    row = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(token)).with_for_update()
    )
    if row is None:
        raise UnauthorizedError()
    if row.revoked_at is not None:
        await _revoke_family(session, row.family_id)
        await session.commit()
        raise UnauthorizedError()
    if row.expires_at <= wall_now():
        raise UnauthorizedError("Your session has expired. Please sign in again.")
    row.revoked_at = wall_now()
    tokens = await _issue_tokens(session, row.user_id, settings, row.family_id)
    await session.commit()
    return tokens


async def logout(session: AsyncSession, token: str) -> None:
    """Revokes every token from that login. Unknown tokens are ignored (no information leak)."""
    row = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(token))
    )
    if row is not None:
        await _revoke_family(session, row.family_id)
        await session.commit()
