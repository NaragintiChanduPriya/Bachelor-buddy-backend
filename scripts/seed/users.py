"""User builders: the demo user Arjun (exact demo numbers) and synthetic users with patterned
spending, plus their budgets, snapshots, notifications, alerts, recommendations and lists."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from faker import Faker

from app.calc.budget import generate_limits
from app.core.clock import shift_month
from app.core.constants import CATEGORY_IDS
from app.core.money import format_inr, js_round
from scripts.seed import vocab
from scripts.seed.catalog import Catalog, ListingInfo
from scripts.seed.common import Anchor, Rng, rng_for, round_to
from scripts.seed.reference import AREAS, CARD_CHOICES, TECH_PARKS

DEMO_EMAIL = "arjun@demo.com"
#: Months of history before the current month (the savings chart shows six finished months).
PAST_MONTHS = 6
#: Arjun on the 15th: food at 70% of ₹7,500, ₹1,800 left of ₹2,500 shopping (₹25,020 total).
ARJUN_CURRENT = {
    "rent": 14000,
    "food": 5250,
    "groceries": 1680,
    "shopping": 700,
    "travel": 1130,
    "bills": 1340,
    "misc": 920,
}
#: What Arjun saved in each of the six finished months, oldest first (he improves as he
#: follows the agents' suggestions).
ARJUN_SAVED = (2100, 3400, 4600, 5800, 6900, 7600)
ARJUN_GROCERIES = (
    ("Sona masoori rice", 5), ("Toor dal", 1), ("Ragi flour", 1), ("Bombay rava", 1),
    ("Sunflower oil", 1), ("Coconut oil", 1), ("Filter coffee powder", 1), ("Sugar", 1),
    ("Fresh curd", 6), ("Idli & dosa batter", 3), ("Onion", 2), ("Tomato", 2), ("Potato", 1),
    ("Curry leaves", 2), ("Coriander leaves", 2), ("Yelakki bananas", 2), ("Sambar powder", 1),
    ("Marie biscuits", 2), ("Instant noodles", 1), ("Bath soap", 1), ("Toothpaste", 1),
    ("Dishwash liquid", 1),
)  # fmt: skip
OCCUPATIONS = (
    "Software Engineer", "QA Engineer", "Data Analyst", "Product Designer", "Sales Executive",
    "Customer Success Associate", "Accountant", "Content Writer", "Mechanical Engineer",
    "Business Analyst", "DevOps Engineer", "HR Associate", "Support Engineer",
)  # fmt: skip
#: Spend as a share of each limit, by spending profile.
PROFILES = {"frugal": (0.62, 0.9), "normal": (0.85, 1.04), "overspender": (1.0, 1.3)}


@dataclass
class SeedExpense:
    category: str
    title: str
    amount: int
    merchant: str | None
    source: str
    spent_at: datetime
    note: str | None = None


@dataclass
class SeedUser:
    email: str
    name: str
    age: int
    occupation: str
    joined_at: datetime
    salary: int
    goal: int
    home_area: str
    office_area: str
    tech_park: str | None
    food_preference: str
    cards: list[tuple[str, str, str, str]]
    budgets: dict[str, dict[str, int]] = field(default_factory=dict)
    expenses: list[SeedExpense] = field(default_factory=list)
    snapshots: list[tuple[str, int, int, int, int]] = field(default_factory=list)
    notifications: list[tuple[str, str, str, str, str | None, bool, datetime, str]] = field(
        default_factory=list
    )
    alerts: list[tuple[str, int, datetime, int | None]] = field(default_factory=list)
    recommendations: list[tuple[str, str, int, int, int, bool, datetime, datetime | None]] = field(
        default_factory=list
    )
    grocery_list: tuple[str, datetime, list[tuple[str, int]]] | None = None


# ------------------------------------------------------------------ expenses


def _month_days(month: str) -> int:
    year, number = (int(p) for p in month.split("-"))
    return calendar.monthrange(year, number)[1]


def _day(month: str, day: int) -> date:
    year, number = (int(p) for p in month.split("-"))
    return date(year, number, day)


class MonthWriter:
    """Writes one month of expenses whose category totals hit exact targets."""

    def __init__(self, rng: Rng, anchor: Anchor, month: str, last_day: int) -> None:
        self.rng, self.anchor, self.month, self.last_day = rng, anchor, month, last_day
        self.expenses: list[SeedExpense] = []

    def when(self, day: int, hour: int, minute: int = 0) -> datetime:
        instant = self.anchor.at(_day(self.month, max(1, min(day, self.last_day))), hour, minute)
        # Never in the future, even on the anchor day itself.
        latest = self.anchor.now - timedelta(minutes=5)
        return (
            instant if instant <= latest else latest - timedelta(minutes=self.rng.randint(1, 600))
        )

    def weekdays(self) -> list[int]:
        return [d for d in range(1, self.last_day + 1) if _day(self.month, d).weekday() < 5]

    def weekends(self) -> list[int]:
        return [d for d in range(1, self.last_day + 1) if _day(self.month, d).weekday() >= 5]

    def add(self, expense: SeedExpense) -> None:
        self.expenses.append(expense)

    def fill(
        self,
        category: str,
        target: int,
        draw: object,
    ) -> None:
        """Draw expenses (via `draw()`) until the category reaches `target` exactly."""
        if target <= 0:
            return
        items: list[SeedExpense] = []
        total = 0
        for _ in range(400):
            if total >= target:
                break
            expense: SeedExpense = draw()  # type: ignore[operator]
            items.append(expense)
            total += expense.amount
        overshoot = total - target
        while overshoot > 0 and items:
            last = items[-1]
            if last.amount - overshoot >= max(10, last.amount // 3):
                last.amount -= overshoot
                overshoot = 0
            else:
                overshoot -= last.amount
                items.pop()
        if overshoot < 0 and items:  # a dropped item left us short; top up the largest
            max(items, key=lambda e: e.amount).amount -= overshoot
        if not items:
            items = [draw()]  # type: ignore[operator]
            items[0].amount = target
        self.expenses.extend(items)


def _template(
    rng: Rng, category: str, *, sources: tuple[str, ...] | None = None
) -> vocab.ExpenseTemplate:
    options = [
        t for t in vocab.EXPENSE_TEMPLATES[category] if sources is None or t.source in sources
    ]
    return rng.choice(options)


def _write_month(
    writer: MonthWriter,
    targets: dict[str, int],
    *,
    office_food: list[ListingInfo],
    home_food: list[ListingInfo],
    month_label: str,
) -> None:
    rng = writer.rng
    if targets.get("rent"):
        writer.add(
            SeedExpense(
                "rent", f"Rent - {month_label}", targets["rent"], None, "recurring",
                writer.when(rng.randint(1, 3), 9, rng.randint(0, 59)),
            )
        )  # fmt: skip

    def text(template: vocab.ExpenseTemplate, eatery: str) -> tuple[str, str | None]:
        title = template.title.replace("{eatery}", eatery).replace("{month}", month_label)
        merchant = template.merchant.replace("{eatery}", eatery) if template.merchant else None
        return title, merchant

    weekdays, weekends = writer.weekdays() or [1], writer.weekends() or [1]

    def draw_food() -> SeedExpense:
        if rng.chance(0.18):
            template = _template(rng, "food", sources=("delivery",))
            title, merchant = text(template, "")
            day, hour = rng.choice(weekdays + weekends), rng.choice((20, 21, 22))
            source = "delivery"
        else:
            template = _template(rng, "food", sources=("manual",))
            weekend = rng.chance(0.25)
            pool = home_food if weekend else office_food
            eatery = rng.choice(pool).name if pool else "a local mess"
            title, merchant = text(template, eatery)
            day = rng.choice(weekends if weekend else weekdays)
            hour, source = (
                (8 if "Breakfast" in template.title else 13 if "Lunch" in template.title else 20),
                "manual",
            )
        amount = rng.randint(template.min_amount, template.max_amount)
        return SeedExpense(
            "food", title, amount, merchant, source, writer.when(day, hour, rng.randint(0, 59))
        )

    def generic(category: str) -> object:
        def draw() -> SeedExpense:
            template = _template(rng, category)
            title, merchant = text(template, "")
            amount = rng.randint(template.min_amount, template.max_amount)
            day = rng.randint(1, writer.last_day)
            if template.source in ("recurring", "subscription"):
                day = rng.randint(1, min(10, writer.last_day))
            hour = rng.choice((9, 11, 13, 17, 19, 21))
            return SeedExpense(
                category,
                title,
                amount,
                merchant,
                template.source,
                writer.when(day, hour, rng.randint(0, 59)),
            )

        return draw

    writer.fill("food", targets.get("food", 0), draw_food)
    for category in ("groceries", "shopping", "travel", "bills", "misc"):
        writer.fill(category, targets.get(category, 0), generic(category))


# ------------------------------------------------------------------ users


def _cards(rng: Rng, count: int) -> list[tuple[str, str, str, str]]:
    picked = rng.sample(CARD_CHOICES, k=count)
    return [
        (card_id, bank, kind, f"{bank} {'Credit' if kind == 'credit' else 'Debit'} Card")
        for card_id, bank, kind in sorted(picked)
    ]


def _park_for(office_area: str) -> str | None:
    return next((p.id for p in TECH_PARKS if p.area_id == office_area), None)


def _months(anchor: Anchor) -> list[str]:
    return [shift_month(anchor.month, -offset) for offset in range(PAST_MONTHS, -1, -1)]


def _month_label(month: str) -> str:
    year, number = month.split("-")
    return f"{calendar.month_name[int(number)]} {year}"


def _partial_targets(full: dict[str, int], day: int, days: int) -> dict[str, int]:
    """Targets for the current month so far: rent lands on the 1st, bills by the 10th, the rest
    accrues day by day."""
    result = {}
    for category, amount in full.items():
        if category == "rent":
            result[category] = amount
        elif category == "bills":
            result[category] = js_round(amount * min(1.0, day / 10))
        else:
            result[category] = js_round(amount * day / days)
    return result


def _food_pools(catalog: Catalog, user: SeedUser) -> tuple[list[ListingInfo], list[ListingInfo]]:
    def pool(area: str) -> list[ListingInfo]:
        listings = [
            info
            for info in catalog.listings
            if info.area_id == area and (info.veg or user.food_preference != "veg")
        ]
        return sorted(listings, key=lambda i: i.avg_meal_price)[:8]

    return pool(user.office_area), pool(user.home_area)


def build_arjun(catalog: Catalog, seed: int, anchor: Anchor) -> SeedUser:
    user = SeedUser(
        email=DEMO_EMAIL,
        name="Arjun",
        age=24,
        occupation="Software Engineer",
        joined_at=anchor.days_ago(200, 10, 0),
        salary=40000,
        goal=8000,
        home_area="area_hsr",
        office_area="area_bellandur",
        tech_park="park_orbit",
        food_preference="veg",
        cards=[
            ("card_hdfc_cc", "HDFC", "credit", "HDFC Credit Card"),
            ("card_sbi_dc", "SBI", "debit", "SBI Debit Card"),
            ("card_icici_cc", "ICICI", "credit", "ICICI Credit Card"),
            ("card_axis_dc", "Axis", "debit", "Axis Debit Card"),
        ],
    )
    limits = generate_limits(user.salary, user.goal)
    office_food, home_food = _food_pools(catalog, user)
    months = _months(anchor)
    for index, month in enumerate(months):
        user.budgets[month] = dict(limits)
        days = _month_days(month)
        current = month == anchor.month
        last_day = anchor.today.day if current else days
        writer = MonthWriter(rng_for(seed, "expenses", "arjun", month), anchor, month, last_day)
        if current:
            scale = min(1.0, last_day / 15)
            targets = {
                c: (amount if c == "rent" else js_round(amount * scale))
                for c, amount in ARJUN_CURRENT.items()
            }
        else:
            saved = ARJUN_SAVED[index]
            spend = user.salary - saved
            remaining = spend - limits["rent"] - 1450
            shares = {
                "food": 0.5 - index * 0.015,
                "groceries": 0.13,
                "shopping": 0.15,
                "travel": 0.11,
            }
            targets = {"rent": limits["rent"], "bills": 1450}
            for category, share in shares.items():
                targets[category] = js_round(remaining * share)
            targets["misc"] = spend - sum(targets.values())
            user.snapshots.append((month, saved, user.goal, user.salary, spend))
        _write_month(
            writer,
            targets,
            office_food=office_food,
            home_food=home_food,
            month_label=_month_label(month),
        )
        user.expenses.extend(writer.expenses)

    # Mark the food deliveries that the Food agent will talk about.
    _arjun_extras(user, catalog, anchor, office_food)
    return user


def _arjun_extras(
    user: SeedUser, catalog: Catalog, anchor: Anchor, office_food: list[ListingInfo]
) -> None:
    mess = next((i for i in office_food if i.kind == "mess"), office_food[0])
    shoes = [p for p in catalog.products if p.category == "formalShoes"]
    tracked = shoes[0]
    others = [p for p in catalog.products if p.category in ("backpacks", "earphones", "watches")]
    alert_products = [tracked, others[2], others[10], others[21]]
    user.alerts = [
        (tracked.id, tracked.lowest_price + 150, anchor.days_ago(10, 21, 45), None),
        (
            alert_products[1].id,
            round_to(alert_products[1].lowest_price * 0.85, 10),
            anchor.days_ago(18, 20, 10),
            None,
        ),
        (
            alert_products[2].id,
            round_to(alert_products[2].lowest_price * 0.9, 10),
            anchor.days_ago(25, 19, 30),
            None,
        ),
        (
            alert_products[3].id,
            round_to(alert_products[3].lowest_price * 0.8, 10),
            anchor.days_ago(40, 22, 5),
            None,
        ),
    ]
    waited = next(p for p in catalog.products if p.category == "jeans")
    user.recommendations = [
        ("food", f"Switched weekday lunch from delivery to {mess.name}", 110, 190, 14, True, anchor.days_ago(16), anchor.days_ago(12)),
        ("grocery", "One monthly grocery stock-up instead of small quick-commerce orders", 2400, 3220, 1, True, anchor.days_ago(11), anchor.days_ago(9)),
        ("shopping", f"Waited for the sale on the {waited.brand} {waited.name}", waited.lowest_price, waited.lowest_price + 700, 1, True, anchor.days_ago(20), anchor.days_ago(6)),
        ("deals", "Paid with the HDFC credit card offer on ShopNest", 2250, 2499, 1, True, anchor.days_ago(5), anchor.days_ago(4)),
        ("food", "Took a monthly tiffin plan for weekday dinners", 95, 165, 20, True, anchor.days_ago(52), anchor.days_ago(48)),
        ("budget", "Took the metro to work instead of a cab", 40, 210, 18, True, anchor.days_ago(70), anchor.days_ago(66)),
        ("grocery", "Bought rice and dal in bulk packs", 690, 840, 1, True, anchor.days_ago(85), anchor.days_ago(83)),
        ("home", "Move to a cheaper PG in Marathahalli", 8500, 14000, 1, False, anchor.days_ago(3), None),
    ]  # fmt: skip
    hdfc = "10% off up to ₹500 on ShopNest orders above ₹1,500 with your HDFC credit card."
    last_month = _month_label(shift_month(anchor.month, -1))
    user.notifications = [
        ("mealSuggestion", "food", f"Lunch near your office for {format_inr(mess.avg_meal_price)}", f"{mess.name} in Bellandur is serving meals at about {format_inr(mess.avg_meal_price)}. Delivery for the same meal would cost nearly double.", "/food?near=office&maxPrice=150", False, anchor.now - timedelta(minutes=25), "seed:meal"),
        ("budgetWarning", "budget", "Food budget is 70% used", "You have spent ₹5,250 of ₹7,500 with half the month left. Around ₹150 a day keeps you inside the limit.", "/budget", False, anchor.now - timedelta(hours=3), "seed:food70"),
        ("priceDrop", "shopping", "Price drop on the formal shoes you tracked", f"The {tracked.brand} {tracked.name} is now {format_inr(tracked.lowest_price)} — below your alert price.", f"/shop/{tracked.id}", False, anchor.now - timedelta(hours=8), "seed:drop"),
        ("offerExpiring", "deals", "HDFC card offer ends in 2 days", hdfc, "/deals", False, anchor.now - timedelta(hours=20), "seed:offer"),
        ("groceryReminder", "grocery", "Time to reorder rice and dal", "Your monthly stock-up is due. Buying it in one order instead of quick-commerce top-ups saves about ₹400.", "/groceries", True, anchor.days_ago(2, 10, 0), "seed:grocery"),
        ("savingsReport", "savings", f"You saved ₹7,600 in {last_month}", "That is 95% of your ₹8,000 goal, and your best month so far.", "/savings", True, anchor.days_ago(15, 21, 0), "seed:report"),
        ("tip", "concierge", "Ask Buddy before you order in", "Ask me whether delivery or eating out is cheaper for any dish. I will show every fee.", "/chat", True, anchor.days_ago(3, 9, 30), "seed:tip1"),
        ("tip", "home", "Your rent is above the area average", "PGs in Marathahalli with food included start around ₹8,500, about ₹5,500 less than you pay now.", "/homes?area=area_marathahalli&type=pg", True, anchor.days_ago(3, 18, 0), "seed:tip2"),
        ("budgetWarning", "budget", "Shopping budget: ₹1,800 left", "You have used 28% of your shopping budget. Formal shoes for Friday fit inside it.", "/budget", True, anchor.days_ago(4, 20, 0), "seed:shop"),
        ("mealSuggestion", "food", "Tiffin plans near home from ₹95 a meal", "A monthly lunch plan in HSR Layout works out cheaper than any delivery app for weekday meals.", "/food?type=tiffin", True, anchor.days_ago(5, 12, 15), "seed:tiffin"),
        ("priceDrop", "shopping", "Earphones you viewed are 18% off", "The price is the lowest in 90 days on one platform. Prices like this usually last a few days.", "/shop?category=earphones", True, anchor.days_ago(7, 11, 0), "seed:ear"),
        ("tip", "savings", "Halfway there this month", "You are halfway through the month. The food budget is the one to watch.", "/savings", True, anchor.days_ago(1, 9, 0), "seed:tip3"),
        ("offerExpiring", "deals", "Grocery cashback ends tomorrow", "Your SBI debit card gets cashback on a StockUp Wholesale order this week.", "/deals", True, anchor.days_ago(6, 18, 30), "seed:offer2"),
    ]  # fmt: skip
    user.grocery_list = (
        anchor.month,
        anchor.days_ago(3, 19, 0),
        [(catalog.grocery_ids[name], qty) for name, qty in ARJUN_GROCERIES],
    )


def build_synthetic(
    catalog: Catalog, seed: int, anchor: Anchor, number: int, fake: Faker
) -> SeedUser:
    rng = rng_for(seed, "user", number)
    fake.seed_instance(f"{seed}:user:{number}")
    first, last = fake.first_name(), fake.last_name()
    salary = rng.money(22000, 95000, 1000)
    goal = round_to(salary * rng.uniform(0.05, 0.25), 500)
    office = rng.choice([p.area_id for p in TECH_PARKS])
    home = rng.choice([a.id for a in AREAS])
    user = SeedUser(
        email=f"{first}.{last}{number}@example.com".lower().replace(" ", ""),
        name=f"{first} {last}",
        age=rng.randint(21, 34),
        occupation=rng.choice(OCCUPATIONS),
        joined_at=anchor.days_ago(rng.randint(200, 280), 10, 0),
        salary=salary,
        goal=goal,
        home_area=home,
        office_area=office,
        tech_park=_park_for(office),
        food_preference=rng.choices(("veg", "nonVeg", "eggetarian", "vegan"), (45, 40, 10, 5))[0],
        cards=_cards(rng, rng.randint(1, 3)),
    )
    profile = rng.choices(tuple(PROFILES), (30, 50, 20))[0]
    limits = generate_limits(salary, goal)
    office_food, home_food = _food_pools(catalog, user)
    for month in _months(anchor):
        user.budgets[month] = dict(limits)
        days = _month_days(month)
        current = month == anchor.month
        month_rng = rng_for(seed, "expenses", number, month)
        low, high = PROFILES[profile]
        full: dict[str, int] = {
            c: (limits[c] if c == "rent" else js_round(limits[c] * month_rng.uniform(low, high)))
            for c in CATEGORY_IDS
            if c != "savings"
        }
        targets = _partial_targets(full, anchor.today.day, days) if current else full
        writer = MonthWriter(month_rng, anchor, month, anchor.today.day if current else days)
        _write_month(
            writer,
            targets,
            office_food=office_food,
            home_food=home_food,
            month_label=_month_label(month),
        )
        user.expenses.extend(writer.expenses)
        if not current:
            spent = sum(targets.values())
            user.snapshots.append((month, max(0, salary - spent), goal, salary, spent))

    kinds = (
        ("tip", "concierge", "Ask Buddy about cheaper lunches", "Ask me for meals near your office under any budget.", "/chat"),
        ("budgetWarning", "budget", "Food budget is getting close", "You have used most of this month's food budget.", "/budget"),
        ("groceryReminder", "grocery", "Monthly grocery stock-up", "One bulk order this month will cost less than several small ones.", "/groceries"),
        ("offerExpiring", "deals", "A card offer ends soon", "One of the offers on your saved cards ends this week.", "/deals"),
    )  # fmt: skip
    for index, (kind, agent, title, body, link) in enumerate(
        rng.sample(kinds, k=rng.randint(2, 4))
    ):
        user.notifications.append(
            (
                kind,
                agent,
                title,
                body,
                link,
                rng.chance(0.6),
                anchor.days_ago(rng.randint(0, 12), rng.randint(8, 21)),
                f"seed:{index}",
            )
        )
    if rng.chance(0.3):
        for product in rng.sample(catalog.products, k=rng.randint(1, 2)):
            user.alerts.append(
                (
                    product.id,
                    round_to(product.lowest_price * 0.85, 10),
                    anchor.days_ago(rng.randint(3, 40), 20),
                    None,
                )
            )
    if rng.chance(0.6):
        names = list(catalog.grocery_ids)
        picked = rng.sample(names, k=rng.randint(8, 18))
        user.grocery_list = (
            anchor.month,
            anchor.days_ago(rng.randint(1, 10), 19),
            [(catalog.grocery_ids[n], rng.randint(1, 3)) for n in picked],
        )
    return user


def build_users(
    catalog: Catalog, seed: int, anchor: Anchor, count: int, *, include_demo: bool = True
) -> list[SeedUser]:
    """The demo user (optional) plus `count` synthetic users."""
    fake = Faker("en_IN")
    users = [build_arjun(catalog, seed, anchor)] if include_demo else []
    used = {DEMO_EMAIL}
    for number in range(1, count + 1):
        user = build_synthetic(catalog, seed, anchor, number, fake)
        if user.email in used:  # astronomically unlikely, but keep emails unique
            user.email = f"user{number}@example.com"
        used.add(user.email)
        users.append(user)
    return users
