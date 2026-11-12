"""Rules-mode answers about the signed-in user: their profile and places, spending by category,
recent and biggest expenses, logging an expense they asked for, alerts and price alerts, and
small talk. Every fact comes from the database; nothing is invented."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select

from app.agents.concierge import AgentResult
from app.agents.evidence import CardRef, Evidence
from app.agents.reply import build_result, join_words
from app.agents.tools import PERIOD_LABELS, expense_window
from app.core.clock import month_bounds
from app.core.constants import CATEGORY_LABELS
from app.core.errors import AppError
from app.core.money import format_inr
from app.db.models import Expense
from app.schemas.budget import BudgetOut
from app.schemas.expense import CreateExpenseRequest
from app.services import expenses as expense_service
from app.services import notifications as notification_service
from app.services import products as product_service
from app.services.context import Ctx

FOOD_PREFERENCES = {
    "veg": "vegetarian",
    "nonVeg": "non-vegetarian",
    "eggetarian": "eggetarian",
    "vegan": "vegan",
}

#: Words that name a budget category, checked in this order (food last: it is the broadest).
CATEGORY_PATTERNS = (
    ("rent", r"\brent\b|\bpg\b|\bdeposit\b|\bhouse ?rent\b"),
    ("groceries", r"\bgrocer(y|ies)\b|\bration\b|\bvegetables?\b|\bmilk\b|\bkirana\b"),
    ("travel", r"\btravel\b|\btransport\b|\bcommute\b|\bcab\b|\btaxi\b|\bauto\b|\bmetro\b|\bbus\b|\bfuel\b|\bpetrol\b|\btrain\b|\bflight\b|\bbike\b|\brapido\b|\buber\b|\bola\b"),
    ("bills", r"\bbills?\b|\belectricity\b|\bpower\b|\bwi-?fi\b|\binternet\b|\bbroadband\b|\brecharge\b|\bmobile\b|\bphone\b|\bgas\b|\bwater\b|\bsubscriptions?\b"),
    ("shopping", r"\bshopping\b|\bclothes\b|\bshoes?\b|\bshirts?\b|\bjeans\b|\bbag\b|\bwatch\b|\bearphones?\b|\bgadgets?\b"),
    ("misc", r"\bmisc\b|\bother\b|\bentertainment\b|\bmovies?\b|\bgym\b|\bparty\b|\bgifts?\b|\blaundry\b|\bhaircut\b|\bmedicines?\b"),
    ("savings", r"\bsavings?\b"),
    ("food", r"\bfood\b|\blunch\b|\bdinner\b|\bbreakfast\b|\bmeals?\b|\bsnacks?\b|\bcoffee\b|\btea\b|\bchai\b|\bdosa\b|\bbiryani\b|\bswiggy\b|\bzomato\b|\bhotel\b|\brestaurant\b|\bmess\b|\btiffin\b|\bdarshini\b"),
)  # fmt: skip


def category_in(text: str) -> str | None:
    lower = text.lower()
    return next((c for c, pattern in CATEGORY_PATTERNS if re.search(pattern, lower)), None)


def _date(instant: datetime, ctx: Ctx) -> str:
    local = instant.astimezone(ctx.clock.zone)
    return f"{local.day} {local:%b}"


# ------------------------------------------------------------------ profile


async def profile(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    """Intent: profile. Answers exactly what was asked, or the whole profile."""
    text = message.lower()
    user, prefs = ctx.user, ctx.prefs
    home = prefs.home_area.name if prefs.home_area else None
    office = prefs.office_area.name if prefs.office_area else None
    park = prefs.tech_park.name if prefs.tech_park else None
    cards = [card.label for card in user.cards]
    preference = prefs.food_preference or ""
    food_label = FOOD_PREFERENCES.get(preference, preference or "not set")

    def asked(pattern: str) -> bool:
        return re.search(pattern, text) is not None

    at_park = f" at {park}" if park else ""
    if home and office and home == office:
        places = f"You live and work in {home}{at_park}."
    elif home and office:
        places = f"You live in {home} and work in {office}{at_park}."
    else:
        places = "You haven't set your home and office areas yet."
    job = f"{'an' if user.occupation[:1].lower() in 'aeiou' else 'a'} {user.occupation}"
    card_text = (
        f"You have saved {len(cards)} card{'s' if len(cards) != 1 else ''}: {join_words(cards)}."
        if cards
        else "You haven't saved any cards yet; add them in Settings to see the offers you can use."
    )
    joined = user.joined_at.astimezone(ctx.clock.zone)
    facts: list[str] = []
    if asked(r"\b(location|address|areas?|places?|live|living|stay|staying|home|based)\b"):
        facts.append(places)
    elif asked(r"\b(office|work|workplace|tech ?park|company)\b"):
        facts.append(
            f"You work in {office}" + (f", at {park}" if park else "") + "."
            if office
            else "You haven't set your office area yet."
        )
    if asked(r"\b(salary|income|earn|earning|earnings|pay)\b"):
        facts.append(f"Your monthly salary is {format_inr(prefs.salary)}.")
    if asked(r"\b(goal|target)\b"):
        facts.append(f"Your savings goal is {format_inr(prefs.savings_goal)} a month.")
    if asked(r"\b(preference|diet|veg|vegetarian|vegan|non-?veg|eggetarian)\b"):
        facts.append(
            f"Your food preference is {food_label}, so I only suggest places and dishes that fit."
        )
    if asked(r"\bcards?\b"):
        facts.append(card_text)
    if asked(r"\bname\b|\bwho am i\b"):
        facts.append(f"You are {user.name}.")
    if asked(r"\b(e-?mail|mail|login)\b"):
        facts.append(f"Your account email is {user.email}.")
    if asked(r"\bage\b|\bhow old\b"):
        facts.append(f"You are {user.age}.")
    if asked(r"\b(occupation|job|profession|do for a living|work as)\b"):
        facts.append(f"You work as {job}.")
    if asked(r"\b(joined|member since|signed up)\b"):
        facts.append(f"You joined BachelorBuddy on {joined.day} {joined:%B %Y}.")
    whole = asked(r"\b(profile|details|about me|myself|who am i|account|everything|info)\b")
    if not facts or whole:
        facts = [
            f"You are {user.name}, {user.age}, working as {job} ({user.email}).",
            places,
            f"Your salary is {format_inr(prefs.salary)} a month and your savings goal is "
            f"{format_inr(prefs.savings_goal)}.",
            f"Food: {food_label}.",
            card_text,
        ]
    text_out = " ".join(dict.fromkeys(facts)) + " You can change any of this in Settings."
    return build_result(
        ev, text_out, [], (), ("Reading your profile…",),
        ("Show places to eat near me, cheapest first", "Show PGs near my office", "What is left in my budget?"),
    )  # fmt: skip


# ------------------------------------------------------------------ spending


async def spend_on_category(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    """Intent: spendOnCategory. Any category other than food (which has its own answer)."""
    category_id = category_in(message) or "misc"
    category = next(c for c in budget.categories if c.id == category_id)
    label = CATEGORY_LABELS.get(category_id, category.label).lower()
    start, end = month_bounds(budget.month, ctx.clock.zone)
    biggest = await ctx.session.scalar(
        select(Expense)
        .where(
            Expense.user_id == ctx.user.id,
            Expense.category == category_id,
            Expense.spent_at >= start,
            Expense.spent_at < end,
        )
        .order_by(Expense.amount.desc(), Expense.id)
        .limit(1)
    )
    if category.spent == 0:
        text = (
            f"You haven't spent anything on {label} this month. Your {label} budget is "
            f"{format_inr(category.limit)}."
        )
    else:
        over = category.remaining < 0
        text = (
            f"You have spent {format_inr(category.spent)} on {label} this month — "
            f"{category.percent_used}% of your {format_inr(category.limit)} budget, "
            + (
                f"which is {format_inr(-category.remaining)} over."
                if over
                else f"with {format_inr(category.remaining)} left."
            )
        )
        if biggest is not None:
            text += (
                f" The biggest was {biggest.title} at {format_inr(biggest.amount)} on "
                f"{_date(biggest.spent_at, ctx)}."
            )
    return build_result(
        ev, text, [CardRef(type="budgetSummary", categories=[category_id])], ("budget",),
        (f"Adding up this month's {label} expenses…", "Comparing against your budget…"),
        ("Show my recent expenses", "Where is my money going?", "What is left in my budget?"),
    )  # fmt: skip


@dataclass(frozen=True)
class Window:
    label: str
    start: datetime
    end: datetime


def _window(ctx: Ctx, text: str) -> Window:
    """The period a message talks about, shared with the llm-mode expenses tool."""
    period = (
        "yesterday" if re.search(r"\byesterday\b", text)
        else "today" if re.search(r"\btoday\b", text)
        else "week" if re.search(r"\bweek\b", text)
        else "lastMonth" if re.search(r"\b(last|previous) month\b", text)
        else "month"
    )  # fmt: skip
    start, end = expense_window(ctx, period)
    return Window(PERIOD_LABELS[period], start, end)


async def recent_expenses(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    """Intent: expenses. The latest (or biggest) expenses in a time window and category."""
    text = message.lower()
    category_id = category_in(text)
    window = _window(ctx, text)
    biggest = re.search(r"\b(biggest|largest|highest|most expensive|top|costliest)\b", text)
    conditions = [
        Expense.user_id == ctx.user.id,
        Expense.spent_at >= window.start,
        Expense.spent_at < window.end,
    ]
    if category_id:
        conditions.append(Expense.category == category_id)
    count, total = (
        await ctx.session.execute(
            select(func.count(), func.coalesce(func.sum(Expense.amount), 0)).where(*conditions)
        )
    ).one()
    order = (
        (Expense.amount.desc(), Expense.spent_at.desc())
        if biggest
        else (Expense.spent_at.desc(), Expense.id.desc())
    )
    rows = list(
        await ctx.session.scalars(select(Expense).where(*conditions).order_by(*order).limit(6))
    )
    where = f" on {CATEGORY_LABELS.get(category_id, category_id).lower()}" if category_id else ""
    if not rows:
        text_out = (
            f"You haven't logged any expenses{where} {window.label}. Tell me what you spent, "
            'like "I spent ₹120 on lunch", and I will log it.'
        )
    else:
        lines = [
            f"{n}. {e.title} — {format_inr(e.amount)}, {CATEGORY_LABELS.get(e.category, e.category).lower()}, "
            f"{_date(e.spent_at, ctx)}" + (f" at {e.merchant}" if e.merchant else "")
            for n, e in enumerate(rows, 1)
        ]
        kind = "biggest" if biggest else "latest"
        text_out = (
            f"Your {kind} expenses{where} {window.label}:\n" + "\n".join(lines)
            + f"\n\n{count} expense{'s' if count != 1 else ''} in all, {format_inr(int(total))}."
        )  # fmt: skip
    return build_result(
        ev, text_out, [], ("budget",), ("Reading your expenses…",),
        ("Where is my money going?", "What is left in my budget?", "How much did I spend on food this month?"),
    )  # fmt: skip


# ------------------------------------------------------------------ logging an expense

#: "log 200 for lunch", "add expense ₹150 auto", "I spent 90 on chai", "paid 1200 for wifi".
LOG_COMMAND = re.compile(
    r"^\s*(?:please\s+)?(?:log|add|record|note|track|save|enter)\b|^\s*(?:i\s+)?(?:just\s+)?(?:spent|paid)\b",
    re.IGNORECASE,
)
AMOUNT = re.compile(r"(?:₹|\brs\.?\s*|\binr\s*)?(\d[\d,]*(?:\.\d+)?)\s*(k\b)?", re.IGNORECASE)


@dataclass(frozen=True)
class ExpenseLog:
    amount: int
    title: str
    category: str


def parse_expense_log(message: str) -> ExpenseLog | None:
    """A request to record an expense, or None. Questions never count ("how much did I spend")."""
    text = message.strip()
    lower = text.lower()
    if "?" in text or not LOG_COMMAND.search(text):
        return None
    if re.match(r"^\s*(how|what|when|where|why|did|do|does|can|could|should|show|list)\b", lower):
        return None
    match = AMOUNT.search(text)
    if match is None:
        return None
    amount = round(float(match.group(1).replace(",", "")) * (1000 if match.group(2) else 1))
    if amount <= 0:
        return None
    after = re.search(r"\b(?:on|for|at)\s+(.+)$", text[match.end() :], re.IGNORECASE)
    if after:
        title = after.group(1)
    else:
        title = re.sub(
            r"^\s*(?:please\s+)?(?:log|add|record|note|track|save|enter|i\s+)?(?:\s*just)?"
            r"(?:\s*(?:spent|paid|an?|my|expense|expenses|of))*\s*",
            "",
            (text[: match.start()] + " " + text[match.end() :]).strip(),
            flags=re.IGNORECASE,
        )
    title = re.sub(r"\s+", " ", title).strip(" .,!-") or ""
    category = category_in(title or text) or "misc"
    if not title:
        title = CATEGORY_LABELS.get(category, "Expense")
    return ExpenseLog(amount=amount, title=title[:1].upper() + title[1:120], category=category)


async def log_expense(ctx: Ctx, ev: Evidence, entry: ExpenseLog) -> AgentResult:
    try:
        created = await expense_service.create_expense(
            ctx,
            CreateExpenseRequest(category=entry.category, title=entry.title, amount=entry.amount),
        )
    except (AppError, ValueError) as exc:
        message = getattr(exc, "message", None) or "That amount doesn't look right."
        return build_result(
            ev, f"I couldn't log that: {message}", [], ("budget",), ("Checking the expense…",),
            ("Show my recent expenses", "What is left in my budget?"),
        )  # fmt: skip
    category = created.category
    label = category.label.lower()
    left = (
        f"You have {format_inr(category.remaining)} left in {label} this month."
        if category.remaining >= 0
        else f"That puts you {format_inr(-category.remaining)} over your {label} budget this month."
    )
    text = f"Done — I logged {format_inr(entry.amount)} for {entry.title} under {label}. {left}"
    return build_result(
        ev, text, [CardRef(type="budgetSummary", categories=[category.id])], ("budget",),
        ("Logging your expense…", "Updating your budget…"),
        ("Show my recent expenses", "What is left in my budget?", "Where is my money going?"),
    )  # fmt: skip


# ------------------------------------------------------------------ alerts


async def alerts(ctx: Ctx, ev: Evidence, message: str, budget: BudgetOut) -> AgentResult:
    """Intent: alerts. Price alerts when the message is about prices, otherwise notifications."""
    if re.search(r"\bprice\b|\bprices\b|\bdrop\b|\btarget\b", message.lower()):
        rows = await product_service.alerts(ctx)
        if not rows:
            text = (
                "You have no price alerts. Open any product in Shop and set a target price; "
                "I will tell you when it drops to it."
            )
        else:
            lines = [
                f"{n}. {a.product_name}: now {format_inr(a.current_price)}, your target "
                f"{format_inr(a.target_price)}"
                + (
                    " — reached, buy now!"
                    if a.triggered
                    else f" ({format_inr(a.gap_to_target)} to go)"
                )
                for n, a in enumerate(rows[:6], 1)
            ]
            text = (
                f"You are watching {len(rows)} price{'s' if len(rows) != 1 else ''}:\n"
                + "\n".join(lines)
            )
        return build_result(
            ev, text, [], ("shopping",), ("Checking your price alerts…",),
            ("Show my notifications", "What offers can I use on my cards?"),
        )  # fmt: skip
    payload = await notification_service.payload(ctx)
    if not payload.items:
        text = (
            "You're all caught up — no alerts yet. Budget warnings, lunch ideas near your office, "
            "price drops and your month-end savings report will show up here."
        )
    else:
        lines = [f"{n}. {i.title} — {i.body}" for n, i in enumerate(payload.items[:4], 1)]
        unread = (
            f"You have {payload.unread_count} unread alert{'s' if payload.unread_count != 1 else ''}."
            if payload.unread_count
            else "You have read all your alerts."
        )
        text = f"{unread} The latest:\n" + "\n".join(lines)
    return build_result(
        ev, text, [], ("budget",), ("Reading your alerts…",),
        ("Show my price alerts", "What is left in my budget?"),
    )  # fmt: skip


# ------------------------------------------------------------------ small talk

GREETING = re.compile(
    r"^\s*(hi+|hello|hey+|hai|namaste|namaskara|good (morning|afternoon|evening)|yo)\b", re.I
)
THANKS = re.compile(r"\b(thanks|thank you|thx|ty|great|awesome|cool|ok(ay)?)\b[\s!.]*$", re.I)
HELP = re.compile(
    r"\b(what can you do|how can you help|help me|what do you do|who are you|^help)\b", re.I
)


def small_talk_kind(message: str) -> str | None:
    words = len(message.split())
    if HELP.search(message):
        return "help"
    if words <= 5 and GREETING.search(message):
        return "greeting"
    if words <= 4 and THANKS.search(message):
        return "thanks"
    return None


CAPABILITIES = (
    "I'm Buddy, your money assistant. Ask me anything about you and your money: your profile and "
    "saved places, what is left in your budget and where it went, your recent expenses (or tell "
    'me "I spent ₹120 on lunch" and I\'ll log it), cheap places to eat near you, your grocery '
    "list and the cheapest store, product prices and whether to buy now, offers on your cards, "
    "PGs and flats, your savings and your alerts."
)
STARTERS = (
    "What is left in my budget?",
    "Show places to eat near me, cheapest first",
    "Where is my money going?",
    "Show PGs near my office",
)


async def small_talk(ctx: Ctx, ev: Evidence, kind: str) -> AgentResult:
    first = ctx.user.name or "there"
    if kind == "greeting":
        text = f"Hi {first}! {CAPABILITIES}"
    elif kind == "thanks":
        text = f"Happy to help, {first}. Anything else you want to check?"
    else:
        text = CAPABILITIES
    return build_result(ev, text, [], (), ("Working out what you need…",), STARTERS)


def fallback_text(message: str) -> str:
    return (
        "Sorry, I can't help with that one. I answer questions about you and your money on "
        "BachelorBuddy: your profile, budget and spending, expenses, food near you, groceries, "
        "product prices, offers on your cards, homes, savings and alerts. Try one of these."
    )
