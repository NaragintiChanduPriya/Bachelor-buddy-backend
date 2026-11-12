from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from app.core.constants import FOOD_PREFERENCES, CardType, FoodPreference
from app.schemas.budget import BudgetOut
from app.schemas.common import CamelModel, UtcDateTime
from app.schemas.validators import whole_number


class SavedCard(CamelModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    bank: str = Field(min_length=1, max_length=40)
    type: CardType
    label: str = Field(min_length=1, max_length=80)


class UserPreferencesOut(CamelModel):
    salary: int
    savings_goal: int
    home_area_id: str
    home_area_name: str
    office_area_id: str
    office_area_name: str
    tech_park_id: str | None
    tech_park_name: str | None
    food_preference: FoodPreference
    cards: list[SavedCard]


class UserOut(CamelModel):
    id: str
    name: str
    email: str
    age: int
    occupation: str
    avatar_initials: str
    onboarded: bool
    joined_at: UtcDateTime
    preferences: UserPreferencesOut


def _salary(value: Any) -> int:
    return whole_number(value, "Enter a monthly salary of at least ₹5,000 in whole rupees.")


def _goal(value: Any) -> int:
    return whole_number(value, "Enter a savings goal in whole rupees.")


def _food(value: Any) -> str:
    if value not in FOOD_PREFERENCES:
        raise ValueError("Choose a food preference.")
    return str(value)


class OnboardingRequest(CamelModel):
    """Field-level checks here; cross-field and database checks (areas exist, goal below salary)
    happen in the service, so the same rules apply to PUT /me/preferences."""

    salary: int
    savings_goal: int
    home_area_id: str
    office_area_id: str
    tech_park_id: str | None = None
    food_preference: FoodPreference
    cards: list[SavedCard] = Field(default_factory=list, max_length=12)

    @field_validator("salary", mode="before")
    @classmethod
    def _v_salary(cls, value: Any) -> int:
        return _salary(value)

    @field_validator("savings_goal", mode="before")
    @classmethod
    def _v_goal(cls, value: Any) -> int:
        return _goal(value)

    @field_validator("food_preference", mode="before")
    @classmethod
    def _v_food(cls, value: Any) -> str:
        return _food(value)


class PreferencesUpdateRequest(CamelModel):
    """Every field optional; omitted fields keep their value. `techParkId: null` clears it."""

    salary: int | None = None
    savings_goal: int | None = None
    home_area_id: str | None = None
    office_area_id: str | None = None
    tech_park_id: str | None = None
    food_preference: FoodPreference | None = None
    cards: list[SavedCard] | None = Field(default=None, max_length=12)

    @field_validator("salary", mode="before")
    @classmethod
    def _v_salary(cls, value: Any) -> int | None:
        return None if value is None else _salary(value)

    @field_validator("savings_goal", mode="before")
    @classmethod
    def _v_goal(cls, value: Any) -> int | None:
        return None if value is None else _goal(value)

    @field_validator("food_preference", mode="before")
    @classmethod
    def _v_food(cls, value: Any) -> str | None:
        return None if value is None else _food(value)


class OnboardingResponse(CamelModel):
    user: UserOut
    budget: BudgetOut
