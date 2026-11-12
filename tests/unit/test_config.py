from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings

DB_PASSWORD = "db-pass-not-for-logs"
JWT = "j" * 48


def make(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": f"postgresql+asyncpg://app:{DB_PASSWORD}@localhost:5432/bb",
        "jwt_secret": JWT,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_cors_origins_are_split_and_trimmed() -> None:
    settings = make(cors_origins="http://localhost:5173, https://app.example.com/ ,")
    assert settings.cors_origins == ["http://localhost:5173", "https://app.example.com"]


def test_wildcard_cors_origin_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exact origins"):
        make(cors_origins="*")


@pytest.mark.parametrize("secret", ["change-me", "", "short-secret"])
def test_weak_jwt_secret_is_rejected(secret: str) -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        make(jwt_secret=secret)


def test_sync_database_driver_is_rejected() -> None:
    with pytest.raises(ValidationError, match="async driver"):
        make(database_url="postgresql://app:pw@localhost/bb")


def test_unknown_time_zone_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown time zone"):
        make(tz="Mars/Olympus_Mons")


@pytest.mark.parametrize(
    ("raw", "expected"), [("api", "/api"), ("/api/", "/api"), ("/v1/api", "/v1/api"), ("/", "")]
)
def test_api_prefix_is_normalised(raw: str, expected: str) -> None:
    assert make(api_prefix=raw).api_prefix == expected


def test_secrets_never_appear_in_repr() -> None:
    settings = make(groq_api_key="gsk_live_value")
    text = repr(settings) + str(settings)
    assert DB_PASSWORD not in text
    assert JWT not in text
    assert "gsk_live_value" not in text


def test_business_zone_and_production_flag() -> None:
    settings = make(app_env="production")
    assert settings.zone.key == "Asia/Kolkata"
    assert settings.is_production
    assert not make().is_production
