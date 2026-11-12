"""Passwords, access tokens and refresh tokens.

Token lifetimes always use the real wall clock, never the demo clock: in CLOCK_MODE=demo "now"
is the 15th of the month, and an expiry computed from it could be days in the future.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import bcrypt
import jwt

from app.core.config import Settings
from app.core.errors import UnauthorizedError

ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - a token kind, not a secret


def wall_now() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str, rounds: int) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:  # malformed hash, or a password over bcrypt's 72-byte limit
        return False


@lru_cache(maxsize=4)
def _dummy_hash(rounds: int) -> str:
    return hash_password(secrets.token_urlsafe(16), rounds)


def burn_password_check(password: str, rounds: int) -> None:
    """Spend the same time as a real check when the email is unknown, so response timing does
    not reveal which emails are registered."""
    verify_password(password, _dummy_hash(rounds))


def create_access_token(user_id: int, settings: Settings) -> tuple[str, int]:
    """A signed JWT and its lifetime in seconds."""
    now = wall_now()
    lifetime = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str, settings: Settings) -> int:
    """The user id in a valid access token. Anything else is UNAUTHORIZED."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Your session has expired. Please sign in again.") from None
    except jwt.PyJWTError:
        raise UnauthorizedError() from None
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise UnauthorizedError()
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.isdigit():
        raise UnauthorizedError()
    return int(subject)


def peek_user_id(token: str, settings: Settings) -> int | None:
    """The user id of a valid token, or None. For rate-limit keys; never raises."""
    try:
        return decode_access_token(token, settings)
    except UnauthorizedError:
        return None


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def refresh_expiry(settings: Settings) -> tuple[datetime, int]:
    lifetime = timedelta(days=settings.jwt_refresh_token_expire_days)
    return wall_now() + lifetime, int(lifetime.total_seconds())
