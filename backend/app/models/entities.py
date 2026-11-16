"""SQLAlchemy ORM models. See docs/09-database-design.md for the ER diagram.

Single-user application: there is no users table, so no user_id columns.
JSON columns hold small lists (aliases, preferred titles...) that are always read
and written as a whole; they stay portable between PostgreSQL and the SQLite used
by the unit tests.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.base import Base, TimestampMixin, utcnow

PLATFORMS = ("greenhouse", "lever", "ashby")
APPLICATION_STATUSES = (
    "discovered",
    "interested",
    "applied",
    "interviewing",
    "rejected",
    "offer_received",
)


class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    platform: Mapped[str] = mapped_column(String(30))
    board_token: Mapped[str] = mapped_column(String(200))
    api_region: Mapped[str] = mapped_column(String(10), default="us")  # lever: us | eu
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_search_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    jobs_collected: Mapped[int] = mapped_column(Integer, default=0)

    jobs: Mapped[list["Job"]] = relationship(back_populates="company")

    __table_args__ = (UniqueConstraint("platform", "board_token", name="uq_company_board"),)


class SearchKeyword(TimestampMixin, Base):
    __tablename__ = "search_keywords"

    id: Mapped[int] = mapped_column(primary_key=True)
    keyword: Mapped[str] = mapped_column(String(120), unique=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class JobPreference(TimestampMixin, Base):
    """Exactly one row (id=1) in this single-user app."""

    __tablename__ = "job_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    preferred_titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    work_modes: Mapped[list[str]] = mapped_column(JSON, default=list)  # remote/hybrid/onsite
    min_experience: Mapped[float | None] = mapped_column(Float)
    max_experience: Mapped[float | None] = mapped_column(Float)
    employment_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(10))
    ai_threshold_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_threshold: Mapped[float] = mapped_column(Float, default=40.0)
    scoring_weights: Mapped[dict | None] = mapped_column(JSON)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    email_to: Mapped[str | None] = mapped_column(String(320))


class Resume(TimestampMixin, Base):
    """Extracted profile only. The original file stays on the local disk."""

    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    original_filename: Mapped[str] = mapped_column(String(300))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    job_titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    education: Mapped[list[str]] = mapped_column(JSON, default=list)
    certifications: Mapped[list[str]] = mapped_column(JSON, default=list)
    experience_years: Mapped[float | None] = mapped_column(Float)
    profile_text: Mapped[str] = mapped_column(Text, default="")  # condensed, capped

    skills: Mapped[list["ResumeSkill"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
        lazy="selectin",  # responses are serialised after the session closes
    )


class ResumeSkill(Base):
    __tablename__ = "resume_skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40), default="other")
    source: Mapped[str] = mapped_column(String(10), default="auto")  # auto | manual

    resume: Mapped[Resume] = relationship(back_populates="skills")

    __table_args__ = (UniqueConstraint("resume_id", "name", name="uq_resume_skill"),)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30))
    external_id: Mapped[str] = mapped_column(String(200))
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    company_name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str | None] = mapped_column(String(500))
    employment_type: Mapped[str | None] = mapped_column(String(100))
    workplace_type: Mapped[str | None] = mapped_column(String(30))
    experience_text: Mapped[str | None] = mapped_column(String(200))
    min_experience_years: Mapped[float | None] = mapped_column(Float)
    max_experience_years: Mapped[float | None] = mapped_column(Float)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    application_url: Mapped[str] = mapped_column(String(1000))
    content_hash: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[Company | None] = relationship(back_populates="jobs")
    match: Mapped["JobMatch | None"] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_job_source_external"),
        Index("ix_jobs_first_seen", "first_seen_at"),
        Index("ix_jobs_active_company", "is_active", "company_id"),
    )


class JobMatch(Base):
    __tablename__ = "job_matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    keyword_qualified: Mapped[bool] = mapped_column(Boolean, default=False)
    matched_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    score: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    matched_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    excerpts: Mapped[list[str]] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    above_threshold: Mapped[bool] = mapped_column(Boolean, default=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="match")

    __table_args__ = (Index("ix_job_matches_qualified_score", "keyword_qualified", "score"),)


class SavedJob(Base):
    __tablename__ = "saved_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApplicationTracking(TimestampMixin, Base):
    __tablename__ = "application_tracking"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="interested", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    applied_date: Mapped[date | None] = mapped_column(Date)


class SearchHistory(Base):
    __tablename__ = "search_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|success|partial|failed
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    companies_searched: Mapped[int] = mapped_column(Integer, default=0)
    jobs_fetched: Mapped[int] = mapped_column(Integer, default=0)
    new_jobs: Mapped[int] = mapped_column(Integer, default=0)
    qualified_jobs: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[str]] = mapped_column(JSON, default=list)


class NotificationHistory(Base):
    __tablename__ = "notification_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(20), default="email")
    status: Mapped[str] = mapped_column(String(20), default="sent")  # sent | failed
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("job_id", "channel", name="uq_notification_job_channel"),)


class EmbeddingCache(Base):
    """Embeddings keyed by (text hash, model). Avoids recomputing unchanged jobs."""

    __tablename__ = "embedding_cache"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_name: Mapped[str] = mapped_column(String(120), primary_key=True)
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)  # float32 bytes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
