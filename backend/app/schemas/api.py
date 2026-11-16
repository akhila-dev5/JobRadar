"""Pydantic request/response models: the contract of the REST API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Platform = Literal["greenhouse", "lever", "ashby"]
Status = Literal["discovered", "interested", "applied", "interviewing", "rejected", "offer_received"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _clean_list(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        v = " ".join(str(v).split())
        if v and v.lower() not in {o.lower() for o in out}:
            out.append(v)
    return out


# ------------------------------------------------------------- companies
class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    platform: Platform
    board_token: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.\-]+$")
    api_region: Literal["us", "eu"] = "us"
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name must not be blank")
        return v


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    platform: Platform | None = None
    board_token: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.\-]+$")
    api_region: Literal["us", "eu"] | None = None
    enabled: bool | None = None


class CompanyOut(ORMModel):
    id: int
    name: str
    platform: str
    board_token: str
    api_region: str
    enabled: bool
    last_search_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    jobs_collected: int


class ImportSummary(BaseModel):
    created: int
    updated: int
    errors: list[str]


class CompanyTestResult(BaseModel):
    ok: bool
    job_count: int = 0
    skipped: int = 0
    message: str = ""


# ------------------------------------------------------------- keywords
class KeywordIn(BaseModel):
    keyword: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("keyword")
    @classmethod
    def _kw(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("keyword must not be blank")
        return v

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, v: list[str]) -> list[str]:
        return _clean_list(v)


class KeywordUpdate(BaseModel):
    keyword: str | None = Field(default=None, min_length=1, max_length=120)
    aliases: list[str] | None = None
    enabled: bool | None = None

    @field_validator("keyword")
    @classmethod
    def _kw(cls, v: str | None) -> str | None:
        return " ".join(v.split()) if v else v

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, v: list[str] | None) -> list[str] | None:
        return _clean_list(v) if v is not None else v


class KeywordOut(ORMModel):
    id: int
    keyword: str
    aliases: list[str]
    enabled: bool


class KeywordTestIn(BaseModel):
    title: str = ""
    description: str = ""


class KeywordTestOut(BaseModel):
    qualified: bool
    matched_keywords: list[str]
    highlighted_title: str
    highlighted_description: str


# ------------------------------------------------------------- preferences
class PreferencesIn(BaseModel):
    preferred_titles: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    work_modes: list[Literal["remote", "hybrid", "onsite"]] = Field(default_factory=list)
    min_experience: float | None = Field(default=None, ge=0, le=60)
    max_experience: float | None = Field(default=None, ge=0, le=60)
    employment_types: list[str] = Field(default_factory=list)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, max_length=10)
    ai_threshold_enabled: bool = True
    ai_threshold: float = Field(default=40.0, ge=0, le=100)
    scoring_weights: dict[str, float] | None = None
    email_enabled: bool = False
    email_to: str | None = Field(default=None, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @field_validator("preferred_titles", "preferred_locations", "employment_types")
    @classmethod
    def _lists(cls, v: list[str]) -> list[str]:
        return _clean_list(v)

    @field_validator("scoring_weights")
    @classmethod
    def _weights(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        if v is None:
            return v
        allowed = {"skills", "semantic", "title", "experience", "keywords"}
        if set(v) - allowed:
            raise ValueError(f"unknown weight keys: {sorted(set(v) - allowed)}")
        if any(x < 0 for x in v.values()) or sum(v.values()) <= 0:
            raise ValueError("weights must be non-negative with a positive total")
        return v

    @model_validator(mode="after")
    def _cross_checks(self) -> PreferencesIn:
        if (
            self.min_experience is not None
            and self.max_experience is not None
            and self.min_experience > self.max_experience
        ):
            raise ValueError("min_experience cannot exceed max_experience")
        if self.salary_min is not None and self.salary_max is not None and self.salary_min > self.salary_max:
            raise ValueError("salary_min cannot exceed salary_max")
        if self.email_enabled and not self.email_to:
            raise ValueError("email_to is required when email notifications are enabled")
        return self


class PreferencesOut(ORMModel):
    preferred_titles: list[str]
    preferred_locations: list[str]
    work_modes: list[str]
    min_experience: float | None
    max_experience: float | None
    employment_types: list[str]
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    ai_threshold_enabled: bool
    ai_threshold: float
    scoring_weights: dict[str, float] | None
    email_enabled: bool
    email_to: str | None


# ------------------------------------------------------------- resume
class SkillOut(ORMModel):
    name: str
    category: str
    source: str


class ResumeOut(ORMModel):
    id: int
    label: str
    original_filename: str
    is_active: bool
    job_titles: list[str]
    education: list[str]
    certifications: list[str]
    experience_years: float | None
    skills: list[SkillOut]
    created_at: datetime


class SkillAdd(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = "other"


class ResumeProfileUpdate(BaseModel):
    job_titles: list[str] | None = None
    education: list[str] | None = None
    certifications: list[str] | None = None
    experience_years: float | None = Field(default=None, ge=0, le=60)


# ------------------------------------------------------------- jobs
class JobOut(BaseModel):
    id: int
    title: str
    company_name: str
    location: str | None
    employment_type: str | None
    workplace_type: str | None
    published_at: datetime | None
    first_seen_at: datetime
    application_url: str
    source: str
    is_active: bool
    score: float
    above_threshold: bool
    keyword_qualified: bool
    matched_keywords: list[str]
    matched_skills: list[str]
    missing_skills: list[str]
    saved: bool = False
    tracking_status: str | None = None


class JobDetail(JobOut):
    description: str
    highlighted_description: str
    experience_text: str | None
    excerpts: list[str]
    explanation: str
    score_breakdown: dict


class JobPage(BaseModel):
    total: int
    items: list[JobOut]


class DashboardStats(BaseModel):
    stored_jobs: int
    qualified_jobs: int
    above_threshold: int
    new_jobs: int
    companies_monitored: int
    last_success_at: datetime | None
    last_search_status: str | None
    ai_threshold_enabled: bool
    ai_threshold: float


# ------------------------------------------------------------- tracking
class TrackingIn(BaseModel):
    status: Status = "interested"
    notes: str | None = Field(default=None, max_length=5000)
    applied_date: date | None = None


class TrackingOut(ORMModel):
    job_id: int
    status: str
    notes: str | None
    applied_date: date | None
    updated_at: datetime


class TrackedJob(BaseModel):
    job: JobOut
    tracking: TrackingOut


# ------------------------------------------------------------- search
class SearchRequest(BaseModel):
    company_ids: list[int] | None = None  # None / empty = all enabled companies


class SearchOut(ORMModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    trigger: str
    companies_searched: int
    jobs_fetched: int
    new_jobs: int
    qualified_jobs: int
    errors: list[str]
