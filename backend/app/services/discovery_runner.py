"""Run board discovery for companies that were added by name only.

Used in two places:
  * right after you add companies (a background task, so the request returns at once)
  * at the start of every search, for any company that is still "pending"
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database.session import session_scope
from backend.app.models import Company
from backend.app.repositories.config_repos import CompanyRepository
from backend.app.services.board_discovery import BoardDiscovery, DiscoveryResult, apply_result

logger = logging.getLogger(__name__)


def discover_company(db: Session, company: Company, discovery: BoardDiscovery) -> DiscoveryResult:
    """Look up one company's board and store the outcome on the row."""
    result = discovery.discover(company.name)
    best = result.best
    if best is not None:
        other = db.scalar(
            select(Company).where(
                Company.platform == best.platform,
                Company.board_token == best.board_token,
                Company.id != company.id,
            )
        )
        if other is not None:  # the unique (platform, token) constraint would reject it
            result = DiscoveryResult(
                "not_found",
                result.candidates,
                None,
                f"That job board ('{best.board_token}' on {best.platform}) is already tracked as "
                f"'{other.name}'. Remove one of the two entries.",
                result.tried_slugs,
            )
    apply_result(company, result)
    db.flush()
    logger.info(
        "Discovery for %r: %s (%s)",
        company.name,
        result.status,
        f"{best.platform}/{best.board_token}" if result.best else "no board",
    )
    return result


def run_discovery(company_ids: list[int] | None = None, deps_factory: Callable | None = None) -> None:
    """Discover boards for pending companies (all of them when company_ids is None)."""
    if deps_factory is None:
        from backend.app.services.search_runner import default_deps_factory  # lazy: avoids an import cycle

        deps_factory = default_deps_factory
    deps: object = deps_factory()
    try:
        with session_scope() as db:
            discovery = BoardDiscovery(deps.http)  # type: ignore[attr-defined]
            for company in CompanyRepository(db).pending(company_ids):
                try:
                    discover_company(db, company, discovery)
                except Exception:  # one bad company must not stop the others
                    logger.exception("Discovery crashed for %r", company.name)
                    company.discovery_status = "not_found"
                    company.last_error = "Discovery failed unexpectedly; see the backend log."
                db.commit()  # each result becomes visible in the dashboard as soon as it is known
    finally:
        deps.http.close()  # type: ignore[attr-defined]
