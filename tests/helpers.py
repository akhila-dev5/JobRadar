"""Test doubles: a fake job-board network, a fake SMTP server, and sample files."""

from __future__ import annotations

import io
import json

import httpx

# ---------------------------------------------------------------- job payloads
# Shapes follow the vendors' public API documentation.


def gh_job(job_id: int, title: str, body: str, location: str = "Remote") -> dict:
    return {
        "id": job_id,
        "internal_job_id": job_id + 1000,
        "title": title,
        "updated_at": "2026-11-01T10:00:00-05:00",
        "location": {"name": location},
        "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{job_id}",
        # Greenhouse returns entity-encoded HTML in `content`
        "content": f"&lt;p&gt;{body}&lt;/p&gt;",
        "departments": [],
        "offices": [],
    }


def lever_job(job_id: str, title: str, body: str, location: str = "Hyderabad") -> dict:
    return {
        "id": job_id,
        "text": title,
        "hostedUrl": f"https://jobs.lever.co/globex/{job_id}",
        "applyUrl": f"https://jobs.lever.co/globex/{job_id}/apply",
        "createdAt": 1761990000000,
        "categories": {"location": location, "commitment": "Full-time", "allLocations": [location]},
        "workplaceType": "hybrid",
        "descriptionPlain": body,
        "lists": [{"text": "Requirements", "content": "<li>3+ years of experience</li>"}],
        "additionalPlain": "",
    }


def ashby_job(job_id: str, title: str, body: str, listed: bool = True) -> dict:
    return {
        "id": job_id,
        "title": title,
        "location": "Bengaluru",
        "isListed": listed,
        "isRemote": False,
        "workplaceType": "Hybrid",
        "employmentType": "FullTime",
        "descriptionPlain": body,
        "descriptionHtml": f"<p>{body}</p>",
        "publishedAt": "2026-10-20T08:00:00.000+00:00",
        "jobUrl": f"https://jobs.ashbyhq.com/initech/{job_id}",
        "applyUrl": f"https://jobs.ashbyhq.com/initech/{job_id}/application",
    }


class FakeBoards:
    """Maps board tokens to payloads; mimics the three vendors' URLs."""

    def __init__(self) -> None:
        self.greenhouse: dict[str, list[dict] | int] = {}
        self.lever: dict[str, list[dict] | int] = {}
        self.ashby: dict[str, list[dict] | int] = {}
        self.calls: list[str] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        self.calls.append(str(url))
        parts = url.path.strip("/").split("/")
        if url.host == "boards-api.greenhouse.io":
            return self._respond(
                self.greenhouse, parts[-2], lambda jobs: {"jobs": jobs, "meta": {"total": len(jobs)}}
            )
        if url.host in ("api.lever.co", "api.eu.lever.co"):
            skip = int(url.params.get("skip", 0))
            limit = int(url.params.get("limit", 100))
            return self._respond(self.lever, parts[-1], lambda jobs: jobs[skip : skip + limit])
        if url.host == "api.ashbyhq.com":
            return self._respond(self.ashby, parts[-1], lambda jobs: {"apiVersion": "1", "jobs": jobs})
        return httpx.Response(404)

    @staticmethod
    def _respond(store, token, wrap) -> httpx.Response:
        data = store.get(token)
        if data is None:
            return httpx.Response(404, json={"error": "not found"})
        if isinstance(data, int):
            return httpx.Response(data)
        if data == "bad-json":
            return httpx.Response(200, content=b"<html>not json</html>")
        return httpx.Response(200, json=wrap(data))


class FakeSMTP:
    """Callable used as smtp_factory. Records sent messages; can be set to fail."""

    def __init__(self) -> None:
        self.sent: list = []
        self.fail = False
        self.logged_in: tuple | None = None

    def __call__(self, host, port, timeout=None):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        if self.fail:
            import smtplib

            raise smtplib.SMTPException("simulated outage")
        self.sent.append(msg)


# ---------------------------------------------------------------- resume files
RESUME_TEXT = """Jane Doe
Senior Software Engineer
Summary
Backend engineer with 6+ years of experience building APIs.

Technical Skills
Python, FastAPI, PostgreSQL, Docker, AWS, Git, REST APIs, Pytest

Experience
Senior Software Engineer at Acme Corp
Jan 2019 - Present
- Built microservices in Python and FastAPI on AWS
Software Developer at Initech
Jun 2016 - Dec 2018
- Maintained SQL Server databases

Education
B.Tech in Computer Science, JNTU Hyderabad, 2016

Certifications
AWS Certified Solutions Architect
Microsoft Certified: Azure Fundamentals
"""


def make_docx(text: str = RESUME_TEXT) -> bytes:
    from docx import Document

    doc = Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_pdf(text: str = RESUME_TEXT) -> bytes:
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for line in text.splitlines():
        page.insert_text((40, y), line, fontsize=10)
        y += 13
        if y > 800:
            page = doc.new_page()
            y = 50
    data = doc.tobytes()
    doc.close()
    return data


def make_blank_pdf() -> bytes:
    import pymupdf as fitz

    doc = fitz.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def json_bytes(obj) -> bytes:
    return json.dumps(obj).encode()
