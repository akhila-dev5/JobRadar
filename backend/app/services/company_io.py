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
        return {"created": 0, "updated": 0, "errors": [f"Could not read file: {exc}"]}

    repo = CompanyRepository(db)
    created = updated = 0
    for index, raw in enumerate(data, start=1):
        try:
            if not isinstance(raw, dict):
                raise ValueError("row is not an object")
            payload = CompanyIn(
                name=str(raw.get("name", "")),
                platform=str(raw.get("platform", "")).strip().lower(),
                board_token=str(raw.get("board_token", "")).strip(),
                api_region=str(raw.get("api_region") or "us").strip().lower(),
                enabled=_parse_bool(raw.get("enabled", True)),
            )
            existing = repo.find_by_name(payload.name)
            if existing:
                repo.update(existing.id, **payload.model_dump())
                updated += 1
            else:
                repo.create(**payload.model_dump())
                created += 1
        except (ValidationError, ValueError) as exc:
            msg = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
            errors.append(f"Row {index}: {msg}")
    return {"created": created, "updated": updated, "errors": errors}
