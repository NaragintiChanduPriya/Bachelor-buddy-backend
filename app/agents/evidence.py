"""What the agents actually looked up during one request.

Cards are built from this record, never from model output, so a card can only show a listing,
product, home or offer a tool really returned. Every number a tool returned is kept too, so a
reply that quotes an amount no tool produced can be caught.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import AGENT_NAMES
from app.schemas.budget import BudgetCategoryOut
from app.schemas.chat import (
    BudgetSummaryCard,
    ChatCard,
    FoodCard,
    GroceryPlanCard,
    HomeCard,
    OfferCard,
    ProductCard,
)
from app.schemas.food import FoodListingSummary
from app.schemas.grocery import GroceryPlanSummary
from app.schemas.home import HomeSummary
from app.schemas.offer import OfferOut
from app.schemas.product import ProductSummary

logger = logging.getLogger(__name__)

RUPEE_AMOUNT = re.compile(r"₹\s?(\d[\d,]*)")
MAX_CARDS = 6


class CardRef(BaseModel):
    """How the model asks for a card: a type plus the id a tool returned."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["food", "product", "home", "offer", "budgetSummary", "groceryPlan"]
    id: str | None = Field(default=None, max_length=40)
    #: For budgetSummary: which category ids to show (default: all spending categories).
    categories: list[str] | None = Field(default=None, max_length=8)


@dataclass
class Evidence:
    food: dict[str, FoodListingSummary] = field(default_factory=dict)
    products: dict[str, ProductSummary] = field(default_factory=dict)
    homes: dict[str, HomeSummary] = field(default_factory=dict)
    offers: dict[str, OfferOut] = field(default_factory=dict)
    budget: list[BudgetCategoryOut] | None = None
    grocery_plan: GroceryPlanSummary | None = None
    numbers: set[int] = field(default_factory=set)
    agents: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    tool_log: list[dict[str, Any]] = field(default_factory=list)

    def add_agent(self, agent: str) -> None:
        if agent not in self.agents:
            self.agents.append(agent)

    def add_step(self, step: str) -> None:
        if step not in self.steps:
            self.steps.append(step)

    def record_numbers(self, payload: Any) -> None:
        """Every whole number anywhere in a tool result (money is always whole rupees)."""
        if isinstance(payload, bool):
            return
        if isinstance(payload, int):
            self.numbers.add(abs(payload))
        elif isinstance(payload, float) and payload.is_integer():
            self.numbers.add(abs(int(payload)))
        elif isinstance(payload, dict):
            for value in payload.values():
                self.record_numbers(value)
        elif isinstance(payload, list | tuple):
            for value in payload:
                self.record_numbers(value)
        elif isinstance(payload, str):
            for match in RUPEE_AMOUNT.finditer(payload):
                self.numbers.add(int(match.group(1).replace(",", "")))

    def unknown_amounts(self, text: str) -> list[int]:
        """Rupee amounts in `text` that no tool returned."""
        amounts = [int(m.group(1).replace(",", "")) for m in RUPEE_AMOUNT.finditer(text)]
        return [a for a in amounts if a not in self.numbers]

    def agents_used(self) -> list[str]:
        used = {"concierge", *self.agents}
        return [a for a in AGENT_NAMES if a in used]

    def build_cards(self, refs: list[CardRef]) -> list[ChatCard]:
        """Cards for the references a tool really returned; anything else is dropped."""
        cards: list[ChatCard] = []
        seen: set[tuple[str, str | None]] = set()
        for ref in refs:
            key = (ref.type, ref.id)
            if key in seen or len(cards) >= MAX_CARDS:
                continue
            seen.add(key)
            card = self._card(ref)
            if card is None:
                logger.warning("dropped_card", extra={"card_type": ref.type, "card_id": ref.id})
                continue
            cards.append(card)
        return cards

    def _card(self, ref: CardRef) -> ChatCard | None:
        if ref.type == "food" and ref.id in self.food:
            return FoodCard(listing=self.food[ref.id])
        if ref.type == "product" and ref.id in self.products:
            return ProductCard(product=self.products[ref.id])
        if ref.type == "home" and ref.id in self.homes:
            return HomeCard(home=self.homes[ref.id])
        if ref.type == "offer" and ref.id in self.offers:
            return OfferCard(offer=self.offers[ref.id])
        if ref.type == "groceryPlan" and self.grocery_plan is not None:
            return GroceryPlanCard(plan=self.grocery_plan)
        if ref.type == "budgetSummary" and self.budget is not None:
            wanted = set(ref.categories or [])
            rows = [c for c in self.budget if (c.id in wanted if wanted else c.id != "savings")]
            return BudgetSummaryCard(budget=rows) if rows else None
        return None
