"""The job search pipeline.

    find the career board of every company still "pending" (added by name only)
    for each enabled company:
        fetch jobs  ->  keyword qualification (OR)  ->  store qualifying jobs
        ->  AI scoring  ->  expire vanished jobs
    after all companies:  email about NEW qualifying jobs (optional)

Keyword qualification happens BEFORE and independently of AI scoring. A qualified
job is always stored, whatever its score; the AI threshold only affects ranking,
filtering and notifications.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.app.collectors import CollectorError, CompanyTarget, HttpFetcher, get_collector
from backend.app.core.config import Settings
from backend.app.database.base import utcnow
from backend.app.matching.embeddings import Embedder
from backend.app.matching.keyword_matcher import KeywordMatcher, KeywordRule, MatchResult
from backend.app.models import Job, SearchHistory
from backend.app.repositories.config_repos import (
    CompanyRepository,
    KeywordRepository,
    PreferenceRepository,
)
from backend.app.repositories.job_repos import HistoryRepository, JobRepository, ResumeRepository
from backend.app.services.board_discovery import BoardDiscovery
from backend.app.services.discovery_runner import discover_company
from backend.app.services.matching_service import MatchingService
from backend.app.services.notification_service import EmailNotifier, NotificationError

logger = logging.getLogger(__name__)


@dataclass
class SearchDeps:
    http: HttpFetcher
    embedder_factory: Callable[[], Embedder]  # only called if there is something to score
    notifier: EmailNotifier


class SearchService:
    def __init__(self, db: Session, settings: Settings, deps: SearchDeps):
        self.db = db
        self.settings = settings
        self.deps = deps
        self.companies = CompanyRepository(db)
        self.keywords = KeywordRepository(db)
        self.prefs = PreferenceRepository(db)
        self.jobs = JobRepository(db)
        self.history = HistoryRepository(db)
        self.resumes = ResumeRepository(db)
        self._embedder: Embedder | None = None

    def _matching(self) -> MatchingService:
        if self._embedder is None:
            self._embedder = self.deps.embedder_factory()
        return MatchingService(self.db, self._embedder, self.settings)

    def run(
        self,
        history: SearchHistory,
        company_ids: list[int] | None = None,
    ) -> SearchHistory:
        errors: list[str] = []
        try:
            self._run(history, company_ids, errors)
        except Exception as exc:  # last resort: never leave a search "running" forever
            logger.exception("Search %s crashed", history.id)
            self.db.rollback()
            history = self.history.get(history.id)
            errors.append(f"Unexpected error: {exc}")
            history.status = "failed"
        history.errors = errors
        history.current_company = None
        history.finished_at = utcnow()
        self.db.commit()
        logger.info(
            "Search %s finished: %s (%d fetched, %d matched, %d new, %d notes)",
            history.id,
            history.status,
            history.jobs_fetched,
            history.qualified_jobs,
            history.new_jobs,
            len(errors),
        )
        return history

    def _run(self, history: SearchHistory, company_ids: list[int] | None, errors: list[str]) -> None:
        companies = self.companies.enabled(company_ids)
        rules = [KeywordRule(k.keyword, tuple(k.aliases or ())) for k in self.keywords.enabled()]
        if not rules:
            errors.append("No enabled search keywords. Add at least one keyword in Settings > Keywords.")
            history.status = "failed"
            return
        if not companies:
            errors.append("No enabled target companies to search.")
            history.status = "failed"
            return

        matcher = KeywordMatcher(rules)
        prefs = self.prefs.get()
        resume = self.resumes.active()
        history.companies_searched = len(companies)
        history.companies_done = 0
        self.db.commit()  # lets the dashboard show "running" with the total right away
        logger.info("Search %s started: %d companies", history.id, len(companies))

        discovery = BoardDiscovery(self.deps.http)
        fetched_total = qualified_total = ok_companies = 0
        new_jobs: list[Job] = []

        for company in companies:
            history.current_company = company.name
            self.db.commit()
            if company.discovery_status in ("pending", "unreachable"):
                logger.info("Search %s: looking for the career board of %r", history.id, company.name)
                discover_company(self.db, company, discovery)
                self.db.commit()
            if not company.platform or not company.board_token:
                msg = f"{company.name}: {company.last_error or 'no career board found'}"
                errors.append(msg)
                self.companies.record_search(company, ok=False, count=0, error=company.last_error)
                history.companies_done += 1
                self.db.commit()
                continue

            logger.info(
                "Search %s: fetching %s (%s/%s)",
                history.id,
                company.name,
                company.platform,
                company.board_token,
            )
            target = CompanyTarget(company.name, company.board_token, company.api_region)
            try:
                collector = get_collector(company.platform, self.deps.http)
                fetched = collector.fetch_jobs(target)
            except CollectorError as exc:
                msg = f"{company.name}: {exc}"
                logger.warning(msg)
                errors.append(msg)
                self.companies.record_search(company, ok=False, count=0, error=str(exc))
                history.companies_done += 1
                self.db.commit()
                continue

            ok_companies += 1
            if collector.skipped:
                errors.append(f"{company.name}: skipped {collector.skipped} malformed postings")
            seen_at = utcnow()
            to_score: list[tuple[Job, MatchResult]] = []
            for nj in fetched:
                result = matcher.match(nj.title, nj.description)
                if not result.qualified:
                    existing = self.jobs.find(nj.source, nj.external_id)
                    if existing is not None:  # already stored: keep it fresh, mark not qualified
                        self.jobs.upsert(nj, company.id, seen_at)
                        self.jobs.set_not_qualified(existing)
                    continue
                job, is_new, _changed = self.jobs.upsert(nj, company.id, seen_at)
                to_score.append((job, result))
                if is_new:
                    new_jobs.append(job)

            if to_score:
                matching = self._matching()
                matching.score_and_store(to_score, matching.build_context(resume, prefs))
            self.jobs.expire_missing(company.id, {nj.external_id for nj in fetched}, company.platform)
            self.companies.record_search(company, ok=True, count=len(fetched), error=None)
            fetched_total += len(fetched)
            qualified_total += len(to_score)
            history.companies_done += 1
            history.jobs_fetched = fetched_total  # live counters for the dashboard
            history.qualified_jobs = qualified_total
            logger.info(
                "Search %s: %s done, %d jobs fetched, %d matched keywords",
                history.id,
                company.name,
                len(fetched),
                len(to_score),
            )
            self.db.commit()  # progress survives a crash in a later company

        history.current_company = None
        history.jobs_fetched = fetched_total
        history.qualified_jobs = qualified_total
        history.new_jobs = len(new_jobs)
        self._notify(new_jobs, errors)  # before status, so email problems are reflected in it
        history.status = (
            "success"
            if not errors and ok_companies == len(companies)
            else ("partial" if ok_companies else "failed")
        )

    def _notify(self, new_jobs: list[Job], errors: list[str]) -> None:
        prefs = self.prefs.get()
        if not (prefs.email_enabled and prefs.email_to and new_jobs):
            return
        if not self.deps.notifier.configured:
            errors.append("Email is enabled but SMTP is not configured in .env; no email sent.")
            return
        already = self.history.notified_job_ids()
        pending = [
            j
            for j in new_jobs
            if j.id not in already
            and j.match is not None
            and j.match.keyword_qualified
            and j.match.above_threshold  # equals True for everyone when the threshold is off
        ]
        if not pending:
            return
        try:
            self.deps.notifier.send_digest(prefs.email_to, pending)
            for j in pending:
                self.history.record_notification(j.id, "sent", None)
        except NotificationError as exc:
            errors.append(str(exc))
            for j in pending:
                self.history.record_notification(j.id, "failed", str(exc)[:500])
