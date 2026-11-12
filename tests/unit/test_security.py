from __future__ import annotations

import time

import jwt
import pytest

from app.core.config import Settings
from app.core.errors import UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    peek_user_id,
    verify_password,
)
from app.schemas.auth import check_password_strength
from tests.conftest import load_test_settings


@pytest.fixture
def settings() -> Settings:
    return load_test_settings()


def test_password_hashing() -> None:
    hashed = hash_password("correct horse 9", 4)
    assert hashed.startswith("$2b$04$")
    assert verify_password("correct horse 9", hashed)
    assert not verify_password("wrong horse 9", hashed)
    assert not verify_password("x", "not-a-bcrypt-hash")


@pytest.mark.parametrize(
    ("password", "fragment"),
    [
        ("short1", "at least 8"),
        ("onlyletters", "letter and one number"),
        ("12345678", "letter and one number"),
        (" padded99 ", "start or end with a space"),
        ("ä" * 40 + "1", "72 bytes"),
    ],
)
def test_password_rules(password: str, fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        check_password_strength(password)
    assert check_password_strength("budget2026") == "budget2026"


def test_access_token_round_trip(settings: Settings) -> None:
    token, lifetime = create_access_token(42, settings)
    assert lifetime == settings.jwt_access_token_expire_minutes * 60
    assert decode_access_token(token, settings) == 42
    assert peek_user_id(token, settings) == 42


def test_expired_token_is_unauthorized(settings: Settings) -> None:
    secret = settings.jwt_secret.get_secret_value()
    past = int(time.time()) - 60
    token = jwt.encode({"sub": "1", "type": "access", "exp": past}, secret, algorithm="HS256")
    with pytest.raises(UnauthorizedError, match="expired"):
        decode_access_token(token, settings)


@pytest.mark.parametrize(
    "payload",
    [
        {"sub": "1", "type": "refresh", "exp": 9999999999},
        {"sub": "abc", "type": "access", "exp": 9999999999},
        {"type": "access", "exp": 9999999999},
    ],
)
def test_wrong_tokens_are_unauthorized(settings: Settings, payload: dict[str, object]) -> None:
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    with pytest.raises(UnauthorizedError):
        decode_access_token(token, settings)


def test_tampered_or_foreign_tokens_are_unauthorized(settings: Settings) -> None:
    token, _ = create_access_token(1, settings)
    forged = jwt.encode(
        {"sub": "1", "type": "access", "exp": 9999999999}, "x" * 40, algorithm="HS256"
    )
    for bad in (token[:-2] + "xx", forged, "not.a.jwt"):
        with pytest.raises(UnauthorizedError):
            decode_access_token(bad, settings)
        assert peek_user_id(bad, settings) is None


def test_refresh_tokens_are_random_and_stored_hashed() -> None:
    first, second = new_refresh_token(), new_refresh_token()
    assert first != second and len(first) >= 60
    assert len(hash_token(first)) == 64 and hash_token(first) != first
