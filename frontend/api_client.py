"""Thin HTTP client used by the Streamlit pages. The frontend never touches the database."""

from __future__ import annotations

import os
from typing import Any

import httpx

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.environ.get("API_KEY", "")


class ApiError(Exception):
    """Readable error to show in the UI."""


class ApiClient:
    def __init__(self, base_url: str = API_BASE_URL, api_key: str = API_KEY, transport=None):
        headers = {"X-API-Key": api_key} if api_key else {}
        self._http = httpx.Client(base_url=base_url, headers=headers, timeout=60, transport=transport)

    def request(self, method: str, path: str, raw: bool = False, **kwargs: Any) -> Any:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.ConnectError as exc:
            raise ApiError(
                f"Cannot reach the backend at {self._http.base_url}. "
                "Start it with: uvicorn backend.app.main:app --port 8000"
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Backend request failed: {exc}") from exc
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            if isinstance(detail, list):  # FastAPI validation errors
                detail = "; ".join(
                    f"{'.'.join(map(str, d.get('loc', [])[1:]))}: {d.get('msg')}" for d in detail
                )
            raise ApiError(str(detail))
        if resp.status_code == 204 or not resp.content:
            return None
        ctype = resp.headers.get("content-type", "")
        return resp.json() if "json" in ctype and not raw else resp.text

    def get(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        return self.request("GET", path, params=clean)

    def get_text(self, path: str, **params: Any) -> str | None:
        """Raw response body (used for file exports, which must not be JSON-decoded)."""
        return self.request("GET", path, raw=True, params=params or None)

    def post(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return self.request("POST", path, json=json, **kwargs)

    def put(self, path: str, json: Any = None) -> Any:
        return self.request("PUT", path, json=json)

    def patch(self, path: str, json: Any = None) -> Any:
        return self.request("PATCH", path, json=json)

    def delete(self, path: str, **params: Any) -> Any:
        return self.request("DELETE", path, params=params or None)
