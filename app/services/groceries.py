"""Groceries: catalog, the monthly list, and the four-store comparison.

There are two stores per store type. For each type the comparison uses whichever of its stores
is cheaper for the user's whole list (the primary store when the list is empty), and the
catalog shows that same store's prices, so every page agrees.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.calc.grocery import (
    CatalogItem,
    build_comparison,
    build_grocery_list,
    to_plan_summary,
    unit_or_bulk_cost,
)
from app.core.constants import GROCERY_CATEGORIES, STORE_ORDER, StoreType
from app.core.errors import ValidationFailedError
from app.db.models import GroceryItem, GroceryList, GroceryListItem, GroceryPrice, Store
from app.schemas.grocery import (
    GroceryCatalogItem,
    GroceryComparison,
    GroceryListOut,
    GroceryPlanSummary,
    StorePrices,
    UpdateGroceryListRequest,
)
from app.services.context import Ctx


@dataclass
class Catalog:
    items: list[GroceryItem]
    stores: list[Store]
    #: item id -> store id -> (unit price, bulk pack price)
    prices: dict[str, dict[str, tuple[int, int | None]]]

    def by_id(self) -> dict[str, GroceryItem]:
        return {item.id: item for item in self.items}


async def load_catalog(ctx: Ctx) -> Catalog:
    items = list(await ctx.session.scalars(select(GroceryItem).order_by(GroceryItem.position)))
    stores = list(await ctx.session.scalars(select(Store).order_by(Store.position)))
    prices: dict[str, dict[str, tuple[int, int | None]]] = defaultdict(dict)
    for row in await ctx.session.scalars(select(GroceryPrice)):
        prices[row.item_id][row.store_id] = (row.price, row.bulk_price)
    return Catalog(items, stores, dict(prices))


def _priced(item: GroceryItem, catalog: Catalog, chosen: dict[StoreType, Store]) -> CatalogItem:
    row = catalog.prices.get(item.id, {})
    bulk_store = chosen["onlineBulk"]
    return CatalogItem(
        id=item.id,
        name=item.name,
        unit=item.unit,
        category=item.category,
        prices={t: row[chosen[t].id][0] for t in STORE_ORDER},
        bulk_unit=item.bulk_unit,
        bulk_price=row[bulk_store.id][1] if item.bulk_unit else None,
        bulk_multiple=item.bulk_multiple,
    )


def choose_stores(catalog: Catalog, entries: Sequence[tuple[str, int]]) -> dict[StoreType, Store]:
    """Per store type, the store with the lowest total for this list (primary on a tie)."""
    by_id = catalog.by_id()
    chosen: dict[StoreType, Store] = {}
    for store_type in STORE_ORDER:
        candidates = [s for s in catalog.stores if s.store_type == store_type]
        candidates.sort(key=lambda s: (not s.is_primary, s.position))

        def total_at(store: Store, store_type: StoreType = store_type) -> int:
            total = 0
            for item_id, quantity in entries:
                item = by_id.get(item_id)
                if item is None:
                    continue
                unit, bulk = catalog.prices[item_id][store.id]
                total += unit_or_bulk_cost(
                    unit, quantity, bulk, item.bulk_multiple, store_type == "onlineBulk"
                ).total
            return total

        best = candidates[0]
        if entries:
            best_total = total_at(best)
            for store in candidates[1:]:
                store_total = total_at(store)
                if store_total < best_total:
                    best, best_total = store, store_total
        chosen[store_type] = best
    return chosen


def labels_of(chosen: dict[StoreType, Store]) -> dict[StoreType, str]:
    return {t: chosen[t].name for t in STORE_ORDER}


async def _list_for_month(ctx: Ctx, month: str) -> GroceryList | None:
    return (
        (
            await ctx.session.execute(
                select(GroceryList)
                .options(joinedload(GroceryList.items))
                .where(GroceryList.user_id == ctx.user.id, GroceryList.month == month)
            )
        )
        .unique()
        .scalar_one_or_none()
    )


async def current_list_row(ctx: Ctx) -> GroceryList:
    """This month's list; on the first visit of a month, last month's list is carried over."""
    month = ctx.clock.month_key()
    current = await _list_for_month(ctx, month)
    if current is not None:
        return current
    previous = (
        (
            await ctx.session.execute(
                select(GroceryList)
                .options(joinedload(GroceryList.items))
                .where(GroceryList.user_id == ctx.user.id, GroceryList.month < month)
                .order_by(GroceryList.month.desc())
                .limit(1)
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    current = GroceryList(user_id=ctx.user.id, month=month, updated_at=ctx.clock.now(), items=[])
    if previous is not None:
        current.items = [
            GroceryListItem(item_id=i.item_id, quantity=i.quantity, position=i.position)
            for i in previous.items
        ]
    ctx.session.add(current)
    await ctx.session.commit()
    return current


def _entries(row: GroceryList) -> list[tuple[str, int]]:
    return [(i.item_id, i.quantity) for i in row.items]


def _resolve(
    catalog: Catalog, chosen: dict[StoreType, Store], entries: Sequence[tuple[str, int]]
) -> list[tuple[CatalogItem, int]]:
    by_id = catalog.by_id()
    return [
        (_priced(by_id[item_id], catalog, chosen), quantity)
        for item_id, quantity in entries
        if item_id in by_id and quantity > 0
    ]


async def catalog_items(ctx: Ctx, q: str | None, category: str | None) -> list[GroceryCatalogItem]:
    catalog = await load_catalog(ctx)
    row = await current_list_row(ctx)
    chosen = choose_stores(catalog, _entries(row))
    needle = (q or "").strip().lower()
    result = []
    for item in catalog.items:
        if category and item.category != category:
            continue
        if needle and needle not in item.name.lower():
            continue
        priced = _priced(item, catalog, chosen)
        result.append(
            GroceryCatalogItem(
                id=item.id,
                name=item.name,
                unit=item.unit,
                category=item.category,
                prices=StorePrices.of(dict(priced.prices)),
                bulk_unit=priced.bulk_unit,
                bulk_price=priced.bulk_price,
                bulk_multiple=priced.bulk_multiple,
            )
        )
    return result


def grocery_categories() -> tuple[str, ...]:
    return GROCERY_CATEGORIES


async def current_list(ctx: Ctx) -> GroceryListOut:
    catalog = await load_catalog(ctx)
    row = await current_list_row(ctx)
    entries = _entries(row)
    chosen = choose_stores(catalog, entries)
    return build_grocery_list(
        _resolve(catalog, chosen, entries), row.month, row.updated_at, labels_of(chosen)
    )


async def replace_list(ctx: Ctx, body: UpdateGroceryListRequest) -> GroceryListOut:
    catalog = await load_catalog(ctx)
    by_id = catalog.by_id()
    seen: set[str] = set()
    for entry in body.items:
        item = by_id.get(entry.item_id)
        if item is None:
            raise ValidationFailedError(f'Unknown grocery item "{entry.item_id}".')
        if entry.item_id in seen:
            raise ValidationFailedError(
                f"{item.name} is on the list twice. Combine them into one line."
            )
        seen.add(entry.item_id)
    row = await current_list_row(ctx)
    row.items.clear()
    await ctx.session.flush()
    row.items.extend(
        GroceryListItem(item_id=e.item_id, quantity=e.quantity, position=i)
        for i, e in enumerate(body.items)
    )
    row.updated_at = ctx.clock.now()
    await ctx.session.commit()
    entries = _entries(row)
    chosen = choose_stores(catalog, entries)
    return build_grocery_list(
        _resolve(catalog, chosen, entries), row.month, row.updated_at, labels_of(chosen)
    )


async def comparison(ctx: Ctx) -> GroceryComparison:
    catalog = await load_catalog(ctx)
    row = await current_list_row(ctx)
    entries = _entries(row)
    chosen = choose_stores(catalog, entries)
    return build_comparison(_resolve(catalog, chosen, entries), row.month, labels_of(chosen))


async def plan_summary(ctx: Ctx) -> GroceryPlanSummary:
    return to_plan_summary(await comparison(ctx))
