"""Async engine and sessions.

The engine is created per app instance (not at import time), so tests can build an app against
the test database and the API never connects until a request needs it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


class Database:
    def __init__(
        self,
        url: str,
        *,
        pool_size: int = 5,
        max_overflow: int = 5,
        application_name: str = "bachelorbuddy-api",
    ) -> None:
        # Tuned for hosted PostgreSQL (Neon): a scaled-to-zero compute takes a few seconds to
        # wake, and idle connections are dropped when it suspends, so connections are checked
        # before use and recycled well within the suspend window. Never rely on the session time
        # zone (Neon ignores the startup setting): store timestamptz and convert explicitly.
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            pool_recycle=240,
            connect_args={
                "timeout": 15,  # seconds to establish a connection
                "server_settings": {"application_name": application_name},
            },
        )
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> Database:
        return cls(
            settings.database_url.get_secret_value(),
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )

    async def ping(self) -> None:
        """Run `SELECT 1`. Callers bound it with `asyncio.timeout(...)`."""
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()


def get_database(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Services commit explicitly; anything uncommitted rolls back."""
    async with get_database(request).sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
DatabaseDep = Annotated[Database, Depends(get_database)]
