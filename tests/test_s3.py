# Tests for s3.py, using MagicMock in place of the boto3 client.
#
# MagicMock is an object that accepts any method call, returns another mock,
# and records every call so a test can check it afterwards. It suits s3.py
# because the questions here are "was put_object called, with what?", not "how
# does S3 behave?". (For tfl_api.py, behaviour mattered, so it used a hand-written
# fake and real Response objects instead.)

import io
import logging
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import ClientError

from tfl_ttl.s3 import download_prefix, upload_to_s3

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


# --- download_prefix -----------------------------------------------------------

PREFIX = "raw/tfl_verify/modes"
KEY_A = "raw/tfl_verify/modes/poll_date=2026-10-01/20261001T080001Z.json.gz"
KEY_B = "raw/tfl_verify/modes/poll_date=2026-10-02/20261002T080001Z.json.gz"


def stock_bucket(s3_client, pages, contents):
    """Make the mock serve `pages` from the paginator and `contents[key]` from get_object."""
    s3_client.get_paginator.return_value.paginate.return_value = pages
    # side_effect as a function: called with the same arguments as get_object,
    # and whatever it returns becomes get_object's return value. A real S3 body
    # is a stream with .read(), so BytesIO stands in for it.
    s3_client.get_object.side_effect = lambda Bucket, Key: {"Body": io.BytesIO(contents[Key])}


def page(*keys):
    return {"Contents": [{"Key": k} for k in keys]}


def test_download_keeps_each_key_path(s3_client, tmp_path):
    stock_bucket(s3_client, [page(KEY_A)], {KEY_A: b"gzip-a"})

    downloaded = download_prefix(s3_client, BUCKET, PREFIX, tmp_path)

    # The poll_date=... folder survives, so local tools can read it as a partition.
    assert downloaded == [tmp_path / KEY_A]
    assert (tmp_path / KEY_A).read_bytes() == b"gzip-a"
    s3_client.get_paginator.assert_called_once_with("list_objects_v2")
    s3_client.get_paginator.return_value.paginate.assert_called_once_with(
        Bucket=BUCKET, Prefix=PREFIX
    )


def test_download_reads_every_page(s3_client, tmp_path):
    # S3 returns at most 1,000 keys per listing; the paginator yields one page each.
    stock_bucket(s3_client, [page(KEY_A), page(KEY_B)], {KEY_A: b"a", KEY_B: b"b"})

    downloaded = download_prefix(s3_client, BUCKET, PREFIX, tmp_path)

    assert downloaded == [tmp_path / KEY_A, tmp_path / KEY_B]


def test_download_skips_folder_markers(s3_client, tmp_path):
    stock_bucket(s3_client, [page("raw/tfl_verify/modes/", KEY_A)], {KEY_A: b"a"})

    downloaded = download_prefix(s3_client, BUCKET, PREFIX, tmp_path)

    assert downloaded == [tmp_path / KEY_A]
    s3_client.get_object.assert_called_once_with(Bucket=BUCKET, Key=KEY_A)


def test_download_skips_files_already_present(s3_client, tmp_path):
    existing = tmp_path / KEY_A
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"already here")
    stock_bucket(s3_client, [page(KEY_A, KEY_B)], {KEY_A: b"a", KEY_B: b"b"})

    downloaded = download_prefix(s3_client, BUCKET, PREFIX, tmp_path)

    # Raw files never change, so the existing copy is kept and not re-fetched.
    assert downloaded == [tmp_path / KEY_B]
    assert existing.read_bytes() == b"already here"
    s3_client.get_object.assert_called_once_with(Bucket=BUCKET, Key=KEY_B)


def test_download_of_an_empty_prefix_returns_nothing(s3_client, tmp_path, caplog):
    # A listing with no matches has no "Contents" key at all.
    stock_bucket(s3_client, [{"KeyCount": 0}], {})
    caplog.set_level(logging.INFO, logger="tfl_ttl.s3")

    assert download_prefix(s3_client, BUCKET, PREFIX, tmp_path) == []
    assert f"Downloaded 0 new file(s) from s3://{BUCKET}/{PREFIX}" in caplog.text


def test_download_refuses_keys_that_escape_the_folder(s3_client, tmp_path):
    # An S3 key is just a string; "../" in one would otherwise write outside
    # the destination folder.
    sneaky = "raw/tfl_verify/../../../outside.txt"
    stock_bucket(s3_client, [page(sneaky)], {sneaky: b"x"})
    dest = tmp_path / "dest"

    with pytest.raises(ValueError, match="Refusing to write"):
        download_prefix(s3_client, BUCKET, "raw/tfl_verify", dest)

    s3_client.get_object.assert_not_called()
