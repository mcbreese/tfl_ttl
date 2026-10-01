# Tests for feeds.py: pure functions, so no fakes needed.
#
# pytest collects every test_* function in every test_*.py file under tests/.
# A test passes if it finishes without raising; a failed assert raises, and
# pytest shows both sides of the comparison.

import pytest

from tfl_ttl.feeds import FEEDS, FREQUENCIES, Call, expand_calls, validate_payload

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


def test_every_url_is_https_tfl():
    for feed in FEEDS:
        assert feed.url.startswith("https://api.tfl.gov.uk/"), feed.name
