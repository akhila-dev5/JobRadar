"""Resume, jobs, tracker, search and system endpoints."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.deps import DbSession, get_deps_factory, job_to_detail, job_to_out
from backend.app.core.config import get_settings
from backend.app.database.base import utcnow
from backend.app.matching.keyword_matcher import KeywordMatcher, KeywordRule
from backend.app.repositories.config_repos import (
    CompanyRepository,
    KeywordRepository,
    PreferenceRepository,
)
from backend.app.repositories.job_repos import (
    HistoryRepository,
    JobRepository,
    ResumeRepository,
    TrackingRepository,
)
from backend.app.schemas.api import (
    DashboardStats,
    JobDetail,
    JobPage,
    ResumeOut,
    ResumeProfileUpdate,
    SearchOut,
    SearchRequest,
    SkillAdd,
    TrackedJob,
    TrackingIn,
    TrackingOut,
)
from backend.app.services.resume_service import ResumeService
from backend.app.services.search_runner import execute_search, start_search

resume = APIRouter(prefix="/resume", tags=["resume"])
jobs = APIRouter(prefix="/jobs", tags=["jobs"])
tracker = APIRouter(prefix="/tracker", tags=["tracker"])
search = APIRouter(prefix="/search", tags=["search"])
system = APIRouter(tags=["system"])


# ------------------------------------------------------------------ resume
@resume.post("", response_model=ResumeOut, status_code=201)
async def upload_resume(
    file: UploadFile = File(...), label: str | None = Form(default=None), db: Session = DbSession
):
    settings = get_settings()
    data = await file.read(settings.max_upload_bytes + 1)  # never read more than the limit
    return ResumeService(db, settings).upload(file.filename or "resume", data, label)


@resume.get("", response_model=list[ResumeOut])
def list_resumes(db: Session = DbSession):
    return ResumeRepository(db).list()


@resume.get("/active", response_model=ResumeOut | None)
def active_resume(db: Session = DbSession):
    return ResumeRepository(db).active()


@resume.post("/{resume_id}/activate", response_model=ResumeOut)
def activate_resume(resume_id: int, db: Session = DbSession):
    repo = ResumeRepository(db)
    obj = repo.get(resume_id)
    repo.activate(obj)
    return obj


@resume.patch("/{resume_id}", response_model=ResumeOut)
def update_profile(resume_id: int, body: ResumeProfileUpdate, db: Session = DbSession):
    obj = ResumeRepository(db).get(resume_id)
    return ResumeService(db, get_settings()).update_profile(obj, **body.model_dump(exclude_unset=True))


@resume.post("/{resume_id}/skills", response_model=ResumeOut)
def add_skill(resume_id: int, body: SkillAdd, db: Session = DbSession):
    obj = ResumeRepository(db).get(resume_id)
    ResumeService(db, get_settings()).add_skill(obj, body.name, body.category)
    return obj


@resume.delete("/{resume_id}/skills/{name}", response_model=ResumeOut)
def remove_skill(resume_id: int, name: str, db: Session = DbSession):
    obj = ResumeRepository(db).get(resume_id)
    if not ResumeService(db, get_settings()).remove_skill(obj, name):
        raise HTTPException(404, f"Skill '{name}' not found on this resume")
    return obj


@resume.delete("/{resume_id}", status_code=204)
def delete_resume(resume_id: int, delete_local_file: bool = False, db: Session = DbSession):
    obj = ResumeRepository(db).get(resume_id)
    ResumeService(db, get_settings()).delete(obj, delete_local_file)
    return Response(status_code=204)


# ------------------------------------------------------------------ jobs
@jobs.get("", response_model=JobPage)
def list_jobs(
    company: str | None = None,
    title: str | None = None,
    keyword: str | None = None,
    location: str | None = None,
    min_score: float | None = Query(default=None, ge=0, le=100),
    source: str | None = None,
    published_after: date | None = None,
    include_below_threshold: bool = False,
    include_expired: bool = False,
    saved_only: bool = False,
    sort: str = Query("score", pattern="^(score|date)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = DbSession,
):
    prefs = PreferenceRepository(db).get()
    effective_min = min_score
    # Threshold is a FILTER on what is displayed, never on what is stored/qualified.
    if prefs.ai_threshold_enabled and not include_below_threshold and not saved_only:
        effective_min = max(min_score or 0.0, prefs.ai_threshold)
    repo = JobRepository(db)
    items, total = repo.query(
        company=company,
        title=title,
        keyword=keyword,
        location=location,
        min_score=effective_min,
        source=source,
        published_after=published_after,
        only_active=not include_expired,
        saved_only=saved_only,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    tracking = TrackingRepository(db)
    saved, tracked = tracking.saved_ids(), tracking.tracking_by_job()
    return JobPage(total=total, items=[job_to_out(j, saved, tracked) for j in items])


@jobs.get("/stats", response_model=DashboardStats)
def dashboard_stats(db: Session = DbSession):
    prefs = PreferenceRepository(db).get()
    threshold = prefs.ai_threshold if prefs.ai_threshold_enabled else None
    stats = JobRepository(db).stats(threshold, utcnow() - timedelta(days=7))
    last = HistoryRepository(db).last_success()
    latest = HistoryRepository(db).recent(1)
    return DashboardStats(
        stored_jobs=stats["stored_jobs"],
        qualified_jobs=stats["qualified_jobs"],
        above_threshold=stats["above_threshold"],
        new_jobs=stats["new_jobs"],
        companies_monitored=len(CompanyRepository(db).enabled()),
        last_success_at=last.finished_at if last else None,
        last_search_status=latest[0].status if latest else None,
        ai_threshold_enabled=prefs.ai_threshold_enabled,
        ai_threshold=prefs.ai_threshold,
    )


@jobs.get("/{job_id}", response_model=JobDetail)
def job_detail(job_id: int, db: Session = DbSession):
    job = JobRepository(db).get(job_id)
    rules = [KeywordRule(k.keyword, tuple(k.aliases or ())) for k in KeywordRepository(db).enabled()]
    matched = job.match.matched_keywords if job.match else None
    highlighted = KeywordMatcher(rules).highlight(job.description, matched)
    return job_to_detail(job, db, highlighted)


@jobs.post("/{job_id}/save", status_code=204)
def save_job(job_id: int, db: Session = DbSession):
    JobRepository(db).get(job_id)
    TrackingRepository(db).save(job_id)
    return Response(status_code=204)


@jobs.delete("/{job_id}/save", status_code=204)
def unsave_job(job_id: int, db: Session = DbSession):
    TrackingRepository(db).unsave(job_id)
    return Response(status_code=204)


# ------------------------------------------------------------------ tracker
@tracker.get("", response_model=list[TrackedJob])
def list_tracked(status: str | None = None, db: Session = DbSession):
    repo = TrackingRepository(db)
    saved, tracked = repo.saved_ids(), repo.tracking_by_job()
    jobs_repo = JobRepository(db)
    out = []
    for row in repo.list(status):
        job = jobs_repo.get(row.job_id)
        out.append(TrackedJob(job=job_to_out(job, saved, tracked), tracking=TrackingOut.model_validate(row)))
    return out


@tracker.put("/{job_id}", response_model=TrackingOut)
def set_tracking(job_id: int, body: TrackingIn, db: Session = DbSession):
    JobRepository(db).get(job_id)
    data = body.model_dump()
    if data["status"] == "applied" and data["applied_date"] is None:
        data["applied_date"] = date.today()
    return TrackingRepository(db).upsert(job_id, **data)


@tracker.delete("/{job_id}", status_code=204)
def clear_tracking(job_id: int, db: Session = DbSession):
    from sqlalchemy import delete

    from backend.app.models import ApplicationTracking

    db.execute(delete(ApplicationTracking).where(ApplicationTracking.job_id == job_id))
    return Response(status_code=204)


# ------------------------------------------------------------------ search
@search.post("", response_model=SearchOut, status_code=202)
def run_search(
    body: SearchRequest,
    background: BackgroundTasks,
    db: Session = DbSession,
    factory=Depends(get_deps_factory),
):
    """Start a search in the background; poll GET /search/{id} for progress."""
    db.commit()  # release the request transaction before the worker opens its own
    history_id = start_search("manual")
    if history_id is None:
        raise HTTPException(409, "A search is already running.")
    background.add_task(execute_search, history_id, body.company_ids or None, factory)
    db.expire_all()
    return HistoryRepository(db).get(history_id)


@search.get("/history", response_model=list[SearchOut])
def search_history(limit: int = Query(20, ge=1, le=100), db: Session = DbSession):
    return HistoryRepository(db).recent(limit)


@search.get("/{history_id}", response_model=SearchOut)
def search_status(history_id: int, db: Session = DbSession):
    return HistoryRepository(db).get(history_id)


# ------------------------------------------------------------------ system
@system.get("/health")
def health(db: Session = DbSession):
    db.execute(text("SELECT 1"))
    s = get_settings()
    return {"status": "ok", "env": s.app_env, "smtp_configured": s.smtp_configured}
