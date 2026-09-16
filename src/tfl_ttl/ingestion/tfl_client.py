"""Thin client for the TfL Unified API (https://api.tfl.gov.uk).

Kept deliberately small: one function to build a request against any TfL
endpoint. Higher-rate-limit access works by passing app_id/app_key, which
are picked up from the environment if not supplied.
"""

from __future__ import annotations

import requests

from tfl_ttl.config import TFL_APP_ID, TFL_APP_KEY

BASE_URL = "https://api.tfl.gov.uk"


def get(path: str, params: dict | None = None) -> dict | list:
    """GET a TfL Unified API path (e.g. '/Line/Mode/tube/Status') as JSON."""
    query = dict(params or {})
    if TFL_APP_ID and TFL_APP_KEY:
        query.setdefault("app_id", TFL_APP_ID)
        query.setdefault("app_key", TFL_APP_KEY)

    response = requests.get(f"{BASE_URL}{path}", params=query, timeout=30)
    response.raise_for_status()
    return response.json()
