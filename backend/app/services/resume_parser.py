"""Resume parsing: bytes -> validated text -> structured profile.

Pure functions with no database access, so they are easy to unit test.
The parser is heuristic (regex + a skill dictionary), which is explainable and
cheap on CPU. Anything it gets wrong can be corrected by hand in the UI.
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from backend.app.matching.skills import get_skill_extractor

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"  # .docx is a zip container
MAX_TEXT_CHARS = 200_000
PROFILE_TEXT_CHARS = 4_000


class ResumeError(ValueError):
    """Raised for any problem with an uploaded resume (shown to the user)."""


@dataclass
class ParsedResume:
    skills: list[tuple[str, str]] = field(default_factory=list)  # (name, category)
    job_titles: list[str] = field(default_factory=list)
    education: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    experience_years: float | None = None
    profile_text: str = ""


# ---------------------------------------------------------------- validation
def validate_upload(filename: str, data: bytes, max_bytes: int) -> str:
    """Return the file kind ('pdf' | 'docx') or raise ResumeError."""
    name = (filename or "").lower()
    if not data:
        raise ResumeError("The uploaded file is empty.")
    if len(data) > max_bytes:
        raise ResumeError(f"File is larger than the {max_bytes // (1024 * 1024)} MB limit.")
    if name.endswith(".pdf"):
        if not data.startswith(PDF_MAGIC):
            raise ResumeError("This file is named .pdf but is not a valid PDF.")
        return "pdf"
    if name.endswith(".docx"):
        if not data.startswith(ZIP_MAGIC):
            raise ResumeError("This file is named .docx but is not a valid Word document.")
        return "docx"
    raise ResumeError("Only PDF and DOCX resumes are supported.")


def sanitize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_TEXT_CHARS]


# ---------------------------------------------------------------- extraction
def extract_text(kind: str, data: bytes) -> str:
    try:
        if kind == "pdf":
            import pymupdf  # PyMuPDF

            with pymupdf.open(stream=data, filetype="pdf") as doc:
                if doc.needs_pass:
                    raise ResumeError("Password-protected PDFs are not supported.")
                text = "\n".join(page.get_text() for page in doc)
        else:
            from docx import Document

            doc = Document(io.BytesIO(data))
            parts = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    parts.extend(cell.text for cell in row.cells)
            text = "\n".join(parts)
    except ResumeError:
        raise
    except Exception as exc:  # corrupt files raise many different library errors
        raise ResumeError(f"Could not read the {kind.upper()} file: {exc}") from exc
    text = sanitize_text(text)
    if len(text) < 30:
        raise ResumeError("No readable text found. Scanned/image-only resumes are not supported.")
    return text


# ---------------------------------------------------------------- structuring
_SECTION_HEADINGS = {
    "experience": r"(?:work\s+|professional\s+)?experience|employment(?:\s+history)?|work\s+history",
    "education": r"education(?:al)?(?:\s+qualifications?)?|academics?",
    "certifications": r"certifications?|licen[sc]es?(?:\s+&\s+certifications?)?|courses",
    "skills": r"(?:technical\s+)?skills|technologies|tech\s+stack",
    "projects": r"projects?",
    "summary": r"summary|profile|objective|about\s+me",
}
_HEADING_RE = {
    name: re.compile(rf"^\s*(?:{pat})\s*:?\s*$", re.IGNORECASE) for name, pat in _SECTION_HEADINGS.items()
}

_TITLE_WORDS = (
    r"engineer|developer|programmer|analyst|manager|architect|consultant|scientist|"
    r"administrator|specialist|lead|intern|trainee|associate|sde|devops|sre|tester|designer"
)
_TITLE_RE = re.compile(rf"\b(?:{_TITLE_WORDS})\b", re.IGNORECASE)
_DEGREE_RE = re.compile(
    r"\b(?:b\.?\s?tech|m\.?\s?tech|b\.?\s?e\.?|m\.?\s?e\.?|b\.?\s?sc|m\.?\s?sc|bca|mca|mba|"
    r"ph\.?d|bachelor|master|diploma|b\.?\s?s\.?|m\.?\s?s\.?)\b",
    re.IGNORECASE,
)
_CERT_HINT_RE = re.compile(r"\bcertif(?:ied|ication|icate)\b", re.IGNORECASE)

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
_RANGE_RE = re.compile(
    r"(?:(?P<m1>[A-Za-z]{3})[a-z]*\.?,?\s+)?(?P<y1>(?:19|20)\d{2})\s*(?:-|–|—|to)\s*"
    r"(?:(?P<present>present|current|now|till\s+date|ongoing)|"
    r"(?:(?P<m2>[A-Za-z]{3})[a-z]*\.?,?\s+)?(?P<y2>(?:19|20)\d{2}))",
    re.IGNORECASE,
)
_STATED_YEARS_RE = re.compile(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*years?", re.IGNORECASE)


def split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        matched = next((n for n, rx in _HEADING_RE.items() if rx.match(line)), None)
        if matched:
            current = matched
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _clean_bullet(line: str) -> str:
    return re.sub(r"^[\-•●▪\*–—›>]+\s*", "", line).strip()


def estimate_experience_years(text: str, today: date | None = None) -> float | None:
    today = today or date.today()
    intervals: list[tuple[int, int]] = []
    for m in _RANGE_RE.finditer(text):
        start_month = _MONTHS.get((m.group("m1") or "").lower()[:3], 1)
        start = int(m.group("y1")) * 12 + start_month - 1
        if m.group("present"):
            end = today.year * 12 + today.month - 1
        else:
            end_month = _MONTHS.get((m.group("m2") or "").lower()[:3], 12)
            end = int(m.group("y2")) * 12 + end_month  # end month is inclusive
        if end >= start and end - start <= 12 * 45:
            intervals.append((start, end))
    merged: list[list[int]] = []
    for s, e in sorted(intervals):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    months = sum(e - s for s, e in merged)
    from_ranges = round(months / 12, 1) if months else None

    stated = [float(x) for x in _STATED_YEARS_RE.findall(text) if 0 < float(x) <= 45]
    from_text = max(stated) if stated else None
    candidates = [v for v in (from_ranges, from_text) if v is not None]
    return max(candidates) if candidates else None


def parse_resume_text(text: str, today: date | None = None) -> ParsedResume:
    extractor = get_skill_extractor()
    sections = split_sections(text)

    skills = [(s.name, s.category) for s in extractor.extract(text)]

    exp_lines = sections.get("experience", []) + sections.get("header", [])[:6]
    titles: list[str] = []
    for line in exp_lines:
        cleaned = _clean_bullet(line)
        if 3 <= len(cleaned) <= 80 and _TITLE_RE.search(cleaned) and not cleaned.endswith("."):
            title = re.split(r"\s+(?:at|@|\||,|-|–|—)\s+", cleaned, maxsplit=1)[0].strip()
            if title and title not in titles and _TITLE_RE.search(title):
                titles.append(title)
    titles = titles[:8]

    education = [_clean_bullet(line) for line in sections.get("education", []) if _DEGREE_RE.search(line)][:6]

    certs = [_clean_bullet(line) for line in sections.get("certifications", [])][:10]
    if not certs:
        certs = [
            _clean_bullet(line)
            for line in text.splitlines()
            if _CERT_HINT_RE.search(line) and len(line) <= 140
        ][:10]

    # Condensed text used for the semantic embedding. Deliberately NOT the full
    # resume: it keeps only skills, titles and summary lines, which is all the
    # matcher needs and all that is stored remotely.
    summary = " ".join(sections.get("summary", []))[:800]
    profile_text = ". ".join(
        part
        for part in (
            summary,
            "Titles: " + ", ".join(titles) if titles else "",
            "Skills: " + ", ".join(n for n, _ in skills) if skills else "",
        )
        if part
    )[:PROFILE_TEXT_CHARS]

    return ParsedResume(
        skills=skills,
        job_titles=titles,
        education=education,
        certifications=certs,
        experience_years=estimate_experience_years(text, today),
        profile_text=profile_text,
    )
