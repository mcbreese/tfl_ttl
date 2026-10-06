# Tests for schedule.py: a pure function, so every case is just a datetime in
# and a decision out. No clock-faking needed: the time is passed in.
#
# The dates are chosen around the clocks changing:
#   Tue 6 Oct 2026  BST (summer): London = UTC + 1
#   Tue 8 Dec 2026  GMT (winter): London = UTC
#   Sun 25 Oct 2026 clocks go back at 02:00 London, so the day itself is GMT
#   Mon 5 Oct / Mon 7 Dec 2026  Mondays, for the weekly run

from datetime import date, datetime, timedelta, timezone

import pytest

from tfl_ttl.feeds import TWICE_DAILY
from tfl_ttl.schedule import plan_scheduled_run


def utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# Each UTC pair has exactly one run that polls. Which one depends on GMT/BST.
@pytest.mark.parametrize(
    ("scheduled_at", "should_run"),
    [
        # Summer (BST): 07:00 and 16:00 UTC are 08:00 and 17:00 London.
        (utc(2026, 10, 6, 7), True),
        (utc(2026, 10, 6, 8), False),  # 09:00 London
        (utc(2026, 10, 6, 16), True),
        (utc(2026, 10, 6, 17), False),  # 18:00 London
        # Winter (GMT): London equals UTC, so 08:00 and 17:00 UTC poll.
        (utc(2026, 12, 8, 7), False),  # 07:00 London
        (utc(2026, 12, 8, 8), True),
        (utc(2026, 12, 8, 16), False),  # 16:00 London
        (utc(2026, 12, 8, 17), True),
        # The day the clocks go back: already GMT by 07:00.
        (utc(2026, 10, 25, 7), False),
        (utc(2026, 10, 25, 8), True),
    ],
    ids=[
        "bst-07utc",
        "bst-08utc",
        "bst-16utc",
        "bst-17utc",
        "gmt-07utc",
        "gmt-08utc",
        "gmt-16utc",
        "gmt-17utc",
        "clocks-back-07utc",
        "clocks-back-08utc",
    ],
)
def test_exactly_one_run_of_each_utc_pair_polls(scheduled_at, should_run):
    assert plan_scheduled_run(scheduled_at, end_date=None).should_run is should_run


def test_weekday_poll_is_twice_daily_feeds_only():
    plan = plan_scheduled_run(utc(2026, 10, 6, 7), end_date=None)  # Tue 08:00 London
    assert plan.frequency == TWICE_DAILY


@pytest.mark.parametrize(
    "scheduled_at",
    [utc(2026, 10, 5, 7), utc(2026, 12, 7, 8)],  # Monday 08:00 London, BST then GMT
    ids=["monday-bst", "monday-gmt"],
)
def test_monday_morning_polls_every_feed(scheduled_at):
    plan = plan_scheduled_run(scheduled_at, end_date=None)
    assert plan.should_run is True
    # None means "no frequency filter": weekly feeds as well as twice-daily.
    assert plan.frequency is None


def test_monday_evening_is_twice_daily_only():
    plan = plan_scheduled_run(utc(2026, 10, 5, 16), end_date=None)  # Mon 17:00 London
    assert plan.frequency == TWICE_DAILY


def test_a_minute_past_the_hour_is_not_a_poll_time():
    # Only an exact 08:00 or 17:00 counts; anything else is not one of ours.
    assert plan_scheduled_run(utc(2026, 10, 6, 7, 30), end_date=None).should_run is False


# The end date is inclusive and judged in London time.
@pytest.mark.parametrize(
    ("end_date", "should_run"),
    [
        (date(2026, 10, 6), True),  # on the end date: still runs
        (date(2026, 10, 5), False),  # the day after it: skips
        (None, True),  # no end date
    ],
    ids=["on-end-date", "after-end-date", "no-end-date"],
)
def test_end_date_is_inclusive(end_date, should_run):
    plan = plan_scheduled_run(utc(2026, 10, 6, 16), end_date)  # Tue 17:00 London
    assert plan.should_run is should_run


def test_skip_reasons_say_why():
    assert "not 08:00 or 17:00" in plan_scheduled_run(utc(2026, 10, 6, 8), None).reason
    assert "past the end date" in plan_scheduled_run(utc(2026, 10, 6, 7), date(2026, 10, 1)).reason


def test_a_non_utc_time_gives_the_same_answer():
    # The same instant written with a +01:00 offset: still 08:00 London.
    bst = timezone(timedelta(hours=1))
    same_moment = datetime(2026, 10, 6, 8, 0, tzinfo=bst)
    assert plan_scheduled_run(same_moment, None) == plan_scheduled_run(utc(2026, 10, 6, 7), None)


def test_a_time_without_a_timezone_is_refused():
    # "07:00" with no timezone could mean UTC or London: too ambiguous to guess.
    with pytest.raises(ValueError, match="timezone-aware"):
        plan_scheduled_run(datetime(2026, 10, 6, 7), end_date=None)
