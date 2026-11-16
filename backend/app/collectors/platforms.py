"""Greenhouse, Lever and Ashby collectors.

Endpoints and field names follow each vendor's public documentation:
  Greenhouse: https://developers.greenhouse.io/job-board.html
  Lever:      https://github.com/lever/postings-api
  Ashby:      https://developers.ashbyhq.com/docs/public-job-posting-api
"""

from __future__ import annotations

import logging
from typing import Any

from backend.app.collectors.base import (
    CollectorError,
    CompanyTarget,
    HttpFetcher,
    JobCollector,
    NormalizedJob,
    html_to_text,
    parse_datetime,
)

logger = logging.getLogger(__name__)
COLLECTORS: dict[str, type[JobCollector]] = {}


def register_collector(cls: type[JobCollector]) -> type[JobCollector]:
    COLLECTORS[cls.platform] = cls
    return cls


def get_collector(platform: str, http: HttpFetcher) -> JobCollector:
    try:
        return COLLECTORS[platform](http)
    except KeyError:
        raise CollectorError(f"No collector registered for platform '{platform}'") from None


def _need_dict(payload: Any, what: str) -> dict:
    if not isinstance(payload, dict):
        raise CollectorError(f"Unexpected {what} response shape (expected an object)")
    return payload


@register_collector
class GreenhouseCollector(JobCollector):
    platform = "greenhouse"
    BASE = "https://boards-api.greenhouse.io/v1/boards"

    def fetch_jobs(self, company: CompanyTarget) -> list[NormalizedJob]:
        self.skipped = 0
        payload = _need_dict(
            self.http.get_json(f"{self.BASE}/{company.board_token}/jobs", {"content": "true"}),
            "Greenhouse",
        )
        items = payload.get("jobs")
        if not isinstance(items, list):
            raise CollectorError("Greenhouse response has no 'jobs' list")
        jobs: list[NormalizedJob] = []
        for item in items:
            try:
                location = (item.get("location") or {}).get("name")
                jobs.append(
                    NormalizedJob(
                        source=self.platform,
                        external_id=str(item["id"]),
                        company_name=company.name,
                        title=str(item["title"]).strip(),
                        description=html_to_text(item.get("content")),
                        application_url=item["absolute_url"],
                        location=location,
                        # Greenhouse exposes updated_at (first_published only on some boards).
                        published_at=parse_datetime(item.get("first_published") or item.get("updated_at")),
                    )
                )
            except (KeyError, TypeError, AttributeError) as exc:
                self.skipped += 1
                logger.warning("Skipping malformed Greenhouse job: %r", exc)
        return jobs


@register_collector
class LeverCollector(JobCollector):
    platform = "lever"
    HOSTS = {"us": "https://api.lever.co", "eu": "https://api.eu.lever.co"}
    PAGE = 100
    MAX_PAGES = 50  # safety stop: 5000 postings

    def fetch_jobs(self, company: CompanyTarget) -> list[NormalizedJob]:
        self.skipped = 0
        host = self.HOSTS.get(company.api_region.lower(), self.HOSTS["us"])
        url = f"{host}/v0/postings/{company.board_token}"
        jobs: list[NormalizedJob] = []
        for page in range(self.MAX_PAGES):
            batch = self.http.get_json(url, {"mode": "json", "skip": page * self.PAGE, "limit": self.PAGE})
            if not isinstance(batch, list):
                raise CollectorError("Lever response is not a list")
            for item in batch:
                try:
                    jobs.append(self._normalise(item, company))
                except (KeyError, TypeError, AttributeError) as exc:
                    self.skipped += 1
                    logger.warning("Skipping malformed Lever posting: %r", exc)
            if len(batch) < self.PAGE:
                break
        return jobs

    def _normalise(self, item: dict, company: CompanyTarget) -> NormalizedJob:
        cats = item.get("categories") or {}
        pieces = [item.get("descriptionPlain") or html_to_text(item.get("description"))]
        for block in item.get("lists") or []:
            pieces.append(f"{block.get('text', '')}\n{html_to_text(block.get('content'))}")
        pieces.append(item.get("additionalPlain") or html_to_text(item.get("additional")))
        locations = cats.get("allLocations") or ([cats["location"]] if cats.get("location") else [])
        return NormalizedJob(
            source=self.platform,
            external_id=str(item["id"]),
            company_name=company.name,
            title=str(item["text"]).strip(),
            description="\n".join(p for p in pieces if p).strip(),
            application_url=item.get("applyUrl") or item["hostedUrl"],
            location=", ".join(locations) or None,
            employment_type=cats.get("commitment"),
            workplace_type=item.get("workplaceType"),
            published_at=parse_datetime(item.get("createdAt")),
        )


@register_collector
class AshbyCollector(JobCollector):
    platform = "ashby"
    BASE = "https://api.ashbyhq.com/posting-api/job-board"

    def fetch_jobs(self, company: CompanyTarget) -> list[NormalizedJob]:
        self.skipped = 0
        payload = _need_dict(self.http.get_json(f"{self.BASE}/{company.board_token}"), "Ashby")
        items = payload.get("jobs")
        if not isinstance(items, list):
            raise CollectorError("Ashby response has no 'jobs' list")
        jobs: list[NormalizedJob] = []
        for item in items:
            try:
                if item.get("isListed") is False:
                    continue  # unlisted postings are not public
                url = item.get("applyUrl") or item["jobUrl"]
                # The docs do not list an id field; fall back to the last URL segment.
                ext_id = item.get("id") or item["jobUrl"].rstrip("/").rsplit("/", 1)[-1]
                workplace = item.get("workplaceType") or ("Remote" if item.get("isRemote") else None)
                jobs.append(
                    NormalizedJob(
                        source=self.platform,
                        external_id=str(ext_id),
                        company_name=company.name,
                        title=str(item["title"]).strip(),
                        description=item.get("descriptionPlain") or html_to_text(item.get("descriptionHtml")),
                        application_url=url,
                        location=item.get("location"),
                        employment_type=item.get("employmentType"),
                        workplace_type=workplace,
                        published_at=parse_datetime(item.get("publishedAt")),
                    )
                )
            except (KeyError, TypeError, AttributeError) as exc:
                self.skipped += 1
                logger.warning("Skipping malformed Ashby job: %r", exc)
        return jobs
