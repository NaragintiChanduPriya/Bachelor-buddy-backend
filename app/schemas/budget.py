from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from app.core.constants import CATEGORY_IDS, BudgetCategoryId, BudgetStatus
from app.schemas.common import CamelModel
from app.schemas.validators import whole_number


class BudgetCategoryOut(CamelModel):
    id: BudgetCategoryId
    label: str
    limit: int
    spent: int
    remaining: int
    percent_used: int
    status: BudgetStatus


class BudgetOut(CamelModel):
    month: str
    salary: int
    total_limit: int
    total_spent: int
    total_remaining: int
    percent_used: int
    days_left_in_month: int
    daily_safe_spend: int
    categories: list[BudgetCategoryOut]


class CategoryLimitIn(CamelModel):
    id: str
    limit: int

    @field_validator("id")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if value not in CATEGORY_IDS:
            raise ValueError(f'Unknown budget category "{value}".')
        return value

    @field_validator("limit", mode="before")
    @classmethod
    def _whole(cls, value: Any) -> int:
        return whole_number(value, "Budget limits must be whole rupees.")


class UpdateBudgetRequest(CamelModel):
    categories: list[CategoryLimitIn] = Field(min_length=1)
