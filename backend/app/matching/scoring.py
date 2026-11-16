"""Hybrid relevance scoring.

Score = weighted average of five components, each in 0..1:

    skills      overlap between skills found in the job and skills on the resume
    semantic    calibrated cosine similarity of resume and job embeddings
    title       similarity of the job title to preferred / past job titles
    experience  fit between the resume's years of experience and the job's requirement
    keywords    how strongly the configured search keywords appear (title counts more)

The result is a 0-100 RELEVANCE score used to rank jobs. It is not a probability of
getting an interview or an offer. Components that cannot be computed (for example
resume-based ones when no resume was uploaded) are left out and the remaining weights
are re-normalised.

This module is pure: no DB, no network, no model loading. The embedding similarity is
passed in by the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LEVEL_WORDS = {
    "senior",
    "junior",
    "sr",
    "jr",
    "lead",
    "staff",
    "principal",
    "associate",
    "i",
    "ii",
    "iii",
    "iv",
    "intern",
    "trainee",
}
_TOKEN_RE = re.compile(r"[a-z0-9#+.]+")
_EXP_RANGE_RE = re.compile(r"(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I)
_EXP_MIN_RE = re.compile(
    r"(?:at\s+least|minimum\s+of|min\.?|over)?\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I
)


def parse_experience_requirement(text: str) -> tuple[float | None, float | None, str | None]:
    """Find 'N years' style requirements. Returns (min, max, matched_text)."""
    m = _EXP_RANGE_RE.search(text)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo <= hi <= 40:
            return lo, hi, m.group(0).strip()
    m = _EXP_MIN_RE.search(text)
    if m and 0 < float(m.group(1)) <= 40:
        return float(m.group(1)), None, m.group(0).strip()
    return None, None, None


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in LEVEL_WORDS}


def title_similarity(job_title: str, candidates: list[str]) -> float | None:
    if not candidates:
        return None
    job_tokens = _tokens(job_title)
    if not job_tokens:
        return 0.0
    best = 0.0
    for cand in candidates:
        cand_tokens = _tokens(cand)
        if not cand_tokens:
            continue
        overlap = len(job_tokens & cand_tokens)
        best = max(best, 2 * overlap / (len(job_tokens) + len(cand_tokens)))  # Dice coefficient
    return best


def experience_fit(years: float | None, req_min: float | None, req_max: float | None) -> float | None:
    if years is None or req_min is None:
        return None
    upper = req_max if req_max is not None else req_min + 5
    if years < req_min:
        return max(0.0, 1.0 - (req_min - years) / max(req_min, 1.0))
    if years <= upper:
        return 1.0
    return max(0.5, 1.0 - (years - upper) / 10.0)


def keyword_strength(matched: list[str], title_matched: list[str]) -> float:
    """Each matched keyword is worth 1 point, 1.5 if it is in the title; 3 points = 1.0."""
    points = sum(1.5 if k in title_matched else 1.0 for k in matched)
    return min(1.0, points / 3.0)


def calibrate_cosine(cos: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (cos - lo) / (hi - lo)))


@dataclass
class ScoreInput:
    job_title: str
    job_skills: list[str]
    matched_keywords: list[str]
    title_keywords: list[str]
    req_min_years: float | None = None
    req_max_years: float | None = None
    # resume side (None / empty when there is no resume)
    resume_skills: list[str] | None = None
    resume_years: float | None = None
    cosine: float | None = None
    cosine_range: tuple[float, float] = (0.10, 0.60)
    title_candidates: list[str] = field(default_factory=list)


@dataclass
class ScoreResult:
    score: float  # 0-100
    components: dict[str, float | None]
    weights_used: dict[str, float]
    matched_skills: list[str]
    missing_skills: list[str]
    resume_used: bool


def normalise_weights(weights: dict[str, float]) -> dict[str, float]:
    clean = {k: max(0.0, float(v)) for k, v in weights.items()}
    total = sum(clean.values())
    if total <= 0:
        raise ValueError("scoring weights must contain a positive value")
    return {k: v / total for k, v in clean.items()}


def compute_score(inp: ScoreInput, weights: dict[str, float]) -> ScoreResult:
    resume_skill_set = {s.lower() for s in (inp.resume_skills or [])}
    matched = [s for s in inp.job_skills if s.lower() in resume_skill_set]
    missing = [s for s in inp.job_skills if s.lower() not in resume_skill_set]
    has_resume = inp.resume_skills is not None

    components: dict[str, float | None] = {
        "skills": (len(matched) / len(inp.job_skills)) if has_resume and inp.job_skills else None,
        "semantic": calibrate_cosine(inp.cosine, *inp.cosine_range) if inp.cosine is not None else None,
        "title": title_similarity(inp.job_title, inp.title_candidates),
        "experience": experience_fit(inp.resume_years, inp.req_min_years, inp.req_max_years),
        "keywords": keyword_strength(inp.matched_keywords, inp.title_keywords),
    }
    available = {k: v for k, v in components.items() if v is not None}
    w = normalise_weights({k: weights.get(k, 0.0) for k in available})
    score = sum(available[k] * w[k] for k in available) * 100 if w else 0.0
    return ScoreResult(
        score=round(score, 1),
        components={k: (round(v, 3) if v is not None else None) for k, v in components.items()},
        weights_used={k: round(v, 3) for k, v in w.items()},
        matched_skills=matched,
        missing_skills=missing,
        resume_used=has_resume,
    )


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def pick_excerpts(description: str, terms: list[str], limit: int = 3, width: int = 300) -> list[str]:
    """Sentences from the description that mention a matched keyword or skill."""
    if not description or not terms:
        return []
    from backend.app.matching.keyword_matcher import compile_term

    patterns = [compile_term(t) for t in terms]
    excerpts: list[str] = []
    for sentence in _SENTENCE_RE.split(description):
        s = sentence.strip()
        if len(s) < 15:
            continue
        if any(p.search(s) for p in patterns):
            excerpts.append(s if len(s) <= width else s[: width - 1].rstrip() + "…")
            if len(excerpts) >= limit:
                break
    return excerpts


def build_explanation(result: ScoreResult, matched_keywords: list[str], threshold: float | None) -> str:
    parts: list[str] = []
    if matched_keywords:
        parts.append("Qualified by keyword(s): " + ", ".join(matched_keywords) + ".")
    if result.resume_used:
        if result.matched_skills:
            parts.append("Your resume matches " + ", ".join(result.matched_skills[:8]) + ".")
        if result.missing_skills:
            parts.append("Not found on your resume: " + ", ".join(result.missing_skills[:8]) + ".")
    else:
        parts.append("No resume uploaded, so the score uses keywords and titles only.")
    strong = sorted(
        ((k, v) for k, v in result.components.items() if v is not None),
        key=lambda kv: kv[1],
        reverse=True,
    )
    if strong:
        top = ", ".join(f"{k} {int(v * 100)}%" for k, v in strong[:3])
        parts.append(f"Strongest signals: {top}.")
    parts.append(f"Relevance score {result.score:.0f}/100 (a ranking aid, not a hiring probability).")
    if threshold is not None and result.score < threshold:
        parts.append(f"Below your {threshold:.0f}% AI threshold, but kept because a keyword matched.")
    return " ".join(parts)
