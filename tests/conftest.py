"""Shared fixtures.

Tests never touch the development database: the app under test points at TEST_DATABASE_URL.
Tests marked `db` need that database (created by `scripts/setup_db.py`); they are skipped, with a
reason, when it isn't reachable. Everything else runs without PostgreSQL.

The test database is seeded once (small: Arjun plus three users) with the clock pinned to
TEST_NOW. Each database test then runs inside a transaction that is rolled back afterwards, so
tests never see each other's writes even though services call `commit()`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import FixedClock
from app.core.config import ENV_FILE, Settings
from app.core.security import create_access_token
from app.db.models import User
from app.db.session import Database, get_session
from app.factory import create_app
from app.services import users as user_service
from scripts.seed.anchors import TEST_NOW, TEST_SEED_USERS

FRONTEND_ORIGIN = "http://localhost:5173"
DEMO_EMAIL = "arjun@demo.com"

_FALLBACK_TEST_URL = (
    "postgresql+asyncpg://bachelorbuddy_app:unset@localhost:5432/bachelorbuddy_test"
)


def load_test_settings() -> Settings:
    """`.env` with the database swapped for the test database. Works without `.env` too."""
    try:
        base = Settings(_env_file=ENV_FILE if ENV_FILE.exists() else None)
    except ValidationError:
        base = Settings(
            _env_file=None,
            database_url=SecretStr(_FALLBACK_TEST_URL),
            jwt_secret=SecretStr("test-secret-" * 4),
        )
    test_url = base.test_database_url or SecretStr(_FALLBACK_TEST_URL)
    return base.model_copy(
        update={
            "app_env": "test",
            "database_url": test_url,
            "cors_origins": [FRONTEND_ORIGIN],
            "clock_mode": "demo",
            "agent_mode": "rules",
            "bcrypt_rounds": 4,
            "rate_limit_enabled": False,
            "dev_auth_bypass_email": None,
        }
    )


@pytest.fixture(scope="session")
def settings() -> Settings:
    return load_test_settings()


@pytest.fixture
def clock(settings: Settings) -> FixedClock:
    return FixedClock(settings.zone, TEST_NOW)


@pytest.fixture
def app(settings: Settings, clock: FixedClock) -> FastAPI:
    return create_app(settings, clock=clock)


async def make_client(app: FastAPI, headers: dict[str, str] | None = None) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers or {}
    )


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with await make_client(app) as http:
        yield http


# ------------------------------------------------------------------ database


@pytest.fixture(scope="session")
async def database(settings: Settings) -> AsyncIterator[Database]:
    """The real test database, or a skip with instructions."""
    db = Database.from_settings(settings)
    try:
        async with asyncio.timeout(20):  # a scaled-to-zero Neon compute needs a moment
            await db.ping()
    except Exception as exc:
        await db.dispose()
        pytest.skip(
            f"test database not reachable ({type(exc).__name__}); "
            "run `uv run python scripts/setup_db.py` first"
        )
    yield db
    await db.dispose()


@pytest.fixture(scope="session")
def seeded(database: Database) -> None:
    """Seed the test database once (skipped when the same seed is already loaded)."""
    from scripts import generate_data

    try:
        generate_data.run(
            users=TEST_SEED_USERS, demo=True, test_db=True, anchor_now=TEST_NOW, quiet=True
        )
    except Exception as exc:  # pragma: no cover - environment problem, not a test failure
        pytest.skip(f"could not seed the test database: {exc}")


@pytest.fixture
async def db_session(database: Database, seeded: None) -> AsyncIterator[AsyncSession]:
    """A session whose work is rolled back after the test (commits become savepoints)."""
    async with database.engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
            autoflush=False,
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
def session_factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """For code that opens its own sessions (scheduled jobs): same rolled-back connection."""
    return async_sessionmaker(
        bind=db_session.bind,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
        autoflush=False,
    )


@pytest.fixture
def db_app(
    settings: Settings, clock: FixedClock, database: Database, db_session: AsyncSession
) -> FastAPI:
    app = create_app(settings, database=database, clock=clock)

    async def override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override
    return app


@pytest.fixture
async def api(db_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Unauthenticated client against the seeded test database."""
    async with await make_client(db_app) as http:
        yield http


@pytest.fixture
async def arjun(db_session: AsyncSession) -> User:
    user = await user_service.load_user_by_email(db_session, DEMO_EMAIL)
    assert user is not None, "the seeded demo user is missing"
    return user


def bearer(user_id: int, settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id, settings)[0]}"}


@pytest.fixture
async def as_arjun(db_app: FastAPI, arjun: User, settings: Settings) -> AsyncIterator[AsyncClient]:
    """Signed in as the demo user."""
    async with await make_client(db_app, bearer(arjun.id, settings)) as http:
        yield http
