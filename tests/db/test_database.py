"""Against the real local test database. Skipped until `scripts/setup_db.py` has run."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.clock import FixedClock
from app.core.config import PROJECT_ROOT, Settings
from app.db.session import Database
from app.factory import create_app
from tests.conftest import make_client

pytestmark = pytest.mark.db


async def test_connects_as_the_app_role_not_the_admin(
    database: Database, settings: Settings
) -> None:
    async with database.engine.connect() as conn:
        user = (await conn.execute(text("SELECT current_user"))).scalar_one()
        is_super = (
            await conn.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"))
        ).scalar_one()
        db_name = (await conn.execute(text("SELECT current_database()"))).scalar_one()
    assert user != "postgres"
    assert is_super is False
    assert db_name.endswith("_test")


async def test_ready_against_the_real_database(
    database: Database, settings: Settings, clock: FixedClock
) -> None:
    async with await make_client(create_app(settings, database=database, clock=clock)) as client:
        response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["data"]["checks"] == {"database": "ok"}


def _upgrade_head(connection: Connection) -> None:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.attributes["connection"] = connection
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


async def test_migrations_upgrade_to_head(database: Database) -> None:
    async with database.engine.begin() as conn:
        await conn.run_sync(_upgrade_head)


def _model_drift(connection: Connection) -> list[object]:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    import app.db.models  # noqa: F401
    from app.db.base import Base

    context = MigrationContext.configure(
        connection,
        opts={
            "compare_type": True,
            "include_object": lambda obj, name, type_, reflected, compare_to: (
                name != "apscheduler_jobs"
            ),
        },
    )
    return list(compare_metadata(context, Base.metadata))


async def test_models_match_the_migrations(database: Database) -> None:
    """A model change without a migration fails here (`alembic revision --autogenerate`)."""
    async with database.engine.connect() as conn:
        assert await conn.run_sync(_model_drift) == []
