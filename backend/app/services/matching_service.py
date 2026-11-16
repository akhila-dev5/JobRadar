"""Matching service: turns (job, resume, keywords) into a stored JobMatch.

Orchestrates embeddings (with a DB cache) and the pure scoring functions.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.matching.embeddings import Embedder
from backend.app.matching.keyword_matcher import MatchResult
from backend.app.matching.scoring import (
    ScoreInput,
    build_explanation,
    compute_score,
    pick_excerpts,
)
from backend.app.matching.skills import get_skill_extractor
from backend.app.models import Job, JobPreference, Resume
from backend.app.repositories.job_repos import EmbeddingCacheRepository, JobRepository

logger = logging.getLogger(__name__)
JOB_TEXT_CHARS = 2000  # MiniLM reads ~256 tokens; more text only costs CPU time


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def job_embedding_text(job: Job) -> str:
    return f"{job.title}. {job.description[:JOB_TEXT_CHARS]}"


@dataclass
class MatchContext:
    resume: Resume | None
    prefs: JobPreference
    weights: dict[str, float]


class MatchingService:
    def __init__(self, db: Session, embedder: Embedder, settings: Settings):
        self.db = db
        self.embedder = embedder
        self.settings = settings
        self.cache = EmbeddingCacheRepository(db)
        self.jobs = JobRepository(db)

    def build_context(self, resume: Resume | None, prefs: JobPreference) -> MatchContext:
        weights = dict(self.settings.scoring_weights)
        if prefs.scoring_weights:
            weights.update(prefs.scoring_weights)
        return MatchContext(resume=resume, prefs=prefs, weights=weights)

    # ---- embeddings with cache -------------------------------------------
    def _embed(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        if not self.embedder.cacheable:
            return list(self.embedder.encode(texts))
        hashes = [_digest(t) for t in texts]
        cached = self.cache.get_many(list(set(hashes)), self.embedder.name)
        missing = {h: t for h, t in zip(hashes, texts, strict=True) if h not in cached}
        if missing:
            vectors = self.embedder.encode(list(missing.values()))
            fresh = dict(zip(missing.keys(), vectors, strict=True))
            self.cache.put_many(fresh, self.embedder.name)
            cached.update(fresh)
            logger.info("Embedded %d new texts (%d from cache)", len(missing), len(texts) - len(missing))
        return [cached[h] for h in hashes]

    # ---- main entry -----------------------------------------------------
    def score_and_store(self, items: list[tuple[Job, MatchResult]], ctx: MatchContext) -> None:
        if not items:
            return
        extractor = get_skill_extractor()
        resume = ctx.resume
        resume_vec: np.ndarray | None = None
        job_vecs: list[np.ndarray | None] = [None] * len(items)
        if resume is not None and resume.profile_text:
            vectors = self._embed([resume.profile_text] + [job_embedding_text(j) for j, _ in items])
            resume_vec, job_vecs = vectors[0], list(vectors[1:])

        title_candidates = list(ctx.prefs.preferred_titles or [])
        resume_skills = [s.name for s in resume.skills] if resume is not None else None
        threshold = ctx.prefs.ai_threshold if ctx.prefs.ai_threshold_enabled else None

        for (job, kw), jvec in zip(items, job_vecs, strict=True):
            cos = None
            if resume_vec is not None and jvec is not None:
                denom = float(np.linalg.norm(resume_vec) * np.linalg.norm(jvec))
                cos = float(np.dot(resume_vec, jvec) / denom) if denom else 0.0
            job_skills = [s.name for s in extractor.extract(f"{job.title}\n{job.description}")]
            result = compute_score(
                ScoreInput(
                    job_title=job.title,
                    job_skills=job_skills,
                    matched_keywords=kw.matched_keywords,
                    title_keywords=kw.title_keywords,
                    req_min_years=job.min_experience_years,
                    req_max_years=job.max_experience_years,
                    resume_skills=resume_skills,
                    resume_years=resume.experience_years if resume is not None else None,
                    cosine=cos,
                    cosine_range=self.embedder.calibration,
                    title_candidates=title_candidates + (list(resume.job_titles) if resume else []),
                ),
                ctx.weights,
            )
            self.jobs.save_match(
                job,
                resume_id=resume.id if resume is not None else None,
                keyword_qualified=True,
                matched_keywords=kw.matched_keywords,
                score=result.score,
                score_breakdown={
                    "components": result.components,
                    "weights": result.weights_used,
                    "embedder": self.embedder.name,
                    "cosine": round(cos, 4) if cos is not None else None,
                },
                matched_skills=result.matched_skills,
                missing_skills=result.missing_skills,
                excerpts=pick_excerpts(job.description, kw.matched_keywords + result.matched_skills),
                explanation=build_explanation(result, kw.matched_keywords, threshold),
                above_threshold=(threshold is None) or result.score >= threshold,
            )
