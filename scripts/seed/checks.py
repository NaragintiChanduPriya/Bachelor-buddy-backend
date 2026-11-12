"""Consistency checks run against the database after a seed, and the row-count summary."""

from __future__ import annotations

from datetime import date

from scripts._pg import Conn

TABLES = (
    "areas", "tech_parks", "area_rent_averages", "food_listings", "menu_items",
    "delivery_platforms", "delivery_quotes", "stores", "grocery_items", "grocery_prices",
    "products", "product_prices", "price_history", "offers", "homes", "home_commutes",
    "users", "user_preferences", "user_cards", "budgets", "budget_categories", "expenses",
    "savings_snapshots", "recommendations", "notifications", "price_alerts", "grocery_lists",
    "grocery_list_items",
)  # fmt: skip


def row_counts(conn: Conn) -> dict[str, int]:
    counts = {}
    for table in TABLES:
        row = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()  # noqa: S608 - fixed names
        counts[table] = int(row[0]) if row else 0
    return counts


#: (description, SQL returning the number of violations)
CHECKS: tuple[tuple[str, str], ...] = (
    (
        "every listing has 6-23 menu items",
        "SELECT count(*) FROM food_listings l WHERE (SELECT count(*) FROM menu_items m "
        "WHERE m.listing_id = l.id) NOT BETWEEN 6 AND 23",
    ),
    (
        "listing price range matches its dishes",
        "SELECT count(*) FROM food_listings l JOIN LATERAL (SELECT min(price_paise) lo, "
        "max(price_paise) hi FROM menu_items m WHERE m.listing_id = l.id AND m.name NOT LIKE "
        "'Monthly%%' AND m.name NOT LIKE 'Weekly%%') d ON true "
        "WHERE d.lo <> l.price_min_paise OR d.hi <> l.price_max_paise",
    ),
    (
        "rents are within 25% of the area average",
        "SELECT count(*) FROM homes h JOIN area_rent_averages a ON a.area_id = h.area_id AND "
        "a.home_type = h.type WHERE h.rent_paise NOT BETWEEN a.average_rent_paise * 0.75 "
        "AND a.average_rent_paise * 1.25",
    ),
    (
        "every home has a commute to every tech park",
        "SELECT count(*) FROM homes h WHERE (SELECT count(*) FROM home_commutes c "
        "WHERE c.home_id = h.id) <> (SELECT count(*) FROM tech_parks)",
    ),
    (
        "price history has 180 consecutive days ending today for every listing",
        "SELECT count(*) FROM (SELECT product_id, platform, count(*) n, min(day) lo, max(day) hi "
        "FROM price_history GROUP BY product_id, platform) s "
        "WHERE n <> 180 OR hi - lo <> 179 OR hi <> %(today)s",
    ),
    (
        "today's platform price equals the last history point",
        "SELECT count(*) FROM product_prices p JOIN price_history h ON h.product_id = "
        "p.product_id AND h.platform = p.platform AND h.day = %(today)s "
        "WHERE h.price_paise <> p.price_paise",
    ),
    (
        "every grocery item is priced at all eight stores",
        "SELECT count(*) FROM grocery_items i WHERE (SELECT count(*) FROM grocery_prices p "
        "WHERE p.item_id = i.id) <> (SELECT count(*) FROM stores)",
    ),
    (
        "budget limits add up to the salary",
        "SELECT count(*) FROM budgets b WHERE b.salary_paise <> (SELECT sum(limit_paise) "
        "FROM budget_categories c WHERE c.budget_id = b.id)",
    ),
    (
        "every seeded user has a budget for every generated month",
        "SELECT count(*) FROM users u WHERE u.is_seeded AND (SELECT count(*) FROM budgets b "
        "WHERE b.user_id = u.id) <> 7",
    ),
    (
        "snapshots equal salary minus that month's spending",
        "SELECT count(*) FROM savings_snapshots s WHERE s.saved_paise <> GREATEST(0, "
        "s.salary_paise - (SELECT coalesce(sum(amount_paise), 0) FROM expenses e WHERE "
        "e.user_id = s.user_id AND to_char(timezone('Asia/Kolkata', e.spent_at), 'YYYY-MM') = "
        "s.month))",
    ),
    (
        "no expense is in the future",
        "SELECT count(*) FROM expenses WHERE spent_at > %(now)s",
    ),
)


def run_checks(conn: Conn, today: date, now: object, demo_day: bool) -> list[str]:
    """Descriptions of failed checks (empty when everything is consistent)."""
    failures = []
    params = {"today": today, "now": now}
    for description, query in CHECKS:
        row = conn.execute(query, params).fetchone()
        if row and int(row[0]) > 0:
            failures.append(f"{description}: {row[0]} violations")
    if demo_day:
        row = conn.execute(
            "SELECT sum(e.amount_paise) / 100 FROM expenses e JOIN users u ON u.id = e.user_id "
            "WHERE u.email = 'arjun@demo.com' AND e.category = 'food' "
            "AND to_char(timezone('Asia/Kolkata', e.spent_at), 'YYYY-MM') = %(month)s",
            {"month": today.strftime("%Y-%m")},
        ).fetchone()
        if not row or int(row[0] or 0) != 5250:
            failures.append(f"Arjun's food spend on the 15th should be ₹5,250, got {row}")
    return failures
