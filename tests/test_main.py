# Tests for __main__.py: a whole run, with only the outside world replaced.
#
# TfL (call_api) and AWS (boto3.client) are faked. Everything in between is the
# real code: feeds, record and s3. So these tests check the glue: that one bad
# feed doesn't stop the others, that bad data still lands, and that the run
# fails loudly at the end.
#
# THE RULE: patch a name where it's looked up, not where it's defined.
# __main__.py does `from tfl_ttl.tfl_api import call_api`, which copies the
# function into __main__'s own namespace when it's imported. So:
#   monkeypatch.setattr(tfl_ttl.tfl_api, "call_api", fake)   -> no effect on run()
#   monkeypatch.setattr(tfl_ttl.__main__, "call_api", fake)  -> what run() sees
# config is different: __main__ imports the module and reads config.S3_BUCKET
# each time, so patching the attribute on config itself works.

import gzip
import json
import logging
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import boto3
import pytest

import tfl_ttl.__main__ as main
from tfl_ttl import config

DLR_STATUS_URL = "https://api.tfl.gov.uk/Line/Mode/dlr/Status"


@pytest.fixture(scope="module")
def real_s3_client():
    return boto3.client("s3", region_name="eu-west-2")


@pytest.fixture
def pipeline(monkeypatch, real_s3_client):
    """Replace TfL and AWS for one test, and expose what happened."""
    monkeypatch.setattr(config, "S3_BUCKET", "test-bucket")
    monkeypatch.setattr(config, "S3_PREFIX", "raw/test")
    monkeypatch.setattr(config, "TFL_APP_KEY", "test-key")

    s3_client = MagicMock(spec=real_s3_client)
    s3_client.put_object.return_value = {"ETag": '"etag"'}
    # The fake factory is a MagicMock too, so tests can check it was (or wasn't) called.
    make_client = MagicMock(return_value=s3_client)
    monkeypatch.setattr(boto3, "client", make_client)

    # A test sets responses[url] to a payload, or to an exception to raise.
    # Anything not listed gets a normal one-item list.
    responses = {}
    api_calls = []

    def fake_call_api(url, session=None, app_key=None):
        api_calls.append({"url": url, "app_key": app_key})
        result = responses.get(url, [{"id": "ok"}])
        if isinstance(result, Exception):
            raise result
        return result

    # Patched on __main__, where run() looks it up. See THE RULE above.
    monkeypatch.setattr(main, "call_api", fake_call_api)

    # SimpleNamespace bundles several values into one object with attributes,
    # so a test writes pipeline.s3_client rather than unpacking a tuple.
    return SimpleNamespace(
        s3_client=s3_client,
        make_client=make_client,
        responses=responses,
        api_calls=api_calls,
    )


def uploaded_keys(pipeline):
    """The Key of every put_object call, in order."""
    # call_args_list holds one entry per call; .kwargs is its keyword arguments.
    return [c.kwargs["Key"] for c in pipeline.s3_client.put_object.call_args_list]


# --- run(): the happy path -----------------------------------------------------


def test_run_uploads_one_file_per_call(pipeline):
    main.run("twice_daily")

    keys = uploaded_keys(pipeline)
    assert len(keys) == 8
    assert all(k.startswith("raw/test/") for k in keys)
    pipeline.make_client.assert_called_once_with("s3", region_name=config.AWS_REGION)


def test_run_with_a_feed_polls_only_that_feed(pipeline):
    main.run(feed="lines")

    keys = uploaded_keys(pipeline)
    # One call per mode, and nothing from any other feed.
    assert len(keys) == 4
    assert all(k.startswith("raw/test/lines/") for k in keys)


def test_run_passes_the_app_key_to_every_request(pipeline):
    main.run("weekly")
    assert {c["app_key"] for c in pipeline.api_calls} == {"test-key"}


def test_uploaded_body_is_the_wrapped_record(pipeline):
    pipeline.responses[DLR_STATUS_URL] = [{"id": "dlr"}]
    main.run("twice_daily")

    dlr_status_upload = next(
        c
        for c in pipeline.s3_client.put_object.call_args_list
        if c.kwargs["Key"].startswith("raw/test/line_status/") and "_dlr" in c.kwargs["Key"]
    )
    record = json.loads(gzip.decompress(dlr_status_upload.kwargs["Body"]))
    assert record["feed"] == "line_status"
    assert record["mode"] == "dlr"
    assert record["source_url"] == DLR_STATUS_URL
    assert record["response"] == [{"id": "dlr"}]


