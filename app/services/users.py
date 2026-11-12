"""Users: loading, the public User shape, onboarding and preference updates."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.calc.budget import MIN_SALARY, generate_limits
from app.core.clock import Clock
from app.core.errors import ValidationFailedError
from app.core.ids import format_id
from app.db.models import Area, TechPark, User, UserCard, UserPreferences
from app.schemas.user import (
    OnboardingRequest,
    OnboardingResponse,
    PreferencesUpdateRequest,
    SavedCard,
    UserOut,
    UserPreferencesOut,
)
from app.services import budget as budget_service

USER_OPTIONS = (
    joinedload(User.preferences).options(
        joinedload(UserPreferences.home_area),
        joinedload(UserPreferences.office_area),
        joinedload(UserPreferences.tech_park),
    ),
    joinedload(User.cards),
)


async def load_user(session: AsyncSession, user_id: int) -> User | None:
    """The user with preferences, place names and cards, in one round trip."""
    result = await session.execute(select(User).options(*USER_OPTIONS).where(User.id == user_id))
    return result.unique().scalar_one_or_none()


async def load_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(
        select(User).options(*USER_OPTIONS).where(User.email == email.lower())
    )
    return result.unique().scalar_one_or_none()


def avatar_initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def to_user_out(user: User) -> UserOut:
    """Before onboarding the places are empty strings and money fields 0, so the shape always
    matches the frontend's `User` type."""
    prefs = user.preferences
    return UserOut(
        id=format_id("user", user.id),
        name=user.name,
        email=user.email,
        age=user.age,
        occupation=user.occupation,
        avatar_initials=avatar_initials(user.name),
        onboarded=user.onboarded,
        joined_at=user.joined_at,
        preferences=UserPreferencesOut(
            salary=prefs.salary if prefs else 0,
            savings_goal=prefs.savings_goal if prefs else 0,
            home_area_id=(prefs.home_area_id or "") if prefs else "",
            home_area_name=prefs.home_area.name if prefs and prefs.home_area else "",
            office_area_id=(prefs.office_area_id or "") if prefs else "",
            office_area_name=prefs.office_area.name if prefs and prefs.office_area else "",
            tech_park_id=prefs.tech_park_id if prefs else None,
            tech_park_name=prefs.tech_park.name if prefs and prefs.tech_park else None,
            food_preference=(prefs.food_preference or "veg") if prefs else "veg",  # type: ignore[arg-type]
            cards=[
                SavedCard(id=c.card_id, bank=c.bank, type=c.card_type, label=c.label)  # type: ignore[arg-type]
                for c in user.cards
            ],
        ),
    )


def _check_money(salary: int, goal: int) -> None:
    if salary < MIN_SALARY:
        raise ValidationFailedError("Enter a monthly salary of at least ₹5,000 in whole rupees.")
    if goal < 0:
        raise ValidationFailedError("Enter a savings goal in whole rupees.")
    if goal >= salary:
        raise ValidationFailedError("Your savings goal must be less than your salary.")


async def _resolve_places(
    session: AsyncSession, home_id: str | None, office_id: str | None, park_id: str | None
) -> tuple[Area, Area, TechPark | None]:
    ids = {i for i in (home_id, office_id) if i}
    areas = {a.id: a for a in (await session.scalars(select(Area).where(Area.id.in_(ids))))}
    if not home_id or home_id not in areas:
        raise ValidationFailedError("Choose a valid home area.")
    if not office_id or office_id not in areas:
        raise ValidationFailedError("Choose a valid office area.")
    park = None
    if park_id:
        park = await session.get(TechPark, park_id)
        if park is None:
            raise ValidationFailedError("Choose a valid tech park.")
    return areas[home_id], areas[office_id], park


def _replace_cards(user: User, cards: list[SavedCard]) -> None:
    if len({c.id for c in cards}) != len(cards):
        raise ValidationFailedError("Each card can only be saved once.")
    user.cards.clear()
    for position, card in enumerate(cards):
        user.cards.append(
            UserCard(
                card_id=card.id,
                bank=card.bank,
                card_type=card.type,
                label=card.label,
                position=position,
            )
        )


def _apply_preferences(
    user: User,
    *,
    salary: int,
    goal: int,
    home: Area,
    office: Area,
    park: TechPark | None,
    food: str,
) -> UserPreferences:
    prefs = user.preferences
    if prefs is None:
        prefs = UserPreferences(user_id=user.id)
        user.preferences = prefs
    prefs.salary = salary
    prefs.savings_goal = goal
    prefs.home_area = home
    prefs.office_area = office
    prefs.tech_park = park
    prefs.food_preference = food
    return prefs


async def complete_onboarding(
    session: AsyncSession, user: User, clock: Clock, body: OnboardingRequest
) -> OnboardingResponse:
    """Save the profile and generate the current month's budget from the salary and goal."""
    _check_money(body.salary, body.savings_goal)
    home, office, park = await _resolve_places(
        session, body.home_area_id, body.office_area_id, body.tech_park_id
    )
    _apply_preferences(
        user,
        salary=body.salary,
        goal=body.savings_goal,
        home=home,
        office=office,
        park=park,
        food=body.food_preference,
    )
    _replace_cards(user, body.cards)
    user.onboarded = True
    await budget_service.reset_current_limits(
        session, user, clock, generate_limits(body.salary, body.savings_goal)
    )
    await session.commit()
    budget = await budget_service.current_budget(session, user, clock)
    return OnboardingResponse(user=to_user_out(user), budget=budget)


async def update_preferences(
    session: AsyncSession, user: User, clock: Clock, body: PreferencesUpdateRequest
) -> UserOut:
    """Omitted fields keep their value. A new salary or goal regenerates the category limits."""
    prefs = user.preferences
    salary = body.salary if body.salary is not None else (prefs.salary if prefs else 0)
    goal = (
        body.savings_goal if body.savings_goal is not None else (prefs.savings_goal if prefs else 0)
    )
    home_id = body.home_area_id or (prefs.home_area_id if prefs else None)
    office_id = body.office_area_id or (prefs.office_area_id if prefs else None)
    park_id = (
        body.tech_park_id
        if "tech_park_id" in body.model_fields_set
        else (prefs.tech_park_id if prefs else None)
    )
    food = body.food_preference or (prefs.food_preference if prefs else None)
    if food is None:
        raise ValidationFailedError("Choose a food preference.")

    _check_money(salary, goal)
    home, office, park = await _resolve_places(session, home_id, office_id, park_id)
    money_changed = prefs is None or salary != prefs.salary or goal != prefs.savings_goal
    _apply_preferences(
        user, salary=salary, goal=goal, home=home, office=office, park=park, food=food
    )
    if body.cards is not None:
        _replace_cards(user, body.cards)
    if money_changed and user.onboarded:
        await budget_service.reset_current_limits(
            session, user, clock, generate_limits(salary, goal)
        )
    await session.commit()
    return to_user_out(user)
