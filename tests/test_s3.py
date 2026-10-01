# Tests for s3.py, using MagicMock in place of the boto3 client.
#
# MagicMock is an object that accepts any method call, returns another mock,
# and records every call so a test can check it afterwards. It suits s3.py
# because the questions here are "was put_object called, with what?", not "how
# does S3 behave?". (For tfl_api.py, behaviour mattered, so it used a hand-written
# fake and real Response objects instead.)

import logging
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import ClientError

from tfl_ttl.s3 import upload_to_s3

BUCKET = "test-bucket"
KEY = "raw/tfl/line_status/poll_date=2026-09-30/20260930T070005Z_tube.json.gz"
BODY = b"\x1f\x8b fake gzip bytes"


# scope="module": built once and shared by every test in this file. Fine here,
# because the real client is only a template and no test changes it. It makes
# no network call, and needs no credentials until a request is actually sent.
@pytest.fixture(scope="module")
def real_s3_client():
    return boto3.client("s3", region_name="eu-west-2")


# Default scope ("function"): a fresh mock for every test. Sharing one would leak
# recorded calls and side_effect from one test into the next.
@pytest.fixture
def s3_client(real_s3_client):
    """A MagicMock shaped like a real S3 client, with a canned put_object response."""
    # spec= restricts the mock to attributes the real client actually has. A
    # plain MagicMock() would accept a typo like put_objekt, record the call,
    # and let the test pass while the real code would crash.
    client = MagicMock(spec=real_s3_client)
    client.put_object.return_value = {"ETag": '"abc123"', "ChecksumSHA256": "c2hhMjU2"}
    return client


def test_uploads_with_the_expected_arguments(s3_client):
    upload_to_s3(s3_client, BUCKET, KEY, BODY)

    # Fails if put_object wasn't called, was called more than once, or was called
    # with any argument different, missing or extra.
    s3_client.put_object.assert_called_once_with(
        Bucket=BUCKET,
        Key=KEY,
        Body=BODY,
        ContentType="application/gzip",
        ChecksumAlgorithm="SHA256",
    )


def test_returns_the_s3_response(s3_client):
    response = upload_to_s3(s3_client, BUCKET, KEY, BODY)
    # `is`: the very dict put_object returned, passed straight back.
    assert response is s3_client.put_object.return_value


def test_logs_before_and_after_the_upload(s3_client, caplog):
    caplog.set_level(logging.INFO, logger="tfl_ttl.s3")

    upload_to_s3(s3_client, BUCKET, KEY, BODY)

    messages = [record.getMessage() for record in caplog.records]
    assert messages == [
        f"Uploading {len(BODY)} bytes to s3://{BUCKET}/{KEY}",
        f'Uploaded s3://{BUCKET}/{KEY} etag="abc123"',
    ]


def test_upload_failure_raises_and_names_the_key_in_the_log(s3_client, caplog):
    # side_effect makes the mock raise instead of returning.
    s3_client.put_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "PutObject"
    )
    caplog.set_level(logging.INFO, logger="tfl_ttl.s3")

    # The error must reach run(), where it's counted against this feed.
    with pytest.raises(ClientError, match="AccessDenied"):
        upload_to_s3(s3_client, BUCKET, KEY, BODY)

    # The "Uploading" line is logged before the call, so even when the upload
    # raises, the log says which key it was. There's no "Uploaded" line.
    assert f"Uploading {len(BODY)} bytes to s3://{BUCKET}/{KEY}" in caplog.text
    assert "Uploaded" not in caplog.text
