# Tests for tfl_api.py: the first code that talks to the network, so the tests
# put a fake in its place.
#
# call_api takes the session as a parameter, so a test hands it a FakeSession
# instead of a real one. No patching needed: that's the payoff of passing
# dependencies in rather than creating them inside.

import logging
import traceback

import pytest
import requests

from tfl_ttl.tfl_api import call_api, create_robust_session

URL = "https://api.tfl.gov.uk/Line/Mode/tube/Status"
# Referenced by name, never typed into a call, so the value only appears in
# output if the code under test leaks it.
APP_KEY = "test-app-key-123"


def make_response(status_code=200, body=b"[]"):
    """A real requests.Response with a canned status and body.

    Real rather than a MagicMock on purpose: a MagicMock's raise_for_status()
    would silently do nothing, so a test for error handling could pass without
    ever exercising it.
    """
    response = requests.Response()
    response.status_code = status_code
    response._content = body
    response.reason = "Test"
    # requests puts the full URL, key included, into its error messages, so the
    # fake does too. That's the leak the key tests check is plugged.
    response.url = f"{URL}?app_key={APP_KEY}"
    return response


class FakeSession:
    """Stands in for requests.Session: records each call, returns or raises what it's told."""

    def __init__(self, response=None, error=None):
        # `is None`, not `response or make_response()`: a Response with a 4xx/5xx
        # status is falsy (bool(response) is response.ok), so `or` would quietly
        # swap every error response for the default 200.
        self.response = make_response() if response is None else response
        self.error = error
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if self.error:
            raise self.error
        return self.response


# --- Successful requests -------------------------------------------------------


def test_returns_parsed_json():
    session = FakeSession(make_response(body=b'[{"id": "victoria"}]'))
    assert call_api(URL, session=session) == [{"id": "victoria"}]


def test_app_key_is_sent_as_a_param_not_in_the_url():
    session = FakeSession()
    call_api(URL, session=session, app_key=APP_KEY)

    sent = session.calls[0]
    assert sent["params"] == {"app_key": APP_KEY}
    # The URL the code passes on (and logs, and stores as source_url) is clean.
    assert sent["url"] == URL


def test_no_params_when_there_is_no_app_key():
    session = FakeSession()
    call_api(URL, session=session, app_key=None)
    assert session.calls[0]["params"] is None


def test_request_has_a_timeout():
    # Without a timeout a request can hang forever and the run never finishes.
    session = FakeSession()
    call_api(URL, session=session)
    assert session.calls[0]["timeout"] == (3, 10)


def test_without_a_session_it_uses_plain_requests(monkeypatch):
    # The `session or requests` fallback. The notebook calls it this way.
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return make_response(body=b'["ok"]')

    # monkeypatch.setattr replaces requests.get for this test only.
    monkeypatch.setattr(requests, "get", fake_get)

    assert call_api(URL) == ["ok"]
    assert calls == [URL]


def test_fetch_is_logged_without_the_key(caplog):
    # caplog is a built-in fixture that captures log records during the test.
    caplog.set_level(logging.INFO, logger="tfl_ttl.tfl_api")
    call_api(URL, session=FakeSession(), app_key=APP_KEY)

    assert f"Fetching {URL}" in caplog.text
    assert APP_KEY not in caplog.text


# --- Failures ------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [400, 404, 429, 500, 503])
def test_http_error_status_raises(status_code):
    session = FakeSession(make_response(status_code=status_code))

    # match= is a regular expression, so the brackets around the status code are
    # escaped. The URL is matched literally afterwards, with `in`.
    with pytest.raises(requests.RequestException, match=rf"HTTPError \({status_code}\)") as excinfo:
        call_api(URL, session=session, app_key=APP_KEY)

    # excinfo.value is the exception that was raised, for checks beyond the type.
    assert URL in str(excinfo.value)


def test_network_error_raises_with_no_response():
    error = requests.ConnectionError(f"Max retries exceeded with url: {URL}?app_key={APP_KEY}")
    session = FakeSession(error=error)

    with pytest.raises(requests.RequestException, match=r"ConnectionError \(no response\)"):
        call_api(URL, session=session, app_key=APP_KEY)


# The security regression tests. requests' own error messages contain the full
# URL, ?app_key=... included; call_api must re-raise without it. These check
# the whole printed traceback, not just the message, because a plain
# `raise ... ` (without `from None`) would print the original error, key and
# all, underneath as "During handling of the above exception...".
@pytest.mark.parametrize(
    "session",
    [
        FakeSession(make_response(status_code=404)),
        FakeSession(error=requests.ConnectionError(f"failed: {URL}?app_key={APP_KEY}")),
        FakeSession(error=requests.Timeout(f"timed out: {URL}?app_key={APP_KEY}")),
    ],
    # ids name each case in the test report instead of session0, session1...
    ids=["http-error", "connection-error", "timeout"],
)
def test_app_key_never_appears_in_the_error(session):
    with pytest.raises(requests.RequestException) as excinfo:
        call_api(URL, session=session, app_key=APP_KEY)

    printed = "".join(traceback.format_exception(excinfo.value))
    assert APP_KEY not in printed


def test_non_json_body_raises():
    # Documents an accepted limitation: a 200 carrying an HTML maintenance page
    # raises before anything is landed, so the page itself isn't kept.
    session = FakeSession(make_response(body=b"<html>Back soon</html>"))
    with pytest.raises(requests.JSONDecodeError):
        call_api(URL, session=session)


# --- create_robust_session -----------------------------------------------------
# Testing that retries really happen would need a real HTTP server. These check
# the configuration instead: cheaper, and it's the configuration that's ours.


def test_session_retries_only_temporary_failures():
    retry = create_robust_session().get_adapter(URL).max_retries

    assert retry.total == 3
    assert set(retry.status_forcelist) == {429, 500, 502, 503, 504}
    # A 404 won't fix itself, so it isn't retried.
    assert 404 not in retry.status_forcelist


def test_session_retries_only_get():
    # GET only reads, so repeating it is harmless; a retried POST could act twice.
    retry = create_robust_session().get_adapter(URL).max_retries
    assert set(retry.allowed_methods) == {"GET"}


def test_session_retry_settings_are_configurable():
    retry = create_robust_session(retries=5, backoff_factor=2).get_adapter(URL).max_retries
    assert retry.total == 5
    assert retry.backoff_factor == 2


def test_session_identifies_itself():
    assert create_robust_session().headers["User-Agent"] == "tfl-ttl/0.1"
