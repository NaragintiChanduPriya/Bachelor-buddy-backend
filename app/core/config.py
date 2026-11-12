"""Application settings, read only from environment variables and `.env`.

The API process never sees the PostgreSQL admin credentials: those are read separately by
`scripts/_pg.py`, which only the setup and reset scripts use.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

#: Placeholder values from `.env.example` that must never reach a running server.
_PLACEHOLDERS = {"", "change-me"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",  # admin credentials and other script-only keys live in the same file
        case_sensitive=False,
    )

    # --- runtime
    app_env: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "json"

    # --- database (the app role, never the admin account)
    database_url: SecretStr
    test_database_url: SecretStr | None = None
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    #: Long enough for a scaled-to-zero Neon compute to wake on the first probe.
    db_ready_timeout_seconds: float = Field(default=10.0, gt=0, le=30)

    # --- auth
    jwt_secret: SecretStr
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=15, ge=1, le=24 * 60)
    jwt_refresh_token_expire_days: int = Field(default=7, ge=1, le=90)
    demo_user_password: SecretStr | None = None
    #: bcrypt cost. 12 is ~250 ms per hash; tests use 4.
    bcrypt_rounds: int = Field(default=12, ge=4, le=15)
    #: DEVELOPMENT ONLY. Requests without a token act as this user, so the unmodified frontend
    #: can run against the real API before login is added. Refused when APP_ENV=production.
    dev_auth_bypass_email: str | None = None

    # --- AI agents
    groq_api_key: SecretStr | None = None
    groq_model: str | None = None
    groq_fast_model: str | None = None
    agent_mode: Literal["llm", "rules"] = "rules"
    groq_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    #: Model turns the Concierge may take per message (each specialist gets at most 3).
    agent_max_iterations: int = Field(default=4, ge=1, le=10)
    #: Earlier messages of the conversation sent to the model.
    agent_history_messages: int = Field(default=6, ge=0, le=30)
    agent_max_tokens: int = Field(default=900, ge=100, le=4000)
    #: Token saver: give the Concierge the specialist tools directly instead of running each
    #: specialist as its own model call. Useful on Groq's free tier.
    agent_direct_tools: bool = False

    # --- HTTP
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    rate_limit_enabled: bool = True
    rate_limit_auth: str = "10/minute"
    rate_limit_chat: str = "20/minute"

    # --- data and time
    seed_value: int = 42
    tz: str = "Asia/Kolkata"
    #: real = the wall clock (production). demo = the 15th of this month, 12:30 IST. fixed = the
    #: instant in CLOCK_FIXED_AT (end-to-end tests against the test database).
    clock_mode: Literal["real", "demo", "fixed"] = "real"
    clock_fixed_at: datetime | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_origin(cls, value: list[str]) -> list[str]:
        # Credentials (the Authorization header) are allowed, so a wildcard would be unsafe.
        if "*" in value:
            raise ValueError("CORS_ORIGINS must list exact origins; '*' is not allowed")
        return value

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _async_driver(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("database URLs must use the async driver: postgresql+asyncpg://...")
        return value

    @field_validator("jwt_secret")
    @classmethod
    def _strong_jwt_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if secret in _PLACEHOLDERS or len(secret) < 32:
            raise ValueError(
                "JWT_SECRET must be at least 32 characters. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return value

    @field_validator("tz")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {value!r}") from exc
        return value

    @field_validator("api_prefix")
    @classmethod
    def _normalise_prefix(cls, value: str) -> str:
        value = "/" + value.strip("/")
        return "" if value == "/" else value

    @model_validator(mode="after")
    def _no_bypass_in_production(self) -> Settings:
        if self.dev_auth_bypass_email and self.app_env == "production":
            raise ValueError("DEV_AUTH_BYPASS_EMAIL must be empty when APP_ENV=production")
        if self.clock_mode == "fixed" and (
            self.clock_fixed_at is None or self.clock_fixed_at.tzinfo is None
        ):
            raise ValueError("CLOCK_MODE=fixed needs CLOCK_FIXED_AT with a timezone, e.g. ...Z")
        if self.app_env == "production" and self.clock_mode != "real":
            raise ValueError("APP_ENV=production needs CLOCK_MODE=real")
        return self

    @property
    def llm_available(self) -> bool:
        return bool(self.groq_api_key and self.groq_api_key.get_secret_value() and self.groq_model)

    @property
    def zone(self) -> ZoneInfo:
        """The business time zone (Asia/Kolkata)."""
        return ZoneInfo(self.tz)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Settings for the running process, loaded once."""
    return Settings()
