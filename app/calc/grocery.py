"""Grocery money math (port of src/mocks/calc/grocery.ts). See API_CONTRACT.md, "Grocery pricing
rules", for the definitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.core.constants import STORE_ORDER, STORE_TIE_ORDER, StoreType
from app.core.money import js_round
from app.schemas.grocery import (
    GroceryCompareRow,
    GroceryComparison,
    GroceryListItemOut,
    GroceryListOut,
    GroceryPlanSummary,
    StorePrices,
    StoreTotal,
)


@dataclass(frozen=True)
class CatalogItem:
    """One catalog item priced at the store chosen for each store type."""

    id: str
    name: str
    unit: str
    category: str
    prices: Mapping[StoreType, int]
    bulk_unit: str | None
    bulk_price: int | None
    bulk_multiple: int | None


@dataclass(frozen=True)
class LineCost:
    total: int
    bulk_applied: bool


def unit_or_bulk_cost(
    unit_price: int,
    quantity: int,
    bulk_price: int | None,
    bulk_multiple: int | None,
    allow_bulk: bool,
) -> LineCost:
    """`quantity` units; where bulk packs are sold, whole packs replace units when cheaper."""
    unit_total = unit_price * quantity
    if (
        allow_bulk
        and bulk_price is not None
        and bulk_multiple is not None
        and bulk_multiple > 1
        and quantity >= bulk_multiple
    ):
        packs, loose = divmod(quantity, bulk_multiple)
        bulk_total = packs * bulk_price + loose * unit_price
        if bulk_total < unit_total:
            return LineCost(bulk_total, True)
    return LineCost(unit_total, False)


def line_cost_at(item: CatalogItem, store: StoreType, quantity: int) -> LineCost:
    """`quantity` units at one store type. Only online bulk sells bulk packs."""
    return unit_or_bulk_cost(
        item.prices[store], quantity, item.bulk_price, item.bulk_multiple, store == "onlineBulk"
    )


def line_totals(item: CatalogItem, quantity: int) -> dict[StoreType, int]:
    return {store: line_cost_at(item, store, quantity).total for store in STORE_ORDER}


def cheapest_of(totals: Mapping[StoreType, int]) -> StoreType:
    """Lowest wins; ties go to the store earliest in the tie order (nearest home first)."""
    best = STORE_TIE_ORDER[0]
    for store in STORE_TIE_ORDER[1:]:
        if totals[store] < totals[best]:
            best = store
    return best


def build_compare_row(item: CatalogItem, quantity: int) -> GroceryCompareRow:
    totals = line_totals(item, quantity)
    return GroceryCompareRow(
        item_id=item.id,
        name=item.name,
        unit=item.unit,
        category=item.category,
        quantity=quantity,
        prices=StorePrices.of(dict(item.prices)),
        cheapest_store=cheapest_of(totals),
        line_totals=StorePrices.of(totals),
        bulk_applied=line_cost_at(item, "onlineBulk", quantity).bulk_applied,
    )


def list_line_id(item_id: str) -> str:
    """Line ids derive from the item id, so they stay stable across saves."""
    return "gli_" + item_id.removeprefix("groc_")


def build_grocery_list(
    entries: Sequence[tuple[CatalogItem, int]],
    month: str,
    updated_at_iso: object,
    labels: Mapping[StoreType, str],
) -> GroceryListOut:
    items: list[GroceryListItemOut] = []
    for item, quantity in entries:
        row = build_compare_row(item, quantity)
        line_total = row.line_totals.get(row.cheapest_store)
        items.append(
            GroceryListItemOut(
                id=list_line_id(item.id),
                item_id=item.id,
                name=item.name,
                unit=item.unit,
                category=item.category,
                quantity=quantity,
                cheapest_store=row.cheapest_store,
                cheapest_store_label=labels[row.cheapest_store],
                cheapest_unit_price=js_round(line_total / quantity),
                line_total=line_total,
                bulk_applied=row.cheapest_store == "onlineBulk" and row.bulk_applied,
            )
        )
    return GroceryListOut(
        id="glist_" + month.replace("-", ""),
        month=month,
        items=items,
        item_count=len(items),
        estimated_total=sum(line.line_total for line in items),
        updated_at=updated_at_iso,  # type: ignore[arg-type]
    )


def build_store_totals(
    rows: Sequence[GroceryCompareRow], labels: Mapping[StoreType, str]
) -> list[StoreTotal]:
    totals: dict[StoreType, int] = {
        store: sum(row.line_totals.get(store) for row in rows) for store in STORE_ORDER
    }
    cheapest = cheapest_of(totals)
    return [
        StoreTotal(
            store=store,
            label=labels[store],
            total=totals[store],
            is_cheapest=store == cheapest,
            difference_from_cheapest=totals[store] - totals[cheapest],
            cheapest_item_count=sum(1 for row in rows if row.cheapest_store == store),
        )
        for store in STORE_ORDER
    ]


def build_comparison(
    entries: Sequence[tuple[CatalogItem, int]], month: str, labels: Mapping[StoreType, str]
) -> GroceryComparison:
    rows = [build_compare_row(item, quantity) for item, quantity in entries]
    store_totals = build_store_totals(rows, labels)
    total_at = {t.store: t.total for t in store_totals}
    cheapest = next(t for t in store_totals if t.is_cheapest)
    mixed = sum(row.line_totals.get(row.cheapest_store) for row in rows)
    return GroceryComparison(
        month=month,
        item_count=len(rows),
        rows=rows,
        store_totals=store_totals,
        cheapest_store=cheapest.store,
        cheapest_store_label=cheapest.label,
        mixed_basket_total=mixed,
        bulk_saving=max(0, total_at["quickCommerce"] - total_at["onlineBulk"]),
        quick_commerce_extra=max(0, total_at["quickCommerce"] - mixed),
        split_saving=max(0, cheapest.total - mixed),
    )


def to_plan_summary(comparison: GroceryComparison) -> GroceryPlanSummary:
    return GroceryPlanSummary(
        month=comparison.month,
        item_count=comparison.item_count,
        estimated_total=comparison.mixed_basket_total,
        cheapest_store_label=comparison.cheapest_store_label,
        bulk_saving=comparison.bulk_saving,
    )
