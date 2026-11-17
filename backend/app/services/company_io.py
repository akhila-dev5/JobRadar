"""Import / export of target-company configuration (JSON or CSV)."""

from __future__ import annotations

import csv
import io
import json

from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.models import Company
from backend.app.repositories.config_repos import CompanyRepository
from backend.app.schemas.api import CompanyIn

FIELDS = ["name", "platform", "board_token", "api_region", "enabled"]


def export_companies(companies: list[Company], fmt: str) -> str:
    rows = [
        {
            "name": c.name,
            "platform": c.platform,
            "board_token": c.board_token,
            "api_region": c.api_region,
            "enabled": c.enabled,
        }
        for c in companies
    ]
    if fmt == "json":
        return json.dumps(rows, indent=2)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", ""}


def import_companies(db: Session, content: str, fmt: str) -> dict:
    errors: list[str] = []
    try:
        if fmt == "json":
            data = json.loads(content)
            if isinstance(data, dict):
                data = data.get("companies", [])
            if not isinstance(data, list):
                raise ValueError("JSON must be a list of company objects")
        else:
            data = list(csv.DictReader(io.StringIO(content)))
    except (ValueError, csv.Error) as exc:
        return {"created": 0, "updated": 0, "errors": [f"Could not read file: {exc}"], "new_pending": []}

    repo = CompanyRepository(db)
    created = updated = 0
    new_pending: list[int] = []  # name-only rows: the caller starts board discovery for these
    for index, raw in enumerate(data, start=1):
        try:
            if not isinstance(raw, dict):
                raise ValueError("row is not an object")
            # Only "name" is required; empty platform/board_token cells mean "find it for me".
            payload = CompanyIn(
                name=str(raw.get("name", "")),
                platform=(str(raw.get("platform") or "").strip().lower() or None),
                board_token=(str(raw.get("board_token") or "").strip() or None),
                api_region=str(raw.get("api_region") or "us").strip().lower(),
                careers_url=(str(raw.get("careers_url") or "").strip() or None),
                enabled=_parse_bool(raw.get("enabled", True)),
            )
            fields = payload.model_dump(exclude={"careers_url"})
            existing = repo.find_by_name(payload.name)
            if existing:
                if payload.platform is None:  # never wipe a known board with an empty cell
                    for key in ("platform", "board_token", "api_region"):
                        fields.pop(key)
                repo.update(existing.id, **fields)
                updated += 1
            else:
                company = repo.create(**fields)
                created += 1
                if company.discovery_status == "pending":
                    new_pending.append(company.id)
        except (ValidationError, ValueError) as exc:
            msg = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
            errors.append(f"Row {index}: {msg}")
    return {"created": created, "updated": updated, "errors": errors, "new_pending": new_pending}
