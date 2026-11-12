from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from app.core.constants import AgentName
from app.schemas.budget import BudgetCategoryOut
from app.schemas.common import CamelModel, UtcDateTime
from app.schemas.food import FoodListingSummary
from app.schemas.grocery import GroceryPlanSummary
from app.schemas.home import HomeSummary
from app.schemas.offer import OfferOut
from app.schemas.product import ProductSummary

MAX_MESSAGE_LENGTH = 500


class FoodCard(CamelModel):
    type: Literal["food"] = "food"
    listing: FoodListingSummary


class ProductCard(CamelModel):
    type: Literal["product"] = "product"
    product: ProductSummary


class HomeCard(CamelModel):
    type: Literal["home"] = "home"
    home: HomeSummary


class BudgetSummaryCard(CamelModel):
    type: Literal["budgetSummary"] = "budgetSummary"
    budget: list[BudgetCategoryOut]


class OfferCard(CamelModel):
    type: Literal["offer"] = "offer"
    offer: OfferOut


class GroceryPlanCard(CamelModel):
    type: Literal["groceryPlan"] = "groceryPlan"
    plan: GroceryPlanSummary


ChatCard = Annotated[
    FoodCard | ProductCard | HomeCard | BudgetSummaryCard | OfferCard | GroceryPlanCard,
    Field(discriminator="type"),
]


class ChatReply(CamelModel):
    message_id: str
    conversation_id: str
    text: str
    cards: list[ChatCard]
    agents_used: list[AgentName]
    steps: list[str]
    suggested_follow_ups: list[str]
    created_at: UtcDateTime


class ChatMessageRequest(CamelModel):
    message: str
    conversation_id: str | None = None

    @field_validator("message", mode="before")
    @classmethod
    def _message(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Type a message first.")
        if len(value) > MAX_MESSAGE_LENGTH:
            raise ValueError("That message is too long. Keep it under 500 characters.")
        return value.strip()


# ---------------------------------------------------------------- history


class ConversationSummary(CamelModel):
    """One past conversation in the history list."""

    id: str
    #: The first thing the user asked, shortened.
    title: str
    #: The latest message, shortened, to jog the memory.
    preview: str
    message_count: int
    created_at: UtcDateTime
    updated_at: UtcDateTime


class ChatHistoryMessage(CamelModel):
    """A stored message in the same shape the chat shows. Cards are returned exactly as they
    were shown at the time, so an old conversation reads the same later."""

    id: str
    role: Literal["user", "assistant"]
    text: str
    cards: list[dict[str, Any]]
    agents_used: list[AgentName]
    steps: list[str]
    suggested_follow_ups: list[str]
    created_at: UtcDateTime


class ConversationDetail(CamelModel):
    id: str
    title: str
    created_at: UtcDateTime
    updated_at: UtcDateTime
    messages: list[ChatHistoryMessage]


class DeleteConversationResponse(CamelModel):
    deleted: Literal[True] = True
    conversation_id: str
