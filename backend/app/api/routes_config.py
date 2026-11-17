"""Companies, keywords and preferences endpoints."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, Response, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from backend.app.api.deps import DbSession, get_deps_factory
from backend.app.collectors import CollectorError, CompanyTarget, get_collector
from backend.app.matching.keyword_matcher import KeywordMatcher, KeywordRule
from backend.app.repositories.config_repos import (
    CompanyRepository,
    Conflict,
    KeywordRepository,
    PreferenceRepository,
)
from backend.app.schemas.api import (
    BulkResult,
    CompanyBulkIn,
    CompanyIn,
    CompanyOut,
    CompanyTestResult,
    CompanyUpdate,
    ImportSummary,
    KeywordIn,
    KeywordOut,
    KeywordTestIn,
    KeywordTestOut,
    KeywordUpdate,
    PreferencesIn,
    PreferencesOut,
)
from backend.app.services.company_io import export_companies, import_companies
from backend.app.services.discovery_runner import run_discovery

companies = APIRouter(prefix="/companies", tags=["companies"])
keywords = APIRouter(prefix="/keywords", tags=["keywords"])
preferences = APIRouter(prefix="/preferences", tags=["preferences"])


# ------------------------------------------------------------------ companies
@companies.get("", response_model=list[CompanyOut])
def list_companies(db: Session = DbSession):
    return CompanyRepository(db).list()


@companies.post("", response_model=CompanyOut, status_code=201)
def create_company(
    body: CompanyIn,
    background: BackgroundTasks,
    db: Session = DbSession,
    factory=Depends(get_deps_factory),
):
    """Add one company. With just a name, its job board is discovered in the background."""
    data = body.model_dump()
    data.pop("careers_url", None)
    company = CompanyRepository(db).create(**data)
    if company.discovery_status == "pending":
        background.add_task(run_discovery, [company.id], factory)
    return company


@companies.post("/bulk", response_model=BulkResult, status_code=201)
def create_companies_bulk(
    body: CompanyBulkIn,
    background: BackgroundTasks,
    db: Session = DbSession,
    factory=Depends(get_deps_factory),
):
    """Add many companies from a list of names; boards are discovered in the background."""
    repo = CompanyRepository(db)
    created, skipped = [], []
    for name in body.names:
        try:
            created.append(repo.create(name=name))
        except Conflict:
            skipped.append(name)
    if created:
        background.add_task(run_discovery, [c.id for c in created], factory)
    return BulkResult(created=created, skipped=skipped)


@companies.get("/export")
def export(format: str = Query("json", pattern="^(json|csv)$"), db: Session = DbSession):
    content = export_companies(CompanyRepository(db).list(), format)
    media = "application/json" if format == "json" else "text/csv"
    return PlainTextResponse(content, media_type=media)


@companies.post("/import", response_model=ImportSummary)
async def import_file(
    background: BackgroundTasks,
    format: str = Query("json", pattern="^(json|csv)$"),
    file: UploadFile = File(...),
    db: Session = DbSession,
    factory=Depends(get_deps_factory),
):
    raw = await file.read(1_000_001)
    if len(raw) > 1_000_000:
        return ImportSummary(created=0, updated=0, errors=["File is larger than 1 MB."])
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ImportSummary(created=0, updated=0, errors=["File must be UTF-8 text."])
    summary = import_companies(db, text, format)
    if summary["new_pending"]:
        background.add_task(run_discovery, summary["new_pending"], factory)
    return ImportSummary(**{k: v for k, v in summary.items() if k != "new_pending"})


@companies.patch("/{company_id}", response_model=CompanyOut)
def update_company(company_id: int, body: CompanyUpdate, db: Session = DbSession):
    data = body.model_dump(exclude_unset=True)
    data.pop("careers_url", None)  # already translated into platform/board_token/api_region
    return CompanyRepository(db).update(company_id, **data)


@companies.post("/{company_id}/discover", response_model=CompanyOut)
def rediscover_company(
    company_id: int,
    background: BackgroundTasks,
    db: Session = DbSession,
    factory=Depends(get_deps_factory),
):
    """Forget the current board and look for the company's job board again."""
    company = CompanyRepository(db).get(company_id)
    company.platform = company.board_token = None
    company.discovery_status = "pending"
    company.last_error = None
    background.add_task(run_discovery, [company.id], factory)
    return company


@companies.delete("/{company_id}", status_code=204)
def delete_company(company_id: int, db: Session = DbSession):
    CompanyRepository(db).delete(company_id)
    return Response(status_code=204)


@companies.post("/{company_id}/test", response_model=CompanyTestResult)
def test_company(company_id: int, db: Session = DbSession, factory=Depends(get_deps_factory)):
    """Fetch the board once to verify platform + board token. Stores nothing."""
    company = CompanyRepository(db).get(company_id)
    if not company.platform or not company.board_token:
        return CompanyTestResult(ok=False, message="No job board known yet for this company.")
    http = factory().http
    try:
        collector = get_collector(company.platform, http)
        jobs = collector.fetch_jobs(CompanyTarget(company.name, company.board_token, company.api_region))
        return CompanyTestResult(
            ok=True,
            job_count=len(jobs),
            skipped=collector.skipped,
            message=f"Board reachable: {len(jobs)} open jobs.",
        )
    except CollectorError as exc:
        return CompanyTestResult(ok=False, message=str(exc))
    finally:
        http.close()


# ------------------------------------------------------------------ keywords
@keywords.get("", response_model=list[KeywordOut])
def list_keywords(db: Session = DbSession):
    return KeywordRepository(db).list()


@keywords.post("", response_model=KeywordOut, status_code=201)
def create_keyword(body: KeywordIn, db: Session = DbSession):
    return KeywordRepository(db).create(body.keyword, body.aliases, body.enabled)


@keywords.patch("/{keyword_id}", response_model=KeywordOut)
def update_keyword(keyword_id: int, body: KeywordUpdate, db: Session = DbSession):
    return KeywordRepository(db).update(keyword_id, **body.model_dump(exclude_unset=True))


@keywords.delete("/{keyword_id}", status_code=204)
def delete_keyword(keyword_id: int, db: Session = DbSession):
    KeywordRepository(db).delete(keyword_id)
    return Response(status_code=204)


@keywords.post("/test", response_model=KeywordTestOut)
def test_keywords(body: KeywordTestIn, db: Session = DbSession):
    """Dry run: which enabled keywords would match this title/description?"""
    rules = [KeywordRule(k.keyword, tuple(k.aliases or ())) for k in KeywordRepository(db).enabled()]
    matcher = KeywordMatcher(rules)
    result = matcher.match(body.title, body.description)
    return KeywordTestOut(
        qualified=result.qualified,
        matched_keywords=result.matched_keywords,
        highlighted_title=matcher.highlight(body.title),
        highlighted_description=matcher.highlight(body.description),
    )


# ------------------------------------------------------------------ preferences
@preferences.get("", response_model=PreferencesOut)
def get_preferences(db: Session = DbSession):
    return PreferenceRepository(db).get()


@preferences.put("", response_model=PreferencesOut)
def put_preferences(body: PreferencesIn, db: Session = DbSession):
    return PreferenceRepository(db).update(**body.model_dump())
