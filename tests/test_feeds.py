# Tests for feeds.py: pure functions, so no fakes needed.
#
# pytest collects every test_* function in every test_*.py file under tests/.
# A test passes if it finishes without raising; a failed assert raises, and
# pytest shows both sides of the comparison.

import pytest

from tfl_ttl.feeds import (
    FEED_NAMES,
    FEEDS,
    FREQUENCIES,
    Call,
    Feed,
    expand_calls,
    records_of,
    validate_payload,
)

# --- expand_calls --------------------------------------------------------------
# One test per behaviour, named after it, so a failing test's name says what broke.


def test_feed_with_modes_fills_mode_into_url():
    calls = expand_calls()
    tube_call = next(c for c in calls if c.feed == "line_status" and c.mode == "tube")
    assert tube_call.url == "https://api.tfl.gov.uk/Line/Mode/tube/Status"
    # `is False`, not `== False`: checks it's the actual boolean, not just falsy.
    assert tube_call.allow_empty is False


def test_feed_without_modes_has_mode_none_and_url_unchanged():
    calls = expand_calls()
    modes_call = next(c for c in calls if c.feed == "modes")
    assert modes_call.mode is None
    assert modes_call.url == "https://api.tfl.gov.uk/Line/Meta/Modes"


# parametrize runs one test function once per tuple, each reported as its own
# test (e.g. test_frequency_filter_returns_matching_calls[weekly-11]). It
# replaces three near-identical tests, or one test with three asserts that stops
# at the first failure.
@pytest.mark.parametrize(
    ("frequency", "expected_count"),
    [
        (None, 19),
        ("weekly", 11),
        ("twice_daily", 8),
    ],
)
def test_frequency_filter_returns_matching_calls(frequency, expected_count):
    calls = expand_calls(frequency)
    assert len(calls) == expected_count
    if frequency is not None:
        assert all(c.feed in _feed_names(frequency) for c in calls)


# A typo would otherwise match nothing, poll nothing, and the run would end green.
@pytest.mark.parametrize("bad_frequency", ["Weekly", "daily", ""])
def test_unknown_frequency_raises(bad_frequency):
    # pytest.raises passes only if the block raises this exception type.
    # match= also checks the message, so the test can't pass on some other
    # unrelated ValueError.
    with pytest.raises(ValueError, match="Unknown frequency"):
        expand_calls(bad_frequency)


# --feed: verifying one feed at a time.
@pytest.mark.parametrize(
    ("feed", "expected_count"),
    [
        ("modes", 1),
        ("lines", 4),
        ("stop_point_disruptions", 4),
    ],
)
def test_feed_filter_returns_only_that_feed(feed, expected_count):
    calls = expand_calls(feed=feed)
    assert len(calls) == expected_count
    assert {c.feed for c in calls} == {feed}


def test_feed_and_frequency_filters_combine():
    calls = expand_calls("weekly", "lines")
    assert [c.mode for c in calls] == ["dlr", "elizabeth-line", "overground", "tube"]


def test_unknown_feed_raises():
    # The CLI's choices= catches this too, but direct callers (the notebook) don't
    # go through the CLI. Without the check, a typo would poll nothing and pass.
    with pytest.raises(ValueError, match="Unknown feed 'line-status'"):
        expand_calls(feed="line-status")


def test_feed_not_polled_at_that_frequency_raises():
    # Both names are valid, but together they match nothing.
    with pytest.raises(ValueError, match="'modes' isn't polled at frequency 'twice_daily'"):
        expand_calls("twice_daily", "modes")


def test_feed_names_are_checked_against_the_registry_passed_in():
    only_one = (
        Feed(name="solo", url="https://api.tfl.gov.uk/x", frequency="weekly", allow_empty=False),
    )
    assert [c.feed for c in expand_calls(feed="solo", feeds=only_one)] == ["solo"]
    with pytest.raises(ValueError, match="Unknown feed 'modes'"):
        expand_calls(feed="modes", feeds=only_one)


def test_feed_names_match_the_registry():
    # argparse's --feed choices come from FEED_NAMES.
    assert FEED_NAMES == tuple(f.name for f in FEEDS)


def _feed_names(frequency):
    """Helper, not a test: no test_ prefix, so pytest doesn't collect it."""
    return {f.name for f in FEEDS if f.frequency == frequency}


# --- validate_payload ----------------------------------------------------------
# The ingestion policy: hard fail only on "not a list", or "empty where empty
# isn't allowed". Everything else is recorded, not raised.


def _call(allow_empty):
    return Call(feed="test_feed", url="https://example.test", mode="tube", allow_empty=allow_empty)


@pytest.mark.parametrize("allow_empty", [True, False])
def test_non_empty_list_passes(allow_empty):
    # No assert needed: the test passes as long as nothing raises.
    validate_payload([{"id": "victoria"}], _call(allow_empty))


def test_empty_list_passes_when_allowed():
    # Station disruptions: [] means nothing is disrupted, which is real data.
    validate_payload([], _call(allow_empty=True))


