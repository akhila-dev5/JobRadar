"""Collector interface, normalised job structure, and a polite HTTP client.

Adding a new job source = one new subclass of JobCollector + one registry entry.
Nothing else in the application changes (Open/Closed principle).
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class CollectorError(Exception):
    """A whole company fetch failed (bad token, outage, invalid response)."""


@dataclass
class NormalizedJob:
    source: str
    external_id: str
    company_name: str
    title: str
    description: str
    application_url: str
    location: str | None = None
    employment_type: str | None = None
    workplace_type: str | None = None
    published_at: datetime | None = None

    def content_hash(self) -> str:
        blob = "\x1f".join([self.title, self.description, self.location or "", self.application_url])
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class CompanyTarget:
    """What a collector needs to know: no ORM object leaks into the collectors."""

    name: str
    board_token: str
    api_region: str = "us"


# ------------------------------------------------------------------ text utils
class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(value: str | None) -> str:
    """Convert HTML (possibly entity-encoded, as Greenhouse returns it) to plain text."""
    if not value:
        return ""
    # Greenhouse double-encodes: "&lt;p&gt;Hello&lt;/p&gt;". Decode until stable (max 2x).
    for _ in range(2):
        decoded = html.unescape(value)
        if decoded == value:
            break
        value = decoded
    parser = _TextExtractor()
    parser.feed(value)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def parse_datetime(value: Any) -> datetime | None:
    """Accept ISO-8601 strings or epoch milliseconds; return aware UTC or None."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value) / 1000, tz=UTC)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, OverflowError, OSError):
        return None


# ------------------------------------------------------------------ HTTP client
class HttpFetcher:
    """httpx wrapper adding timeout, retry with backoff, and per-host rate limiting.

    The transport is injectable so tests can mock the network completely.
    """

    RETRY_STATUS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        timeout: float = 20.0,
        max_retries: int = 3,
        min_interval: float = 0.5,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ):
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": "JobRadarAI/1.0 (personal job search tool)"},
            follow_redirects=True,
        )
        self._max_retries = max_retries
        self._min_interval = min_interval
        self._last_call: dict[str, float] = {}
        self._sleep = sleep
        # Probe bookkeeping: lets discovery tell "does not exist" (404) from "could not ask".
        self.probe_answers = 0  # clear answers: 200, or 404 = no such board
        self.probe_failures = 0  # network errors, timeouts, 403/429/5xx...

    def _throttle(self, host: str) -> None:
        wait = self._last_call.get(host, 0.0) + self._min_interval - time.monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last_call[host] = time.monotonic()

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        host = httpx.URL(url).host
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            self._throttle(host)
            try:
                resp = self._client.get(url, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                logger.warning("GET %s failed (%s), attempt %d", url, exc, attempt + 1)
            else:
                if resp.status_code == 404:
                    raise CollectorError(f"Not found (404): {url}")
                if resp.status_code in self.RETRY_STATUS:
                    last_exc = CollectorError(f"HTTP {resp.status_code} from {url}")
                    delay = _retry_after(resp)
                    if delay:
                        self._sleep(min(delay, 30))
                    logger.warning("GET %s -> %s, attempt %d", url, resp.status_code, attempt + 1)
                elif resp.status_code >= 400:
                    raise CollectorError(f"HTTP {resp.status_code} from {url}")
                else:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise CollectorError(f"Invalid JSON from {url}") from exc
            if attempt < self._max_retries:
                self._sleep(min(2**attempt, 10))
        raise CollectorError(f"Giving up on {url}: {last_exc}")

    def probe(self, url: str, params: dict[str, Any] | None = None) -> Any | None:
        """One polite attempt, no retries and no exceptions.

        Used to guess whether a careers board exists. Returns the parsed JSON on HTTP 200,
        otherwise None. Every call is counted as a clear answer (200 / 404) or a failure
        (timeouts, blocked, rate limited, server errors), so a caller can tell "this board does
        not exist" apart from "I could not reach the server".
        """
        self._throttle(httpx.URL(url).host)
        try:
            resp = self._client.get(url, params=params)
        except httpx.HTTPError:
            self.probe_failures += 1
            return None
        if resp.status_code not in (200, 404):
            self.probe_failures += 1
            return None
        self.probe_answers += 1
        if resp.status_code == 404:
            return None
        try:
            return resp.json()
        except ValueError:
            self.probe_failures += 1
            return None

    def close(self) -> None:
        self._client.close()


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    try:
        return float(value) if value else None
    except ValueError:
        return None


# ------------------------------------------------------------------ interface
class JobCollector(ABC):
    platform: str

    def __init__(self, http: HttpFetcher):
        self.http = http
        self.skipped = 0  # malformed items skipped in the last fetch

    @abstractmethod
    def fetch_jobs(self, company: CompanyTarget) -> list[NormalizedJob]:
        """Return every currently open job, or raise CollectorError."""
