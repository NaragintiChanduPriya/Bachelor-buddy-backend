"""The scheduler process. Run it separately from the API so jobs never run once per API worker.

uv run python -m app.scheduler                       # run on schedule (Asia/Kolkata)
uv run python -m app.scheduler list                  # the jobs and when they run
uv run python -m app.scheduler run lunch_suggestion  # run one job now (demos)
uv run python -m app.scheduler run budget_check --force
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.engine import make_url

from app.core.clock import build_clock
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import Database
from app.factory import build_llm
from app.scheduler import runtime
from app.scheduler.jobs import JOBS, JobContext, run_job

logger = logging.getLogger("app.scheduler")


def job_context(settings: Settings, db: Database) -> JobContext:
    return JobContext(
        sessions=db.sessionmaker,
        clock=build_clock(settings),
        settings=settings,
        llm=build_llm(settings),
    )


def jobstore_url(settings: Settings) -> str:
    """APScheduler's job store is synchronous, so it uses psycopg instead of asyncpg."""
    url = make_url(settings.database_url.get_secret_value()).set(drivername="postgresql+psycopg")
    query = dict(url.query)
    if "ssl" in query:
        query["sslmode"] = query.pop("ssl")
    return url.set(query=query).render_as_string(hide_password=False)


async def serve(settings: Settings) -> None:
    db = Database.from_settings(settings)
    runtime.context = job_context(settings, db)
    scheduler = AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=jobstore_url(settings))},
        timezone=settings.tz,
    )
    for spec in JOBS.values():
        scheduler.add_job(
            "app.scheduler.runtime:scheduled",
            CronTrigger(timezone=settings.tz, **spec.cron),
            args=[spec.name],
            id=spec.name,
            name=spec.description,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
    scheduler.start()
    logger.info("scheduler_started", extra={"jobs": list(JOBS), "timezone": settings.tz})
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Windows has no signal handlers here; Ctrl+C raises KeyboardInterrupt instead.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        scheduler.shutdown(wait=False)
        await db.dispose()


async def run_once(settings: Settings, name: str, force: bool) -> int:
    db = Database.from_settings(settings)
    try:
        outcome = await run_job(job_context(settings, db), name, force=force)
    finally:
        await db.dispose()
    if outcome.skipped:
        print(f"{name}: already ran for {outcome.run_key} (use --force to run again)")
    else:
        print(
            f"{name} ({outcome.run_key}): {outcome.users} users, "
            f"{outcome.notifications} new notifications {outcome.details or ''}".rstrip()
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.scheduler", description=__doc__.split("\n\n")[0] if __doc__ else None
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list", help="show the jobs and their schedules")
    run = sub.add_parser("run", help="run one job now")
    run.add_argument("job", choices=sorted(JOBS))
    run.add_argument("--force", action="store_true", help="run even if this period already ran")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    if args.command == "list":
        for spec in JOBS.values():
            when = " ".join(f"{k}={v}" for k, v in spec.cron.items())
            print(f"{spec.name:<18} {when:<36} {spec.description}")
        return 0
    if args.command == "run":
        return asyncio.run(run_once(settings, args.job, args.force))
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve(settings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
