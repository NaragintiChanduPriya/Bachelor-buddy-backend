"""The per-request context services receive."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import ConflictError
from app.db.models import User, UserPreferences


@dataclass
class Ctx:
    """Everything a service needs to act for one user: the session, the user (preferences and
    cards loaded), the clock and the settings."""

    session: AsyncSession
    user: User
    clock: Clock
    settings: Settings

    @property
    def prefs(self) -> UserPreferences:
        prefs = self.user.preferences
        if prefs is None or prefs.home_area_id is None or prefs.office_area_id is None:
            raise ConflictError("Finish setting up your profile first.", {"onboarded": False})
        return prefs