def test_empty_list_raises_when_not_allowed(tube_status_call):
    # tube_status_call is a fixture from conftest.py: naming it as a parameter
    # is all it takes for pytest to build it and pass it in.
    with pytest.raises(ValueError, match="empty response"):
        validate_payload([], tube_status_call)


# A dict and None are the realistic shapes: an error object returned with a 200,
# or a body that parsed to null. Both must fail even where empty is allowed.
@pytest.mark.parametrize("payload", [{"message": "Service unavailable"}, None, "text"])
@pytest.mark.parametrize("allow_empty", [True, False])
def test_non_list_raises_type_error(payload, allow_empty):
    # Stacked parametrize decorators run every combination: 3 payloads x 2 = 6 tests.
    with pytest.raises(TypeError, match="expected a list"):
        validate_payload(payload, _call(allow_empty))


# --- Wrapped lists (list_field) -------------------------------------------------
# Some endpoints wrap their list in an object, e.g. stop points:
# {"pageSize": 1751, "total": 1751, "page": 1, "stopPoints": [...]}.


def _wrapped_call(allow_empty=False):
    return Call(
        feed="stop_points",
        url="https://example.test",
        mode="tube",
        allow_empty=allow_empty,
        list_field="stopPoints",
    )


@pytest.mark.parametrize(
    ("payload", "call", "expected"),
    [
        ([{"id": "a"}], _call(False), [{"id": "a"}]),  # plain feed, plain list
        ({"id": "a"}, _call(False), None),  # plain feed, but an object came back
        ({"stopPoints": [{"id": "a"}]}, _wrapped_call(), [{"id": "a"}]),  # wrapped: the inner list
        ([{"id": "a"}], _wrapped_call(), None),  # wrapped feed, but a plain list came back
        ({"total": 1}, _wrapped_call(), None),  # wrapped, but the list field is missing
        ({"stopPoints": "oops"}, _wrapped_call(), None),  # wrapped, but the field isn't a list
    ],
    ids=[
        "plain-list",
        "plain-got-object",
        "wrapped",
        "wrapped-got-list",
        "missing-field",
        "field-not-list",
    ],
)
def test_records_of_finds_the_list_or_returns_none(payload, call, expected):
    assert records_of(payload, call) == expected


def test_wrapped_payload_passes():
    validate_payload({"total": 2, "stopPoints": [{"id": "a"}, {"id": "b"}]}, _wrapped_call())


@pytest.mark.parametrize(
    "payload",
    [[{"id": "a"}], {"total": 1}, {"stopPoints": None}],
    ids=["plain-list", "missing-field", "field-is-null"],
)
def test_wrapped_feed_without_its_list_raises_type_error(payload):
    with pytest.raises(TypeError, match="expected an object with a 'stopPoints' list"):
        validate_payload(payload, _wrapped_call())


def test_empty_wrapped_list_raises_when_not_allowed():
    with pytest.raises(ValueError, match="empty response"):
        validate_payload({"total": 0, "stopPoints": []}, _wrapped_call(allow_empty=False))


def test_paged_response_missing_records_raises():
    # The guard: TfL says 5,000 exist but sent 1. Only the first page is ever
    # fetched, so without this the other 4,999 would be silently missing.
    with pytest.raises(ValueError, match="received 1 of 5000 records; the response is paged"):
        validate_payload({"total": 5000, "stopPoints": [{"id": "a"}]}, _wrapped_call())


def test_complete_single_page_passes():
    # total equal to what was sent: nothing missing.
    validate_payload(
        {"pageSize": 2, "total": 2, "page": 1, "stopPoints": [{}, {}]}, _wrapped_call()
    )


def test_stop_points_calls_carry_the_list_field():
    calls = expand_calls(feed="stop_points")
    assert {c.list_field for c in calls} == {"stopPoints"}


# --- The registry itself -------------------------------------------------------
# FEEDS is configuration, but it's still code that can be wrong. These check it
# as data, so a careless new entry fails here rather than silently at 08:00.


def test_feed_names_are_unique():
    names = [f.name for f in FEEDS]
    # Two feeds with one name would write to the same S3 folder.
    assert len(names) == len(set(names))


def test_every_feed_has_a_known_frequency():
    for feed in FEEDS:
        # The message after the comma is shown if the assert fails, so the
        # failure names the offending feed instead of just "False".
        assert feed.frequency in FREQUENCIES, f"{feed.name} has frequency {feed.frequency!r}"


def test_mode_placeholder_matches_modes():
    for feed in FEEDS:
        has_placeholder = "{mode}" in feed.url
        # With modes but no {mode}: every mode would request the same URL.
        # With {mode} but no modes: the literal "{mode}" would be sent to TfL.
        assert has_placeholder == bool(feed.modes), f"{feed.name}: url and modes disagree"


def test_list_field_is_unset_or_a_real_name():
    # An empty string would never match a key, failing every poll of that feed.
    for feed in FEEDS:
        assert feed.list_field is None or feed.list_field.strip(), feed.name


def test_every_url_is_https_tfl():
    for feed in FEEDS:
        assert feed.url.startswith("https://api.tfl.gov.uk/"), feed.name
