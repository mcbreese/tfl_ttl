# Tests for record.py: pure functions, so no fakes needed.
#
# No clock-faking either. poll_datetime() is the only function that reads the
# clock; build_record and generate_s3_key take polled_at as a parameter, so a
# test just passes a fixed time in. Passing values in rather than reaching for
# them (the clock, the environment, the network) is what makes code easy to test.

import gzip
import json
from datetime import datetime, timedelta, timezone

import pytest

from tfl_ttl.feeds import Call
from tfl_ttl.record import build_record, generate_s3_key, poll_datetime, to_gzipped_line

# A fixture defined in a test file is only visible to tests in that file.
# Shared ones (fixed_time, tube_status_call) live in conftest.py.


@pytest.fixture
def modes_call():
    """A feed with no modes, so no mode in the key."""
    return Call(
        feed="modes",
        url="https://api.tfl.gov.uk/Line/Meta/Modes",
        mode=None,
        allow_empty=False,
    )


# --- poll_datetime -------------------------------------------------------------


def test_poll_datetime_is_timezone_aware_utc():
    polled_at = poll_datetime()
    # A naive datetime (no tzinfo) would be ambiguous when the clocks change.
    assert polled_at.tzinfo == timezone.utc
    # The real clock can't be asserted exactly, so check it's "now, roughly".
    assert abs(datetime.now(timezone.utc) - polled_at) < timedelta(seconds=5)


# --- build_record --------------------------------------------------------------


def test_build_record_wraps_payload_with_poll_metadata(tube_status_call, fixed_time):
    payload = [{"id": "victoria"}, {"id": "central"}]

    record = build_record(payload, tube_status_call, fixed_time)

    # Comparing whole dicts checks every key and value at once, and fails on an
    # unexpected extra key too. pytest's failure output shows only the differences.
    assert record == {
        "polled_at": "2026-09-30T07:00:05+00:00",
        "feed": "line_status",
        "mode": "tube",
        "source_url": "https://api.tfl.gov.uk/Line/Mode/tube/Status",
        "record_count": 2,
        "response": payload,
    }


def test_build_record_keeps_the_response_untouched(tube_status_call, fixed_time):
    payload = [{"id": "victoria", "nested": {"a": [1, 2]}}]
    record = build_record(payload, tube_status_call, fixed_time)
    # `is` checks it's the very same object, not a copy or a reshaped version:
    # the raw layer stores exactly what TfL sent.
    assert record["response"] is payload


# build_record runs before validate_payload (land first), so it must cope with
# payloads that aren't lists. len() of a dict counts its keys, which would look
# like a believable record count; None is honest.
@pytest.mark.parametrize(
    ("payload", "expected_count"),
    [
        ([], 0),
        ([{"id": "a"}], 1),
        ({"message": "error", "status": 500}, None),
        (None, None),
    ],
)
def test_record_count_is_none_unless_payload_is_a_list(
    payload, expected_count, tube_status_call, fixed_time
):
    assert build_record(payload, tube_status_call, fixed_time)["record_count"] == expected_count


# Wrapped feeds count the list inside the object, not the object's keys.
@pytest.mark.parametrize(
    ("payload", "expected_count"),
    [
        ({"total": 3, "stopPoints": [{}, {}, {}]}, 3),
        ({"total": 0, "stopPoints": []}, 0),
        ({"total": 3}, None),  # the list is missing: honest None, not 1 (the key count)
    ],
)
def test_record_count_for_a_wrapped_feed_counts_the_inner_list(payload, expected_count, fixed_time):
    call = Call(
        feed="stop_points",
        url="https://api.tfl.gov.uk/StopPoint/Mode/tube",
        mode="tube",
        allow_empty=False,
        list_field="stopPoints",
    )
    record = build_record(payload, call, fixed_time)
    assert record["record_count"] == expected_count
    # The response is still stored exactly as received, wrapper and all.
    assert record["response"] is payload


# --- to_gzipped_line -----------------------------------------------------------


def test_gzipped_line_round_trips(tube_status_call, fixed_time):
    record = build_record([{"id": "victoria"}], tube_status_call, fixed_time)

    body = to_gzipped_line(record)

    # A round trip (encode, then decode, then compare) checks nothing was lost
    # or mangled, without the test having to know the exact compressed bytes.
    assert isinstance(body, bytes)
    assert json.loads(gzip.decompress(body)) == record


def test_gzipped_line_is_exactly_one_line(tube_status_call, fixed_time):
    # TfL descriptions can contain newlines. json.dumps escapes them as \n
    # inside the string, so the record still occupies one physical line, which
    # is what Athena needs.
    payload = [{"description": "Minor delays.\nLifts out of service."}]
    record = build_record(payload, tube_status_call, fixed_time)

    text = gzip.decompress(to_gzipped_line(record)).decode("utf-8")

    assert text.endswith("\n")
    assert text.count("\n") == 1


# --- generate_s3_key -----------------------------------------------------------


def test_key_for_feed_with_mode(tube_status_call, fixed_time):
    key = generate_s3_key("raw/tfl", tube_status_call, fixed_time)
    assert key == "raw/tfl/line_status/poll_date=2026-09-30/20260930T070005Z_tube.json.gz"


def test_key_for_feed_without_mode(modes_call, fixed_time):
    key = generate_s3_key("raw/tfl", modes_call, fixed_time)
    assert key == "raw/tfl/modes/poll_date=2026-09-30/20260930T070005Z.json.gz"


def test_same_second_different_modes_get_different_keys(fixed_time):
    # The bug this guards against: without the mode in the name, two calls in
    # the same second build one key, and S3 silently overwrites the first.
    dlr = Call("line_status", "https://api.tfl.gov.uk/Line/Mode/dlr/Status", "dlr", False)
    tube = Call("line_status", "https://api.tfl.gov.uk/Line/Mode/tube/Status", "tube", False)
    assert generate_s3_key("raw/tfl", dlr, fixed_time) != generate_s3_key(
        "raw/tfl", tube, fixed_time
    )


def test_poll_date_is_the_utc_date(tube_status_call):
    # Documents a known caveat rather than a desired outcome: 23:30 UTC on
    # 1 July is 00:30 on 2 July in London (BST), but the key files it under
    # 1 July. Harmless for 08:00/17:00 polls. If the behaviour is ever changed
    # on purpose, this test is meant to fail and be updated with it.
    late_evening = datetime(2026, 7, 1, 23, 30, tzinfo=timezone.utc)
    key = generate_s3_key("raw/tfl", tube_status_call, late_evening)
    assert "/poll_date=2026-07-01/" in key
