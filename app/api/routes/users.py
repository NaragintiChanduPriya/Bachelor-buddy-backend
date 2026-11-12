"""GET /meta/areas (public), POST /onboarding, GET /me, PUT /me/preferences."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import ClockDep, CurrentUser
from app.db.session import SessionDep
from app.schemas.common import Envelope, ok
from app.schemas.meta import AreasResponse
from app.schemas.user import (
    OnboardingRequest,
    OnboardingResponse,
    PreferencesUpdateRequest,
    UserOut,
)
from app.services import meta as meta_service
from app.services import users as user_service

router = APIRouter(tags=["users"])


@router.get("/meta/areas", tags=["meta"], summary="Bangalore areas and tech parks (public)")
async def areas(session: SessionDep, response: Response) -> Envelope[AreasResponse]:
    response.headers["Cache-Control"] = "public, max-age=3600"
    return ok(await meta_service.areas_and_parks(session))


@router.post("/onboarding", summary="Save the profile and generate the first monthly budget")
async def onboarding(
    body: OnboardingRequest, user: CurrentUser, session: SessionDep, clock: ClockDep
) -> Envelope[OnboardingResponse]:
    return ok(await user_service.complete_onboarding(session, user, clock, body))


@router.get("/me", summary="Profile, preferences, cards and onboarding status")
async def me(user: CurrentUser) -> Envelope[UserOut]:
    return ok(user_service.to_user_out(user))


@router.put("/me/preferences", summary="Update any subset of the preferences")
async def update_preferences(
    body: PreferencesUpdateRequest, user: CurrentUser, session: SessionDep, clock: ClockDep
) -> Envelope[UserOut]:
    return ok(await user_service.update_preferences(session, user, clock, body))
