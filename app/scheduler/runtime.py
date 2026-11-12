"""The job entry point APScheduler stores by reference.

It lives in its own module because `python -m app.scheduler` loads `__main__.py` as `__main__`:
a reference to `app.scheduler.__main__` would import a second copy without the context.
"""

from __future__ import annotations

import logging

from app.scheduler.jobs import JobContext, run_job

logger = logging.getLogger("app.scheduler")

context: JobContext | None = None


async def scheduled(name: str) -> None:
    if context is None:  # pragma: no cover - set by the scheduler process at startup
        raise RuntimeError("scheduler context not initialised")
    try:
        await run_job(context, name)
    except Exception:
        logger.exception("scheduled_job_failed", extra={"job": name})
