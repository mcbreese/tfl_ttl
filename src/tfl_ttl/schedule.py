# The scheduling gate: given when a run was SCHEDULED for, decide whether it
# should poll, and which feeds.
#
# Why it exists: GitHub schedules only in UTC, but polls are at 08:00 and 17:00
# London time, and London is UTC in winter (GMT) but UTC+1 in summer (BST). No
# single UTC time hits 08:00 London all year, so the workflow fires at both 07:00
# and 08:00 UTC (and 16:00 and 17:00), and this decides which of each pair is
# really 08:00 (or 17:00) in London. The other one skips.
#
# It works from the scheduled time, not the clock when the run actually started.
# GitHub often starts scheduled runs late; checking the real clock could mistake
# a late 07:00 run for the 08:00 one, polling twice or not at all.
#
# A pure function (no clock, network or files), so it's simple to test, and it
# doesn't know about GitHub: any scheduler can call it with a time.

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from tfl_ttl.feeds import TWICE_DAILY

# Python's built-in timezone database. On Windows it comes from the tzdata
# package (a project dependency), since Windows has no IANA database of its own.
LONDON = ZoneInfo("Europe/London")

POLL_HOURS = (8, 17)  # 08:00 and 17:00 London: the morning and evening peaks
WEEKLY_WEEKDAY = 0  # Monday (datetime.weekday(): Monday is 0, Sunday is 6)
WEEKLY_HOUR = 8  # the Monday 08:00 run also polls the weekly feeds


@dataclass(frozen=True)
class ScheduledRun:
    """The gate's answer: whether to poll, which feeds, and why (for the log)."""

    should_run: bool
    # None means every feed (weekly plus twice-daily); TWICE_DAILY means only those.
    frequency: str | None
    reason: str


def plan_scheduled_run(scheduled_at: datetime, end_date: date | None) -> ScheduledRun:
    """Decide what a run scheduled for `scheduled_at` should do."""
    # A "naive" datetime (no timezone) can't be converted to London time
    # reliably: it might mean UTC, local time, or anything. Refuse it.
    if scheduled_at.tzinfo is None:
        raise ValueError("scheduled_at must be timezone-aware, e.g. 2026-10-06T07:00:00+00:00")

    # The same moment, expressed as London wall-clock time (GMT or BST, whichever
    # applies on that date). zoneinfo knows the dates the clocks change.
    london = scheduled_at.astimezone(LONDON)
    when = london.strftime("%a %d %b %H:%M London")

    # The end date is inclusive: collection runs ON it, and stops after it.
    if end_date is not None and london.date() > end_date:
        return ScheduledRun(False, None, f"{when}: past the end date {end_date}, skipping")

    if london.minute != 0 or london.hour not in POLL_HOURS:
        return ScheduledRun(False, None, f"{when}: not 08:00 or 17:00 London, skipping")

    if london.weekday() == WEEKLY_WEEKDAY and london.hour == WEEKLY_HOUR:
        return ScheduledRun(True, None, f"{when}: Monday morning, polling all feeds")

    return ScheduledRun(True, TWICE_DAILY, f"{when}: polling twice-daily feeds")
