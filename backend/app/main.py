"""FastAPI application entry point.

Run:  uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.api import routes_config, routes_jobs
from backend.app.api.deps import require_api_key
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging
from backend.app.database.session import DatabaseConfigError
from backend.app.repositories.config_repos import Conflict, NotFound
from backend.app.services.resume_parser import ResumeError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    scheduler = None
    if settings.scheduler_enabled and not settings.is_test:
        from apscheduler.schedulers.background import BackgroundScheduler

        from backend.app.services.search_runner import run_scheduled_search

        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(
            run_scheduled_search,
            "interval",
            hours=settings.scheduler_interval_hours,
            id="job-search",
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        logger.info("Scheduler started: search every %s h", settings.scheduler_interval_hours)
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(
        title="JobRadar AI",
        version="1.0.0",
        description="Local job discovery and resume matching API.",
        lifespan=lifespan,
        dependencies=[Depends(require_api_key)],
    )
    for router in (
        routes_config.companies,
        routes_config.keywords,
        routes_config.preferences,
        routes_jobs.resume,
        routes_jobs.jobs,
        routes_jobs.tracker,
        routes_jobs.search,
        routes_jobs.system,
    ):
        app.include_router(router)

    @app.exception_handler(NotFound)
    async def _nf(_: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def _conflict(_: Request, exc: Conflict):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ResumeError)
    async def _resume(_: Request, exc: ResumeError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(DatabaseConfigError)
    async def _dbcfg(_: Request, exc: DatabaseConfigError):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    return app


app = create_app()
