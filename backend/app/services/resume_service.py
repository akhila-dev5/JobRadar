"""Resume use-cases: upload, manual correction, deletion.

The original file is saved only under RESUME_DIR on this machine (gitignored).
The database receives the extracted profile, never the file itself.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.matching.skills import get_skill_extractor
from backend.app.models import Resume
from backend.app.repositories.job_repos import ResumeRepository
from backend.app.services.resume_parser import (
    ResumeError,
    extract_text,
    parse_resume_text,
    validate_upload,
)

logger = logging.getLogger(__name__)


def _local_path(settings: Settings, file_hash: str, filename: str) -> Path:
    ext = Path(filename).suffix.lower()
    return Path(settings.resume_dir) / f"{file_hash[:16]}{ext}"


class ResumeService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings
        self.repo = ResumeRepository(db)

    def upload(self, filename: str, data: bytes, label: str | None = None) -> Resume:
        kind = validate_upload(filename, data, self.settings.max_upload_bytes)
        file_hash = hashlib.sha256(data).hexdigest()

        for existing in self.repo.list():
            if existing.file_hash == file_hash:
                self.repo.activate(existing)
                return existing  # same file uploaded again: just make it active

        text = extract_text(kind, data)
        parsed = parse_resume_text(text)

        path = _local_path(self.settings, file_hash, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

        resume = self.repo.create(
            Resume(
                label=(label or Path(filename).stem)[:200],
                original_filename=Path(filename).name[:300],
                file_hash=file_hash,
                job_titles=parsed.job_titles,
                education=parsed.education,
                certifications=parsed.certifications,
                experience_years=parsed.experience_years,
                profile_text=parsed.profile_text,
            )
        )
        for name, category in parsed.skills:
            self.repo.add_skill(resume, name, category, "auto")
        self.repo.activate(resume)
        logger.info("Parsed resume %s: %d skills", resume.original_filename, len(parsed.skills))
        return resume

    def add_skill(self, resume: Resume, name: str, category: str = "other") -> None:
        name = " ".join(name.split())
        if not name:
            raise ResumeError("Skill name must not be blank.")
        known = get_skill_extractor().category_of
        canonical = next((k for k in known if k.lower() == name.lower()), name)
        self.repo.add_skill(resume, canonical, known.get(canonical, category), "manual")
        self._refresh_profile_text(resume)

    def remove_skill(self, resume: Resume, name: str) -> bool:
        removed = self.repo.remove_skill(resume, name)
        if removed:
            self._refresh_profile_text(resume)
        return removed

    def update_profile(self, resume: Resume, **fields) -> Resume:
        for key, value in fields.items():
            if value is not None:
                setattr(resume, key, value)
        self._refresh_profile_text(resume)
        return resume

    def _refresh_profile_text(self, resume: Resume) -> None:
        """Rebuild the condensed embedding text after manual edits."""
        parts = []
        if resume.job_titles:
            parts.append("Titles: " + ", ".join(resume.job_titles))
        if resume.skills:
            parts.append("Skills: " + ", ".join(s.name for s in resume.skills))
        resume.profile_text = ". ".join(parts)[:4000]
        self.db.flush()

    def delete(self, resume: Resume, delete_local_file: bool = False) -> None:
        path = _local_path(self.settings, resume.file_hash, resume.original_filename)
        self.repo.delete(resume)
        if delete_local_file:
            path.unlink(missing_ok=True)
