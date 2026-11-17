"""Find a company's public career board from just its name.

Many companies host their careers page on Greenhouse, Lever or Ashby, and each of those has
a public, key-less endpoint keyed by a "board token" (a slug such as ``stripe``). We guess
likely slugs from the company name and probe the three platforms:

    "Acme Technologies, Inc."  ->  acme, acmetechnologies, acme-technologies, ...
    for each slug:  Greenhouse /boards/{slug}   Lever /postings/{slug}   Ashby /job-board/{slug}

How sure are we?
  * verified    Greenhouse tells us the board's company name, and it matches ours.
  * unverified  A board exists under that slug on Lever/Ashby (they do not expose the
                company name), so a different company could in theory share the slug.
                The dashboard shows the careers link so you can confirm with one click.
  * mismatch    Greenhouse says the board belongs to a *different* company name. Shown as a
                possible match for manual choice, never picked automatically.
  * unreachable We could not get a clear answer from any job-board server (no internet, blocked,
                rate limited). Says nothing about the company; it is retried at the next search.
  * not_found   Nothing public under any guessed slug. The company probably runs its own
                careers site (Workday, iCIMS, a custom page...). Those cannot be searched
                automatically; paste its Greenhouse/Lever/Ashby link if it has one.

Only official public APIs are called. No scraping.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from backend.app.collectors.base import HttpFetcher
from backend.app.core.names import _core_words, _words, name_key, same_company  # noqa: F401

logger = logging.getLogger(__name__)

MAX_SLUGS = 6
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards"
LEVER_HOSTS = {"us": "https://api.lever.co", "eu": "https://api.eu.lever.co"}
ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board"


def slug_candidates(name: str) -> list[str]:
    """Likely board tokens for a company name, best guess first (max MAX_SLUGS)."""
    words = _words(name)
    if not words:
        return []
    core, core2 = _core_words(name)
    ordered: list[str] = []
    for group in (core2, core, words):
        for slug in ("".join(group), "-".join(group)):
            if len(slug) >= 2 and slug not in ordered:
                ordered.append(slug)
    return ordered[:MAX_SLUGS]


# ---------------------------------------------------------------- URLs
def careers_url(platform: str | None, token: str | None, region: str = "us") -> str | None:
    if not platform or not token:
        return None
    if platform == "greenhouse":
        return f"https://boards.greenhouse.io/{token}"
    if platform == "lever":
        return f"https://jobs{'.eu' if region == 'eu' else ''}.lever.co/{token}"
    if platform == "ashby":
        return f"https://jobs.ashbyhq.com/{token}"
    return None


@dataclass(frozen=True)
class BoardRef:
    platform: str
    board_token: str
    api_region: str = "us"


def parse_careers_url(url: str) -> BoardRef | None:
    """Extract platform + token from a pasted careers/job link, or None if not recognised."""
    raw = url.strip()
    if not raw:
        return None
    parsed = urlparse(raw if "//" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower()
    parts = [p for p in parsed.path.split("/") if p]
    token: str | None = None
    ref: tuple[str, str] | None = None

    if host.endswith("greenhouse.io"):
        if host == "boards-api.greenhouse.io" and len(parts) >= 3 and parts[:2] == ["v1", "boards"]:
            token = parts[2]
        elif parts and parts[0] == "embed":
            token = (parse_qs(parsed.query).get("for") or [None])[0]
        elif parts:
            token = parts[0]
        ref = ("greenhouse", "us")
    elif host.endswith("lever.co"):
        if host.startswith("api.") and len(parts) >= 3 and parts[:2] == ["v0", "postings"]:
            token = parts[2]
        elif parts:
            token = parts[0]
        ref = ("lever", "eu" if ".eu." in host else "us")
    elif host == "jobs.ashbyhq.com" and parts:
        token = parts[0]
        ref = ("ashby", "us")

    if ref and token and TOKEN_RE.match(token):
        return BoardRef(ref[0], token, ref[1])
    return None


# ---------------------------------------------------------------- results
@dataclass
class BoardCandidate:
    platform: str
    board_token: str
    api_region: str
    job_count: int
    verified: bool = False
    mismatch: bool = False
    board_name: str | None = None  # company name reported by the platform (Greenhouse only)

    @property
    def careers_url(self) -> str | None:
        return careers_url(self.platform, self.board_token, self.api_region)


@dataclass
class DiscoveryResult:
    status: str  # verified | unverified | not_found | unreachable
    candidates: list[BoardCandidate] = field(default_factory=list)
    best: BoardCandidate | None = None
    message: str = ""
    tried_slugs: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- discovery
class BoardDiscovery:
    def __init__(self, http: HttpFetcher):
        self.http = http

    def discover(self, company_name: str) -> DiscoveryResult:
        slugs = slug_candidates(company_name)
        found: list[BoardCandidate] = []
        answers_before = self.http.probe_answers
        for slug in slugs:
            hits = [
                c
                for c in (
                    self._greenhouse(slug, company_name),
                    self._lever(slug, "us"),
                    self._lever(slug, "eu"),
                    self._ashby(slug),
                )
                if c is not None
            ]
            found.extend(hits)
            if any(not c.mismatch for c in hits):
                break  # good enough: do not keep guessing weaker slugs
        if not found and self.http.probe_answers == answers_before and slugs:
            return DiscoveryResult(
                "unreachable",
                [],
                None,
                "Could not reach the Greenhouse, Lever and Ashby servers, so the job board is still unknown. "
                "Check your internet connection; it is tried again at the next search, or press "
                "'Find job board again'.",
                slugs,
            )
        return self._decide(company_name, slugs, found)

    # ---- platform probes -------------------------------------------------
    def _greenhouse(self, slug: str, company_name: str) -> BoardCandidate | None:
        info = self.http.probe(f"{GREENHOUSE_API}/{slug}")
        name = info.get("name") if isinstance(info, dict) else None
        if not name:
            return None
        jobs = self.http.probe(f"{GREENHOUSE_API}/{slug}/jobs")
        count = len(jobs.get("jobs", [])) if isinstance(jobs, dict) else 0
        same = same_company(company_name, str(name))
        return BoardCandidate(
            "greenhouse", slug, "us", count, verified=same, mismatch=not same, board_name=str(name)
        )

    def _lever(self, slug: str, region: str) -> BoardCandidate | None:
        base = f"{LEVER_HOSTS[region]}/v0/postings/{slug}"
        first = self.http.probe(base, {"mode": "json", "limit": 1})
        if not isinstance(first, list) or not first:  # empty = nothing to search anyway
            return None
        page = self.http.probe(base, {"mode": "json", "limit": 100})
        return BoardCandidate("lever", slug, region, len(page) if isinstance(page, list) else len(first))

    def _ashby(self, slug: str) -> BoardCandidate | None:
        data = self.http.probe(f"{ASHBY_API}/{slug}")
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            return None
        listed = [j for j in jobs if isinstance(j, dict) and j.get("isListed") is not False]
        return BoardCandidate("ashby", slug, "us", len(listed)) if listed else None

    # ---- decision ----------------------------------------------------------
    @staticmethod
    def _decide(name: str, slugs: list[str], found: list[BoardCandidate]) -> DiscoveryResult:
        verified = [c for c in found if c.verified]
        plausible = [c for c in found if not c.mismatch]
        if verified:
            best = verified[0]
            return DiscoveryResult("verified", found, best, f"Found {name} on {best.platform}.", slugs)
        if plausible:
            best = plausible[0]
            return DiscoveryResult(
                "unverified",
                found,
                best,
                f"Found a {best.platform} board '{best.board_token}' with {best.job_count} open jobs. "
                "Open the careers link to confirm it is the right company.",
                slugs,
            )
        note = ""
        if found:  # only Greenhouse boards that belong to other companies
            other = ", ".join(f"'{c.board_name}'" for c in found if c.board_name)
            note = f" (a Greenhouse board exists under a different name: {other})"
        return DiscoveryResult(
            "not_found",
            found,
            None,
            f"No public Greenhouse, Lever or Ashby board found for '{name}'{note}. The company may use its "
            "own careers site, which cannot be searched automatically. If you have a link to its "
            "Greenhouse/Lever/Ashby page, paste it as the careers link.",
            slugs,
        )


def apply_result(company, result: DiscoveryResult) -> None:
    """Copy a discovery outcome onto a Company row (platform, token, region, status)."""
    company.discovery_status = result.status
    if result.best is not None:
        company.platform = result.best.platform
        company.board_token = result.best.board_token
        company.api_region = result.best.api_region
        company.last_error = None
    else:
        company.platform = company.board_token = None
        company.last_error = result.message[:1000]
