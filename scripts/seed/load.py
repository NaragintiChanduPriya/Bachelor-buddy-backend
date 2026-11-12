"""Writes a generated dataset into PostgreSQL in one transaction.

- Catalog tables are synced: rows are COPYed into a temp table, upserted by primary key, and
  rows the new dataset no longer has are deleted. IDs are deterministic, so real users' alerts
  and lists keep pointing at the same products and items.
- Seeded users (`users.is_seeded`) are deleted, which cascades to everything they own, and
  inserted again. Users who registered themselves are never touched.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from scripts._pg import Conn
from scripts.seed.catalog import Catalog
from scripts.seed.common import Table, paise
from scripts.seed.users import SeedUser

#: Parents before children.
CATALOG_ORDER = (
    "areas",
    "tech_parks",
    "area_rent_averages",
    "delivery_platforms",
    "food_listings",
    "menu_items",
    "delivery_quotes",
    "stores",
    "grocery_items",
    "grocery_prices",
    "products",
    "product_prices",
    "price_history",
    "offers",
    "homes",
    "home_commutes",
)


def _copy(conn: Conn, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
    count = 0
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns))
    )
    with conn.cursor() as cur, cur.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


def sync_table(conn: Conn, table: Table) -> None:
    temp = f"_sync_{table.name}"
    cols = sql.SQL(", ").join(map(sql.Identifier, table.columns))
    keys = sql.SQL(", ").join(map(sql.Identifier, table.keys))
    conn.execute(
        sql.SQL("CREATE TEMP TABLE {} (LIKE {} INCLUDING DEFAULTS) ON COMMIT DROP").format(
            sql.Identifier(temp), sql.Identifier(table.name)
        )
    )
    _copy(conn, temp, table.columns, table.rows)
    updates = [c for c in table.columns if c not in table.keys]
    conflict = (
        sql.SQL("DO UPDATE SET {}").format(
            sql.SQL(", ").join(
                sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(c), sql.Identifier(c))
                for c in updates
            )
        )
        if updates
        else sql.SQL("DO NOTHING")
    )
    conn.execute(
        sql.SQL("INSERT INTO {} ({}) SELECT {} FROM {} ON CONFLICT ({}) {}").format(
            sql.Identifier(table.name), cols, cols, sql.Identifier(temp), keys, conflict
        )
    )
    match = sql.SQL(" AND ").join(
        sql.SQL("t.{} = s.{}").format(sql.Identifier(k), sql.Identifier(k)) for k in table.keys
    )
    conn.execute(
        sql.SQL("DELETE FROM {} t WHERE NOT EXISTS (SELECT 1 FROM {} s WHERE {})").format(
            sql.Identifier(table.name), sql.Identifier(temp), match
        )
    )


def _insert_returning(
    conn: Conn,
    table: str,
    columns: Sequence[str],
    types: Sequence[str],
    rows: Sequence[Sequence[Any]],
    returning: Sequence[str],
) -> list[tuple[Any, ...]]:
    """Bulk insert with `unnest` in one round trip, returning generated keys."""
    if not rows:
        return []
    arrays = [list(column) for column in zip(*rows, strict=True)]
    statement = sql.SQL("INSERT INTO {} ({}) SELECT * FROM unnest({}) RETURNING {}").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.SQL("%s::" + t + "[]") for t in types),
        sql.SQL(", ").join(map(sql.Identifier, returning)),
    )
    return conn.execute(statement, arrays).fetchall()


def load_users(conn: Conn, users: Sequence[SeedUser], password_hash: str) -> None:
    conn.execute("DELETE FROM users WHERE is_seeded")
    ids = {
        email: user_id
        for user_id, email in _insert_returning(
            conn,
            "users",
            ("email", "password_hash", "name", "age", "occupation", "onboarded", "is_seeded", "joined_at"),
            ("text", "text", "text", "smallint", "text", "boolean", "boolean", "timestamptz"),
            [(u.email, password_hash, u.name, u.age, u.occupation, True, True, u.joined_at) for u in users],
            ("id", "email"),
        )
    }  # fmt: skip
    _copy(
        conn,
        "user_preferences",
        ("user_id", "salary_paise", "savings_goal_paise", "home_area_id", "office_area_id", "tech_park_id", "food_preference"),
        ((ids[u.email], paise(u.salary), paise(u.goal), u.home_area, u.office_area, u.tech_park, u.food_preference) for u in users),
    )  # fmt: skip
    _copy(
        conn,
        "user_cards",
        ("user_id", "card_id", "bank", "card_type", "label", "position"),
        (
            (ids[u.email], card_id, bank, kind, label, position)
            for u in users
            for position, (card_id, bank, kind, label) in enumerate(u.cards)
        ),
    )
    budget_rows = [(ids[u.email], month, paise(u.salary)) for u in users for month in u.budgets]
    budget_ids = {
        (user_id, month): budget_id
        for budget_id, user_id, month in _insert_returning(
            conn,
            "budgets",
            ("user_id", "month", "salary_paise"),
            ("integer", "text", "bigint"),
            budget_rows,
            ("id", "user_id", "month"),
        )
    }
    order = ("rent", "food", "groceries", "shopping", "travel", "bills", "misc", "savings")
    _copy(
        conn,
        "budget_categories",
        ("budget_id", "category", "limit_paise", "position"),
        (
            (
                budget_ids[(ids[u.email], month)],
                category,
                paise(limits[category]),
                order.index(category),
            )
            for u in users
            for month, limits in u.budgets.items()
            for category in order
            if category in limits
        ),
    )
    _copy(
        conn,
        "expenses",
        ("user_id", "category", "title", "note", "amount_paise", "merchant", "source", "spent_at", "created_at"),
        (
            (ids[u.email], e.category, e.title[:120], e.note, paise(e.amount), e.merchant, e.source, e.spent_at, e.spent_at)
            for u in users
            for e in u.expenses
        ),
    )  # fmt: skip
    _copy(
        conn,
        "savings_snapshots",
        ("user_id", "month", "saved_paise", "goal_paise", "salary_paise", "total_spent_paise"),
        (
            (ids[u.email], month, paise(saved), paise(goal), paise(salary), paise(spent))
            for u in users
            for month, saved, goal, salary, spent in u.snapshots
        ),
    )
    _copy(
        conn,
        "notifications",
        ("user_id", "kind", "agent", "title", "body", "link", "read", "created_at", "dedupe_key"),
        ((ids[u.email], *n) for u in users for n in u.notifications),
    )
    _copy(
        conn,
        "price_alerts",
        ("user_id", "product_id", "target_price_paise", "created_at", "last_notified_price_paise"),
        (
            (
                ids[u.email],
                product_id,
                paise(target),
                created,
                paise(notified) if notified else None,
            )
            for u in users
            for product_id, target, created, notified in u.alerts
        ),
    )
    _copy(
        conn,
        "recommendations",
        ("user_id", "agent", "title", "chosen_price_paise", "alternative_price_paise", "times", "accepted", "suggested_at", "followed_at"),
        (
            (ids[u.email], agent, title, paise(chosen), paise(alt), times, accepted, suggested, followed)
            for u in users
            for agent, title, chosen, alt, times, accepted, suggested, followed in u.recommendations
        ),
    )  # fmt: skip
    with_lists = [u for u in users if u.grocery_list]
    list_ids = {
        user_id: list_id
        for list_id, user_id in _insert_returning(
            conn,
            "grocery_lists",
            ("user_id", "month", "updated_at"),
            ("integer", "text", "timestamptz"),
            [
                (ids[u.email], u.grocery_list[0], u.grocery_list[1])
                for u in with_lists
                if u.grocery_list
            ],
            ("id", "user_id"),
        )
    }
    _copy(
        conn,
        "grocery_list_items",
        ("list_id", "item_id", "quantity", "position"),
        (
            (list_ids[ids[u.email]], item_id, quantity, position)
            for u in with_lists
            if u.grocery_list
            for position, (item_id, quantity) in enumerate(u.grocery_list[2])
        ),
    )


def load(
    conn: Conn,
    catalog: Catalog,
    users: Sequence[SeedUser],
    *,
    password_hash: str,
    seed_run: dict[str, Any],
) -> None:
    """Everything in one transaction: a failure leaves the database as it was."""
    with conn.transaction():
        for name in CATALOG_ORDER:
            sync_table(conn, catalog.tables[name])
        load_users(conn, users, password_hash)
        # Scheduled-job bookkeeping belongs to the old data; let jobs run again on the new.
        conn.execute("DELETE FROM job_runs")
        conn.execute(
            "INSERT INTO seed_runs (fingerprint, seed_value, anchor, volumes, row_counts) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                seed_run["fingerprint"],
                seed_run["seed_value"],
                seed_run["anchor"],
                Jsonb(seed_run["volumes"]),
                Jsonb(json.loads(json.dumps(seed_run.get("row_counts", {})))),
            ),
        )
