from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from app.core.constants import StoreType
from app.schemas.common import CamelModel, UtcDateTime
from app.schemas.validators import whole_number

MAX_LIST_LINES = 80
MIN_QUANTITY = 1
MAX_QUANTITY = 50


class StorePrices(CamelModel):
    """`Record<StoreType, number>`: one value per store type, always all four."""

    quick_commerce: int
    supermarket: int
    kirana: int
    online_bulk: int

    def get(self, store: StoreType) -> int:
        return {
            "quickCommerce": self.quick_commerce,
            "supermarket": self.supermarket,
            "kirana": self.kirana,
            "onlineBulk": self.online_bulk,
        }[store]

    @classmethod
    def of(cls, values: dict[StoreType, int]) -> StorePrices:
        return cls(
            quick_commerce=values["quickCommerce"],
            supermarket=values["supermarket"],
            kirana=values["kirana"],
            online_bulk=values["onlineBulk"],
        )


class GroceryCatalogItem(CamelModel):
    id: str
    name: str
    unit: str
    category: str
    prices: StorePrices
    bulk_unit: str | None
    bulk_price: int | None
    bulk_multiple: int | None


class GroceryListItemOut(CamelModel):
    id: str
    item_id: str
    name: str
    unit: str
    category: str
    quantity: int
    cheapest_store: StoreType
    cheapest_store_label: str
    cheapest_unit_price: int
    line_total: int
    bulk_applied: bool


class GroceryListOut(CamelModel):
    id: str
    month: str
    items: list[GroceryListItemOut]
    item_count: int
    estimated_total: int
    updated_at: UtcDateTime


class StoreTotal(CamelModel):
    store: StoreType
    label: str
    total: int
    is_cheapest: bool
    difference_from_cheapest: int
    cheapest_item_count: int


class GroceryCompareRow(CamelModel):
    item_id: str
    name: str
    unit: str
    category: str
    quantity: int
    prices: StorePrices
    cheapest_store: StoreType
    line_totals: StorePrices
    bulk_applied: bool


class GroceryComparison(CamelModel):
    month: str
    item_count: int
    rows: list[GroceryCompareRow]
    store_totals: list[StoreTotal]
    cheapest_store: StoreType
    cheapest_store_label: str
    mixed_basket_total: int
    bulk_saving: int
    quick_commerce_extra: int
    split_saving: int


class GroceryPlanSummary(CamelModel):
    month: str
    item_count: int
    estimated_total: int
    cheapest_store_label: str
    bulk_saving: int


class GroceryEntryIn(CamelModel):
    item_id: str = Field(max_length=20)
    quantity: int

    @field_validator("quantity", mode="before")
    @classmethod
    def _quantity(cls, value: Any) -> int:
        message = f"Quantities must be whole numbers from {MIN_QUANTITY} to {MAX_QUANTITY}."
        quantity = whole_number(value, message)
        if not MIN_QUANTITY <= quantity <= MAX_QUANTITY:
            raise ValueError(message)
        return quantity


class UpdateGroceryListRequest(CamelModel):
    items: list[GroceryEntryIn] = Field(max_length=MAX_LIST_LINES)
