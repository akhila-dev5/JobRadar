"""Repositories for resumes, jobs/matches, tracking, history and caches."""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from backend.app.collectors.base import NormalizedJob
from backend.app.database.base import utcnow
from backend.app.models import (
    ApplicationTracking,
    EmbeddingCache,
    Job,
    JobMatch,
    NotificationHistory,
    Resume,
    ResumeSkill,
    SavedJob,
    SearchHistory,
)
from backend.app.repositories.config_repos import NotFound


class ResumeRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(self) -> list[Resume]:
        return list(self.db.scalars(select(Resume).order_by(Resume.created_at.desc())))

    def get(self, resume_id: int) -> Resume:
        obj = self.db.get(Resume, resume_id)
        if obj is None:
            raise NotFound(f"Resume {resume_id} not found")
        return obj

    def active(self) -> Resume | None:
        return self.db.scalar(select(Resume).where(Resume.is_active.is_(True)))

    def activate(self, resume: Resume) -> None:
        self.db.execute(update(Resume).values(is_active=False))
        resume.is_active = True
        self.db.flush()

    def create(self, resume: Resume) -> Resume:
        self.db.add(resume)
        self.db.flush()
        return resume

    def add_skill(self, resume: Resume, name: str, category: str, source: str) -> ResumeSkill | None:
        if any(s.name.lower() == name.lower() for s in resume.skills):
            return None
        skill = ResumeSkill(resume_id=resume.id, name=name, category=category, source=source)
        resume.skills.append(skill)
        self.db.flush()
        return skill

    def remove_skill(self, resume: Resume, name: str) -> bool:
        for skill in list(resume.skills):
            if skill.name.lower() == name.lower():
                resume.skills.remove(skill)
                self.db.flush()
                return True
        return False

    def delete(self, resume: Resume) -> None:
        self.db.delete(resume)
        self.db.flush()


class JobRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, job_id: int) -> Job:
        job = self.db.scalar(select(Job).options(joinedload(Job.match)).where(Job.id == job_id))
        if job is None:
            raise NotFound(f"Job {job_id} not found")
        return job

    def find(self, source: str, external_id: str) -> Job | None:
        return self.db.scalar(
            select(Job)
            .options(joinedload(Job.match))
            .where(Job.source == source, Job.external_id == external_id)
        )

    def upsert(self, nj: NormalizedJob, company_id: int | None, seen_at: datetime) -> tuple[Job, bool, bool]:
        """Insert or refresh a job. Returns (job, is_new, content_changed)."""
        from backend.app.matching.scoring import parse_experience_requirement

        digest = nj.content_hash()
        lo, hi, text = parse_experience_requirement(nj.description)
        job = self.find(nj.source, nj.external_id)
        if job is None:
            job = Job(
                source=nj.source,
                external_id=nj.external_id,
                company_id=company_id,
                company_name=nj.company_name,
                title=nj.title[:500],
                description=nj.description,
                location=nj.location,
                employment_type=nj.employment_type,
                workplace_type=nj.workplace_type,
                experience_text=text,
                min_experience_years=lo,
                max_experience_years=hi,
                published_at=nj.published_at,
                application_url=nj.application_url[:1000],
                content_hash=digest,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            )
            self.db.add(job)
            self.db.flush()
            return job, True, True
        changed = job.content_hash != digest
        if changed:
            job.title = nj.title[:500]
            job.description = nj.description
            job.location = nj.location
            job.employment_type = nj.employment_type
            job.workplace_type = nj.workplace_type
            job.experience_text, job.min_experience_years, job.max_experience_years = (text, lo, hi)
            job.published_at = nj.published_at or job.published_at
            job.application_url = nj.application_url[:1000]
            job.content_hash = digest
        job.last_seen_at = seen_at
        job.company_id = company_id or job.company_id
        job.is_active = True
        job.expired_at = None
        self.db.flush()
        return job, False, changed

    def expire_missing(self, company_id: int, seen_ids: set[str], source: str) -> int:
        """Mark jobs of a company that vanished from a successful fetch as expired."""
        q = select(Job).where(Job.company_id == company_id, Job.source == source, Job.is_active.is_(True))
        count = 0
        for job in self.db.scalars(q):
            if job.external_id not in seen_ids:
                job.is_active = False
                job.expired_at = utcnow()
                count += 1
        self.db.flush()
        return count

    def save_match(self, job: Job, **fields) -> JobMatch:
        match = job.match
        if match is None:
            match = JobMatch(job_id=job.id)
            self.db.add(match)
            job.match = match
        for key, value in fields.items():
            setattr(match, key, value)
        match.scored_at = utcnow()
        self.db.flush()
        return match

    def set_not_qualified(self, job: Job) -> None:
        if job.match is not None:
            job.match.keyword_qualified = False
            job.match.matched_keywords = []
            self.db.flush()

    # ---- listing -------------------------------------------------------
    def query(
        self,
        *,
        company: str | None = None,
        title: str | None = None,
        keyword: str | None = None,
        location: str | None = None,
        min_score: float | None = None,
        source: str | None = None,
        published_after: date | None = None,
        only_active: bool = True,
        only_qualified: bool = True,
        only_new_since: datetime | None = None,
        saved_only: bool = False,
        sort: str = "score",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Job], int]:
        q = select(Job).join(JobMatch, JobMatch.job_id == Job.id).options(joinedload(Job.match))
        if only_active:
            q = q.where(Job.is_active.is_(True))
        if only_qualified:
            q = q.where(JobMatch.keyword_qualified.is_(True))
        if company:
            q = q.where(func.lower(Job.company_name).like(f"%{company.lower()}%"))
        if title:
            q = q.where(func.lower(Job.title).like(f"%{title.lower()}%"))
        if location:
            q = q.where(func.lower(func.coalesce(Job.location, "")).like(f"%{location.lower()}%"))
        if source:
            q = q.where(Job.source == source)
        if min_score is not None:
            q = q.where(JobMatch.score >= min_score)
        if published_after:
            q = q.where(
                or_(
                    Job.published_at
                    >= datetime.combine(published_after, datetime.min.time()).replace(tzinfo=utcnow().tzinfo),
                    and_(
                        Job.published_at.is_(None),
                        Job.first_seen_at
                        >= datetime.combine(published_after, datetime.min.time()).replace(
                            tzinfo=utcnow().tzinfo
                        ),
                    ),
                )
            )
        if only_new_since:
            q = q.where(Job.first_seen_at >= only_new_since)
        if saved_only:
            q = q.join(SavedJob, SavedJob.job_id == Job.id)
        jobs = list(self.db.scalars(q).unique())
        if keyword:  # JSON list filter done in Python to stay portable across databases
            kw = keyword.lower()
            jobs = [j for j in jobs if any(kw in k.lower() for k in (j.match.matched_keywords or []))]
        total = len(jobs)
        if sort == "date":
            jobs.sort(key=lambda j: j.published_at or j.first_seen_at, reverse=True)
        else:
            jobs.sort(key=lambda j: j.match.score, reverse=True)
        return jobs[offset : offset + limit], total

    def stats(self, threshold: float | None, since: datetime | None) -> dict:
        total_seen = self.db.scalar(select(func.count(Job.id))) or 0
        qualified = (
            self.db.scalar(
                select(func.count(JobMatch.id))
                .join(Job)
                .where(JobMatch.keyword_qualified.is_(True), Job.is_active.is_(True))
            )
            or 0
        )
        above = 0
        if threshold is not None:
            above = (
                self.db.scalar(
                    select(func.count(JobMatch.id))
                    .join(Job)
                    .where(
                        JobMatch.keyword_qualified.is_(True),
                        Job.is_active.is_(True),
                        JobMatch.score >= threshold,
                    )
                )
                or 0
            )
        else:
            above = qualified
        new = 0
        if since is not None:
            new = (
                self.db.scalar(
                    select(func.count(JobMatch.id))
                    .join(Job)
                    .where(JobMatch.keyword_qualified.is_(True), Job.first_seen_at >= since)
                )
                or 0
            )
        return {
            "stored_jobs": total_seen,
            "qualified_jobs": qualified,
            "above_threshold": above,
            "new_jobs": new,
        }


