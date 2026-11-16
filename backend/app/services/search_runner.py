"""Glue for running a search outside of a request (background task, scheduler, CLI)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from backend.app.collectors import HttpFetcher
from backend.app.core.config import get_settings
from backend.app.database.session import session_scope
from backend.app.matching.embeddings import get_embedder
from backend.app.repositories.job_repos import HistoryRepository
from backend.app.services.notification_service import EmailNotifier
from backend.app.services.search_service import SearchDeps, SearchService

logger = logging.getLogger(__name__)
DepsFactory = Callable[[], SearchDeps]


def default_deps_factory() -> SearchDeps:
    s = get_settings()
    return SearchDeps(
        http=HttpFetcher(
            timeout=s.http_timeout_seconds,
            max_retries=s.http_max_retries,
            min_interval=s.http_min_interval_seconds,
        ),
        embedder_factory=get_embedder,
        notifier=EmailNotifier(s),
    )


def start_search(trigger: str) -> int | None:
    """Create a 'running' history row. Returns None if a search is already running."""
    with session_scope() as db:
        repo = HistoryRepository(db)
        if repo.running() is not None:
            return None
        return repo.start(trigger).id


def execute_search(
    history_id: int,
    company_ids: list[int] | None = None,
    deps_factory: DepsFactory = default_deps_factory,
) -> None:
    deps = deps_factory()
    try:
        with session_scope() as db:
            history = HistoryRepository(db).get(history_id)
            SearchService(db, get_settings(), deps).run(history, company_ids)
    finally:
        deps.http.close()


def run_scheduled_search(deps_factory: DepsFactory = default_deps_factory) -> None:
    history_id = start_search("scheduled")
    if history_id is None:
        logger.info("Scheduled search skipped: another search is running")
        return
    execute_search(history_id, None, deps_factory)
