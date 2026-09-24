from __future__ import annotations

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


def create_robust_session(retries: int = 3, backoff_factor: float = 0.5) -> requests.Session:
    """A requests Session that retries transient failures with backoff."""
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "tfl-ttl/0.1"})
    return session


def call_api(
    url: str,
    session: requests.Session | None = None,
    app_key: str | None = None,
) -> object:
    """GET a TfL URL and return the parsed JSON. Raises on any HTTP or network error."""
    http = session or requests
    params = {"app_key": app_key} if app_key else None

    logger.info("Fetching %s", url)
    response = http.get(url, params=params, timeout=(3, 10))
    response.raise_for_status()
    return response.json()
