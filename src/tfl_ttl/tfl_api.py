# Fetching from TfL: a retrying HTTP session, and one function to GET a URL.
#
# Nothing in here knows about specific endpoints, S3 or the registry. It takes
# a URL and returns parsed JSON, or raises.

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


def create_robust_session(retries: int = 3, backoff_factor: float = 0.5) -> requests.Session:
    """A requests Session that retries transient failures with backoff."""
    # A Session reuses one connection across requests instead of opening a new
    # one each time.
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        # Waits a little longer between each attempt.
        backoff_factor=backoff_factor,
        # Only temporary failures: 429 "slow down" and 5xx "server fault".
        # A 404 won't fix itself, so it isn't retried.
        status_forcelist=[429, 500, 502, 503, 504],
        # GET only reads, so repeating it is harmless. A POST can create
        # something, and retrying one risks doing it twice.
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    # Attach the retry rules to every URL starting with these prefixes.
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    # Tells TfL who is calling.
    session.headers.update({"User-Agent": "tfl-ttl/0.1"})
    return session


def call_api(
    url: str,
    session: requests.Session | None = None,
    app_key: str | None = None,
) -> object:
    """GET a TfL URL and return the parsed JSON. Raises on any HTTP or network error."""
    # "Use the session if given, otherwise plain requests" (None is falsy).
    http = session or requests
    # The key goes in params, not the URL string, so `url` never contains it and
    # it stays out of the "Fetching" log line and the source_url stored in S3.
    params = {"app_key": app_key} if app_key else None

    logger.info("Fetching %s", url)
    try:
        # timeout=(connect, read) in seconds. Without one, a request can hang forever.
        response = http.get(url, params=params, timeout=(3, 10))
        # requests does NOT raise on a bad status by itself. This raises
        # HTTPError for any 4xx/5xx and does nothing on success.
        response.raise_for_status()
    except requests.RequestException as err:
        # Every requests error message (HTTP errors, timeouts, exhausted retries)
        # contains the full URL including ?app_key=..., which would put the key
        # in the logs. Re-raise with the URL minus its parameters. `from None`
        # stops Python printing the original error as the cause.
        status = err.response.status_code if err.response is not None else "no response"
        raise requests.RequestException(f"{type(err).__name__} ({status}) for {url}") from None

    # There's no try/except returning None: a failure must reach run(), where
    # it's logged against this feed and turns the run red. Returning None would
    # let the caller upload {"response": null} as if it were a real poll.
    #
    # Known limitation, accepted: a 200 that isn't JSON (e.g. an HTML
    # maintenance page) raises here, before anything is landed, so the raw body
    # isn't kept as evidence. The log still records the failure.
    #
    # Returns object because JSON can be a list, dict, string or number;
    # validate_payload checks the shape after landing.
    return response.json()
