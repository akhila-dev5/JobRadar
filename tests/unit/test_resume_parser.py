from datetime import date

import pytest

from backend.app.services.resume_parser import (
    ResumeError,
    estimate_experience_years,
    extract_text,
    parse_resume_text,
    sanitize_text,
    validate_upload,
)
from tests.helpers import RESUME_TEXT, make_blank_pdf, make_docx, make_pdf

MB = 1024 * 1024


def test_validate_rejects_empty_oversized_and_wrong_types():
    with pytest.raises(ResumeError, match="empty"):
        validate_upload("a.pdf", b"", MB)
    with pytest.raises(ResumeError, match="limit"):
        validate_upload("a.pdf", b"%PDF-" + b"0" * (MB + 1), MB)
    with pytest.raises(ResumeError, match="PDF and DOCX"):
        validate_upload("a.exe", b"MZ", MB)
    with pytest.raises(ResumeError, match="not a valid PDF"):
        validate_upload("fake.pdf", b"hello world", MB)
    with pytest.raises(ResumeError, match="not a valid Word"):
        validate_upload("fake.docx", b"hello world", MB)


def test_pdf_and_docx_text_extraction():
    for kind, data in (("pdf", make_pdf()), ("docx", make_docx())):
        text = extract_text(kind, data)
        assert "FastAPI" in text and "Acme Corp" in text


def test_corrupt_files_raise_resume_error_not_crash():
    with pytest.raises(ResumeError):
        extract_text("pdf", b"%PDF-1.4 garbage")
    with pytest.raises(ResumeError):
        extract_text("docx", b"PK\x03\x04garbage")


def test_image_only_pdf_gives_clear_error():
    with pytest.raises(ResumeError, match="No readable text"):
        extract_text("pdf", make_blank_pdf())


def test_sanitize_strips_control_chars_and_caps_blank_lines():
    assert sanitize_text("a\x00b\x07c\n\n\n\n\nd") == "abc\n\nd"


def test_structured_profile():
    p = parse_resume_text(RESUME_TEXT, today=date(2026, 11, 1))
    names = {n for n, _ in p.skills}
    assert {"Python", "FastAPI", "PostgreSQL", "Docker", "AWS", "Git", "REST APIs", "Pytest"} <= names
    cats = dict(p.skills)
    assert cats["Python"] == "languages" and cats["PostgreSQL"] == "databases"
    assert cats["AWS"] == "cloud" and cats["FastAPI"] == "frameworks"
    assert "Senior Software Engineer" in p.job_titles
    assert any("B.Tech" in e for e in p.education)
    assert any("AWS Certified" in c for c in p.certifications)
    assert p.experience_years and p.experience_years >= 6
    assert "Skills:" in p.profile_text


def test_java_not_extracted_from_javascript_text():
    p = parse_resume_text("Experienced developer using JavaScript and TypeScript every day.")
    names = {n for n, _ in p.skills}
    assert "JavaScript" in names and "Java" not in names


def test_ambiguous_words_not_taken_as_skills():
    p = parse_resume_text("I go to work and we rest on weekends. A swift response, ruby red.")
    assert not {"Go", "R", "Swift", "Ruby", "Rest"} & {n for n, _ in p.skills}


def test_experience_merges_overlapping_ranges():
    text = "Jan 2018 - Dec 2020\nJun 2019 - Dec 2021"
    assert estimate_experience_years(text, today=date(2026, 1, 1)) == 4.0


def test_experience_present_and_stated_years():
    assert estimate_experience_years("Jan 2024 - Present", today=date(2026, 1, 1)) == 2.0
    assert estimate_experience_years("I have 7 years of experience") == 7.0
    assert estimate_experience_years("no dates here") is None
