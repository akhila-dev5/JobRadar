"""Companies, keywords and preferences endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from backend.app.api.deps import DbSession, get_deps_factory
from backend.app.collectors import CollectorError, CompanyTarget, get_collector
from backend.app.matching.keyword_matcher import KeywordMatcher, KeywordRule
from backend.app.repositories.config_repos import (
    CompanyRepository,
    KeywordRepository,
    PreferenceRepository,
)
from backend.app.schemas.api import (
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

companies = APIRouter(prefix="/companies", tags=["companies"])
keywords = APIRouter(prefix="/keywords", tags=["keywords"])
preferences = APIRouter(prefix="/preferences", tags=["preferences"])


# ------------------------------------------------------------------ companies
@companies.get("", response_model=list[CompanyOut])
def list_companies(db: Session = DbSession):
    return CompanyRepository(db).list()


@companies.post("", response_model=CompanyOut, status_code=201)
def create_company(body: CompanyIn, db: Session = DbSession):
    return CompanyRepository(db).create(**body.model_dump())


@companies.get("/export")
def export(format: str = Query("json", pattern="^(json|csv)$"), db: Session = DbSession):
    content = export_companies(CompanyRepository(db).list(), format)
    media = "application/json" if format == "json" else "text/csv"
    return PlainTextResponse(content, media_type=media)


@companies.post("/import", response_model=ImportSummary)
async def import_file(
    format: str = Query("json", pattern="^(json|csv)$"),
    file: UploadFile = File(...),
    db: Session = DbSession,
):
    raw = await file.read(1_000_001)
    if len(raw) > 1_000_000:
        return ImportSummary(created=0, updated=0, errors=["File is larger than 1 MB."])
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ImportSummary(created=0, updated=0, errors=["File must be UTF-8 text."])
    return import_companies(db, text, format)


@companies.patch("/{company_id}", response_model=CompanyOut)
def update_company(company_id: int, body: CompanyUpdate, db: Session = DbSession):
    return CompanyRepository(db).update(company_id, **body.model_dump(exclude_unset=True))


@companies.delete("/{company_id}", status_code=204)
def delete_company(company_id: int, db: Session = DbSession):
    CompanyRepository(db).delete(company_id)
    return Response(status_code=204)


@companies.post("/{company_id}/test", response_model=CompanyTestResult)
def test_company(company_id: int, db: Session = DbSession, factory=Depends(get_deps_factory)):
    """Fetch the board once to verify platform + board token. Stores nothing."""
    company = CompanyRepository(db).get(company_id)
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
