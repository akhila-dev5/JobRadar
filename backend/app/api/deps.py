import hmac
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.database.session import get_db
from backend.app.models import Job
from backend.app.repositories.job_repos import TrackingRepository
from backend.app.schemas.api import JobDetail, JobOut


def require_api_key(
    x_api_key: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> None:
    """If API_KEY is set, every request must carry it. Off by default (local, 127.0.0.1)."""
    if settings.api_key and not hmac.compare_digest(x_api_key or "", settings.api_key):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")


def get_deps_factory(request: Request) -> Callable:
    from backend.app.services.search_runner import default_deps_factory

    return getattr(request.app.state, "deps_factory", default_deps_factory)


# scope="function": get_db's exit code (the COMMIT) runs right after the endpoint returns and
# BEFORE the response is sent. With the default scope the commit would run after the client
# already received "201 Created", so a failed commit would be silent and a quick follow-up
# request could read stale data. See tests/integration/test_commit_before_response.py.
DbSession = Depends(get_db, scope="function")


def job_to_out(job: Job, saved_ids: set[int], tracking: dict) -> JobOut:
    m = job.match
    t = tracking.get(job.id)
    return JobOut(
        id=job.id,
        title=job.title,
        company_name=job.company_name,
        location=job.location,
        employment_type=job.employment_type,
        workplace_type=job.workplace_type,
        published_at=job.published_at,
        first_seen_at=job.first_seen_at,
        application_url=job.application_url,
        source=job.source,
        is_active=job.is_active,
        score=m.score if m else 0.0,
        above_threshold=m.above_threshold if m else False,
        keyword_qualified=m.keyword_qualified if m else False,
        matched_keywords=m.matched_keywords if m else [],
        matched_skills=m.matched_skills if m else [],
        missing_skills=m.missing_skills if m else [],
        saved=job.id in saved_ids,
        tracking_status=t.status if t else None,
    )


def job_to_detail(job: Job, db: Session, highlighted: str) -> JobDetail:
    repo = TrackingRepository(db)
    base = job_to_out(job, repo.saved_ids(), repo.tracking_by_job())
    m = job.match
    return JobDetail(
        **base.model_dump(),
        description=job.description,
        highlighted_description=highlighted,
        experience_text=job.experience_text,
        excerpts=m.excerpts if m else [],
        explanation=m.explanation if m else "",
        score_breakdown=m.score_breakdown if m else {},
    )
