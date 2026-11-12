"""Auth DTOs. These endpoints are new (the mock had no auth); see FRONTEND_INTEGRATION.md."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import EmailStr, Field, field_validator, model_validator

from app.schemas.common import CamelModel
from app.schemas.user import UserOut
from app.schemas.validators import whole_number

PASSWORD_MIN = 8
#: bcrypt only uses the first 72 bytes, and bcrypt 5 refuses longer input outright.
PASSWORD_MAX_BYTES = 72


def check_password_strength(password: str) -> str:
    if len(password) < PASSWORD_MIN:
        raise ValueError(f"Use at least {PASSWORD_MIN} characters for your password.")
    if len(password.encode()) > PASSWORD_MAX_BYTES:
        raise ValueError("Keep your password under 72 bytes.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("Use at least one letter and one number in your password.")
    if password.strip() != password:
        raise ValueError("Your password cannot start or end with a space.")
    return password


class RegisterRequest(CamelModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str
    age: int
    occupation: str = Field(min_length=1, max_length=80)

    @field_validator("name", "occupation", mode="before")
    @classmethod
    def _trim(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower()

    @field_validator("password")
    @classmethod
    def _strong(cls, value: str) -> str:
        return check_password_strength(value)

    @field_validator("age", mode="before")
    @classmethod
    def _age(cls, value: Any) -> int:
        age = whole_number(value, "Enter your age in whole years.")
        if not 16 <= age <= 100:
            raise ValueError("Enter an age between 16 and 100.")
        return age

    @model_validator(mode="after")
    def _password_is_not_email(self) -> RegisterRequest:
        if self.password.lower() == self.email:
            raise ValueError("Your password cannot be your email address.")
        return self


class LoginRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower()


class RefreshRequest(CamelModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class AuthTokens(CamelModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - scheme name
    #: Seconds until the access token expires.
    expires_in: int
    refresh_expires_in: int


class AuthResponse(CamelModel):
    user: UserOut
    tokens: AuthTokens


class LogoutResponse(CamelModel):
    logged_out: bool = True