class TrackingRepository:
    def __init__(self, db: Session):
        self.db = db

    def is_saved(self, job_id: int) -> bool:
        return self.db.scalar(select(SavedJob.id).where(SavedJob.job_id == job_id)) is not None

    def saved_ids(self) -> set[int]:
        return set(self.db.scalars(select(SavedJob.job_id)))

    def save(self, job_id: int) -> None:
        if not self.is_saved(job_id):
            self.db.add(SavedJob(job_id=job_id))
            self.db.flush()

    def unsave(self, job_id: int) -> None:
        self.db.execute(delete(SavedJob).where(SavedJob.job_id == job_id))

    def get(self, job_id: int) -> ApplicationTracking | None:
        return self.db.scalar(select(ApplicationTracking).where(ApplicationTracking.job_id == job_id))

    def upsert(self, job_id: int, **data) -> ApplicationTracking:
        row = self.get(job_id)
        if row is None:
            row = ApplicationTracking(job_id=job_id, **data)
            self.db.add(row)
        else:
            for key, value in data.items():
                setattr(row, key, value)
        self.db.flush()
        return row

    def list(self, status: str | None = None) -> list[ApplicationTracking]:
        q = select(ApplicationTracking)
        if status:
            q = q.where(ApplicationTracking.status == status)
        return list(self.db.scalars(q.order_by(ApplicationTracking.updated_at.desc())))

    def tracking_by_job(self) -> dict[int, ApplicationTracking]:
        return {t.job_id: t for t in self.db.scalars(select(ApplicationTracking))}


class HistoryRepository:
    def __init__(self, db: Session):
        self.db = db

    def start(self, trigger: str) -> SearchHistory:
        row = SearchHistory(trigger=trigger, status="running")
        self.db.add(row)
        self.db.flush()
        return row

    def get(self, history_id: int) -> SearchHistory:
        row = self.db.get(SearchHistory, history_id)
        if row is None:
            raise NotFound(f"Search {history_id} not found")
        return row

    def recent(self, limit: int = 20) -> list[SearchHistory]:
        return list(self.db.scalars(select(SearchHistory).order_by(SearchHistory.id.desc()).limit(limit)))

    def last_success(self) -> SearchHistory | None:
        return self.db.scalar(
            select(SearchHistory)
            .where(SearchHistory.status.in_(("success", "partial")))
            .order_by(SearchHistory.id.desc())
            .limit(1)
        )

    def running(self, within_minutes: int = 30) -> SearchHistory | None:
        from datetime import timedelta

        cutoff = utcnow() - timedelta(minutes=within_minutes)
        rows = self.db.scalars(select(SearchHistory).where(SearchHistory.status == "running"))
        for row in rows:
            started = (
                row.started_at if row.started_at.tzinfo else row.started_at.replace(tzinfo=utcnow().tzinfo)
            )
            if started >= cutoff:
                return row
        return None

    def notified_job_ids(self, channel: str = "email") -> set[int]:
        return set(
            self.db.scalars(
                select(NotificationHistory.job_id).where(
                    NotificationHistory.channel == channel, NotificationHistory.status == "sent"
                )
            )
        )

    def record_notification(
        self, job_id: int, status: str, error: str | None, channel: str = "email"
    ) -> None:
        existing = self.db.scalar(
            select(NotificationHistory).where(
                NotificationHistory.job_id == job_id, NotificationHistory.channel == channel
            )
        )
        if existing is None:
            self.db.add(NotificationHistory(job_id=job_id, channel=channel, status=status, error=error))
        else:
            existing.status, existing.error, existing.sent_at = status, error, utcnow()
        self.db.flush()


class EmbeddingCacheRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_many(self, hashes: list[str], model: str) -> dict[str, np.ndarray]:
        if not hashes:
            return {}
        rows = self.db.scalars(
            select(EmbeddingCache).where(
                EmbeddingCache.model_name == model, EmbeddingCache.content_hash.in_(hashes)
            )
        )
        return {r.content_hash: np.frombuffer(r.vector, dtype=np.float32).copy() for r in rows}

    def put_many(self, items: dict[str, np.ndarray], model: str) -> None:
        for digest, vec in items.items():
            vec32 = np.asarray(vec, dtype=np.float32)
            self.db.merge(
                EmbeddingCache(
                    content_hash=digest,
                    model_name=model,
                    dim=int(vec32.shape[0]),
                    vector=vec32.tobytes(),
                )
            )
        self.db.flush()