# --- run(): failures -----------------------------------------------------------


def test_missing_bucket_fails_before_any_work(pipeline, monkeypatch):
    monkeypatch.setattr(config, "S3_BUCKET", None)

    with pytest.raises(RuntimeError, match="S3_BUCKET is not set"):
        main.run("weekly")

    # Run-wide problems stop everything up front: no client, no TfL requests.
    pipeline.make_client.assert_not_called()
    assert pipeline.api_calls == []


def test_one_failing_feed_does_not_stop_the_others(pipeline, caplog):
    pipeline.responses[DLR_STATUS_URL] = ConnectionError("TfL unreachable")

    with pytest.raises(RuntimeError, match=r"^1 feed\(s\) failed: line_status \(dlr\)$"):
        main.run("twice_daily")

    # The other 7 still landed.
    assert len(uploaded_keys(pipeline)) == 7

    # logger.exception logs at ERROR and attaches the traceback (exc_info).
    [failure] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert failure.getMessage() == "Failed: line_status (dlr)"
    assert failure.exc_info is not None


def test_bad_payload_still_lands_then_fails_the_run(pipeline):
    # Land first, check after: a dict where a list is expected is uploaded as
    # evidence, then counted as a failure.
    pipeline.responses[DLR_STATUS_URL] = {"message": "Service unavailable"}

    with pytest.raises(RuntimeError, match=r"line_status \(dlr\)"):
        main.run("twice_daily")

    assert len(uploaded_keys(pipeline)) == 8
    assert any("line_status" in k and "_dlr" in k for k in uploaded_keys(pipeline))


def test_every_failure_is_listed(pipeline):
    pipeline.responses[DLR_STATUS_URL] = ConnectionError("down")
    pipeline.responses["https://api.tfl.gov.uk/Line/Mode/tube/Status"] = []

    with pytest.raises(RuntimeError) as excinfo:
        main.run("twice_daily")

    message = str(excinfo.value)
    assert message.startswith("2 feed(s) failed:")
    assert "line_status (dlr)" in message
    assert "line_status (tube)" in message


def test_unknown_frequency_raises_before_any_request(pipeline):
    with pytest.raises(ValueError, match="Unknown frequency"):
        main.run("Weekly")
    assert pipeline.api_calls == []


# --- main(): the command line --------------------------------------------------


@pytest.fixture
def fake_run(monkeypatch):
    """Replace run() so main() can be tested without polling anything."""
    calls = []
    # Records (frequency, feed) for each call.
    monkeypatch.setattr(
        main, "run", lambda frequency=None, feed=None: calls.append((frequency, feed))
    )
    # main() calls logging.basicConfig, which would change logging for every
    # later test. Replace it for the duration of the test.
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: None)
    return calls


# argparse reads sys.argv: the program name, then its arguments.
@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["tfl_ttl"], (None, None)),
        (["tfl_ttl", "--frequency", "weekly"], ("weekly", None)),
        (["tfl_ttl", "--frequency", "twice_daily"], ("twice_daily", None)),
        (["tfl_ttl", "--feed", "lines"], (None, "lines")),
        (["tfl_ttl", "--frequency", "weekly", "--feed", "lines"], ("weekly", "lines")),
    ],
)
def test_main_passes_arguments_to_run(fake_run, monkeypatch, argv, expected):
    monkeypatch.setattr(sys, "argv", argv)
    main.main()
    assert fake_run == [expected]


# argparse doesn't raise ValueError for a bad choice: it prints usage and calls
# sys.exit(2), which raises SystemExit. 2 is the conventional "bad command line" code.
@pytest.mark.parametrize(
    ("argv", "bad_value"),
    [
        (["tfl_ttl", "--frequency", "Weekly"], "Weekly"),
        (["tfl_ttl", "--feed", "line-status"], "line-status"),
    ],
)
def test_main_rejects_unknown_values(fake_run, monkeypatch, capsys, argv, bad_value):
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as excinfo:
        main.main()

    assert excinfo.value.code == 2
    # capsys captures what was printed; argparse writes errors to stderr.
    assert f"invalid choice: '{bad_value}'" in capsys.readouterr().err
    assert fake_run == []
