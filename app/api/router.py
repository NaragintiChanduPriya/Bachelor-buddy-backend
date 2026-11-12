"""Every contract endpoint, mounted under `API_PREFIX` (default `/api`, the frontend's base URL)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import activity, auth, budget, catalog, chat, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(budget.router)
api_router.include_router(catalog.router)
api_router.include_router(activity.router)
api_router.include_router(chat.router)
