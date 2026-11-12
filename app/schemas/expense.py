from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, field_validator

from app.core.constants import CATEGORY_IDS, BudgetCategoryId, ExpenseSource
from app.schemas.budget import BudgetCategoryOut
from app.schemas.common import CamelModel, UtcDateTime
from app.schemas.validators import clean_optional_text, whole_number

MAX_EXPENSE = 1_000_000


class ExpenseOut(CamelModel):
    id: str
    category: BudgetCategoryId
    category_label: str
    title: str
    note: str | None
    amount: int
    merchant: str | None
    source: ExpenseSource
    spent_at: UtcDateTime
    created_at: UtcDateTime


class ExpenseListResponse(CamelModel):
    expenses: list[ExpenseOut]
    filtered_total: int


class CreateExpenseRequest(CamelModel):
    category: str
    title: str
    amount: int
    merchant: str | None = None
    note: str | None = None
    #: Optional; defaults to the server's now. Must not be in the future.
    spent_at: AwareDatetime | None = None

    @field_validator("category", mode="before")
    @classmethod
    def _category(cls, value: Any) -> str:
        if value not in CATEGORY_IDS:
            raise ValueError("Choose a valid category.")
        return str(value)

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Give the expense a short title.")
        if len(value.strip()) > 120:
            raise ValueError("Keep the title under 120 characters.")
        return value.strip()

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, value: Any) -> int:
        amount = whole_number(value, "Enter an amount in whole rupees greater than zero.")
        if amount <= 0:
            raise ValueError("Enter an amount in whole rupees greater than zero.")
        if amount > MAX_EXPENSE:
            raise ValueError("That amount looks too large. Enter it in rupees.")
        return amount

    @field_validator("merchant", "note", mode="before")
    @classmethod
    def _optional_text(cls, value: Any) -> str | None:
        cleaned = clean_optional_text(value)
        if cleaned is not None and len(cleaned) > 500:
            raise ValueError("Keep it under 500 characters.")
        return cleaned

    @field_validator("spent_at", mode="before")
    @classmethod
    def _spent_at(cls, value: Any) -> Any:
        if value is None or isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            raise ValueError("The spent date is not a valid date.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("The spent date is not a valid date.") from None
        if parsed.tzinfo is None:
            raise ValueError("Include a time zone in the spent date, e.g. 2026-10-15T09:14:00Z.")
        return parsed


class CreateExpenseResponse(CamelModel):
    expense: ExpenseOut
    category: BudgetCategoryOut


class DeleteExpenseResponse(CamelModel):
    id: str
    category: BudgetCategoryOut
