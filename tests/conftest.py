# Shared test setup. pytest loads conftest.py automatically before running any
# test in this folder; nothing imports it.
#
# A fixture is a function marked @pytest.fixture. A test asks for one by naming
# it as a parameter, and pytest calls the fixture and passes in what it returns.

from datetime import datetime, timezone

import pytest

from tfl_ttl.feeds import Call


# autouse=True: applied to every test without being asked for. monkeypatch
# changes the environment for one test only and puts everything back after it.
@pytest.fixture(autouse=True)
def fake_aws_credentials(monkeypatch):
    """Make sure no test can ever reach AWS with real credentials."""
    # boto3 checks environment variables first, so dummy keys here win over
    # anything in ~/.aws. A test that forgot to fake S3 fails on auth instead of
    # writing to the real bucket.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    # raising=False: don't complain if it wasn't set in the first place.
    monkeypatch.delenv("AWS_PROFILE", raising=False)


@pytest.fixture
def fixed_time():
    """A known poll time, so expected keys and timestamps can be written out exactly."""
    return datetime(2026, 9, 30, 7, 0, 5, tzinfo=timezone.utc)


@pytest.fixture
def tube_status_call():
    """The line_status call for the tube, as expand_calls would build it."""
    return Call(
        feed="line_status",
        url="https://api.tfl.gov.uk/Line/Mode/tube/Status",
        mode="tube",
        allow_empty=False,
    )
