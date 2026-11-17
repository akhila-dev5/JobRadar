"""Repositories for user-editable configuration: companies, keywords, preferences."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.names import name_key
from backend.app.database.base import utcnow
from backend.app.models import Company, JobPreference, SearchKeyword


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


class CompanyRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(self) -> list[Company]:
        return list(self.db.scalars(select(Company).order_by(func.lower(Company.name))))

    def get(self, company_id: int) -> Company:
        obj = self.db.get(Company, company_id)
        if obj is None:
            raise NotFound(f"Company {company_id} not found")
        return obj

    def find_by_name(self, name: str) -> Company | None:
        """Exact (case-insensitive) match first, then the same company spelled differently
        ("Stripe" vs "Stripe, Inc."). Companies are few, so comparing keys in Python is fine."""
        exact = self.db.scalar(select(Company).where(func.lower(Company.name) == name.lower()))
        if exact is not None:
            return exact
        key = name_key(name)
        if not key:
            return None
        return next((c for c in self.list() if name_key(c.name) == key), None)

    def enabled(self, ids: list[int] | None = None) -> list[Company]:
        q = select(Company).where(Company.enabled.is_(True))
        if ids:
            q = q.where(Company.id.in_(ids))
        return list(self.db.scalars(q.order_by(Company.name)))

    def pending(self, ids: list[int] | None = None) -> list[Company]:
        """Companies still waiting for their career board to be discovered."""
        q = select(Company).where(Company.discovery_status == "pending")
        if ids:
            q = q.where(Company.id.in_(ids))
        return list(self.db.scalars(q.order_by(Company.id)))

    def _check_unique(
        self, name: str, platform: str | None, token: str | None, exclude_id: int | None
    ) -> None:
        candidates = [self.find_by_name(name)]
        if platform and token:  # companies without a board yet cannot collide on it
            candidates.append(
                self.db.scalar(
                    select(Company).where(Company.platform == platform, Company.board_token == token)
                )
            )
        for existing in candidates:
            if existing is not None and existing.id != exclude_id:
                raise Conflict(f"A company with this name or board already exists ({existing.name}).")

    def create(self, **data) -> Company:
        """Name-only companies start 'pending' (discovery fills in the board); a given
        platform + token means the user chose the board, so it is 'manual'."""
        data.setdefault("platform", None)
        data.setdefault("board_token", None)
        self._check_unique(data["name"], data["platform"], data["board_token"], None)
        data["discovery_status"] = "manual" if data["platform"] else "pending"
        obj = Company(**data)
        self.db.add(obj)
        self.db.flush()
        return obj

    def update(self, company_id: int, **data) -> Company:
        obj = self.get(company_id)
        name = data.get("name", obj.name)
        platform = data.get("platform", obj.platform)
        token = data.get("board_token", obj.board_token)
        self._check_unique(name, platform, token, obj.id)
        board_changed = ("platform" in data and data["platform"] != obj.platform) or (
            "board_token" in data and data["board_token"] != obj.board_token
        )
        for key, value in data.items():
            setattr(obj, key, value)
        if board_changed and obj.platform and obj.board_token:
            obj.discovery_status = "manual"  # the user picked this board explicitly
            obj.last_error = None
        self.db.flush()
        return obj

    def delete(self, company_id: int) -> None:
        self.db.delete(self.get(company_id))
        self.db.flush()

    def record_search(self, company: Company, *, ok: bool, count: int, error: str | None) -> None:
        now = utcnow()
        company.last_search_at = now
        if ok:
            company.last_success_at = now
            company.jobs_collected = count
            company.last_error = None
        else:
            company.last_error = (error or "unknown error")[:1000]
        self.db.flush()


class KeywordRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(self) -> list[SearchKeyword]:
        return list(self.db.scalars(select(SearchKeyword).order_by(func.lower(SearchKeyword.keyword))))

    def enabled(self) -> list[SearchKeyword]:
        return list(self.db.scalars(select(SearchKeyword).where(SearchKeyword.enabled.is_(True))))

    def get(self, keyword_id: int) -> SearchKeyword:
        obj = self.db.get(SearchKeyword, keyword_id)
        if obj is None:
            raise NotFound(f"Keyword {keyword_id} not found")
        return obj

    def _dupe(self, keyword: str, exclude_id: int | None) -> None:
        existing = self.db.scalar(
            select(SearchKeyword).where(func.lower(SearchKeyword.keyword) == keyword.lower())
        )
        if existing is not None and existing.id != exclude_id:
            raise Conflict(f"Keyword '{keyword}' already exists.")

    def create(self, keyword: str, aliases: list[str], enabled: bool = True) -> SearchKeyword:
        self._dupe(keyword, None)
        obj = SearchKeyword(keyword=keyword, aliases=aliases, enabled=enabled)
        self.db.add(obj)
        self.db.flush()
        return obj

    def update(self, keyword_id: int, **data) -> SearchKeyword:
        obj = self.get(keyword_id)
        if "keyword" in data:
            self._dupe(data["keyword"], obj.id)
        for key, value in data.items():
            setattr(obj, key, value)
        self.db.flush()
        return obj

    def delete(self, keyword_id: int) -> None:
        self.db.delete(self.get(keyword_id))
        self.db.flush()


class PreferenceRepository:
    """The single preferences row (id=1), created on first access."""

    def __init__(self, db: Session):
        self.db = db

    def get(self) -> JobPreference:
        obj = self.db.get(JobPreference, 1)
        if obj is None:
            obj = JobPreference(id=1)
            self.db.add(obj)
            self.db.flush()
        return obj

    def update(self, **data) -> JobPreference:
        obj = self.get()
        for key, value in data.items():
            setattr(obj, key, value)
        self.db.flush()
        return obj
