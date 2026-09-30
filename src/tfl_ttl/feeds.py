# What to call: the registry of TfL endpoints and the rules for each.
#
# To poll a new endpoint, add one Feed to FEEDS. Nothing else changes:
# expand_calls turns it into requests, and __main__ polls whatever it's given.

from dataclasses import dataclass

# Tuples rather than lists: module-level constants can't be changed by accident.
ACCEPTED_MODES = ("dlr", "elizabeth-line", "overground", "tube")

TWICE_DAILY = "twice_daily"
WEEKLY = "weekly"
FREQUENCIES = (TWICE_DAILY, WEEKLY)


# Feed and Call are the notebook's two dict shapes, given names:
#   Feed = one endpoint as configured, with its list of modes (stg_api_dict)
#   Call = one actual HTTP request, one mode filled in (final_api_dict)
#
# @dataclass writes __init__, a readable print, and == from the fields below.
# frozen=True makes instances read-only, since this is configuration.
#
# The main gain over dicts: a misspelled field (frequncy=...) raises TypeError
# when FEEDS is built, i.e. on import, before anything runs. With a dict, the
# typo is accepted, and .get("frequency") would quietly return None, so the
# feed would silently never match a frequency and never be polled.


@dataclass(frozen=True)
class Feed:
    """One TfL endpoint and the rules for polling it."""

    name: str
    url: str
    frequency: str
    # allow_empty is ingestion policy: can an empty list be a real answer?
    allow_empty: bool
    # Fields with defaults go last. The default must be immutable: dataclasses
    # refuse a list default, as one shared list would be reused by every Feed.
    modes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Call:
    """A single resolved request: one feed, for one mode."""

    feed: str
    url: str
    # Type hints (str | None = "a string or None") are documentation for
    # editors and linters; Python doesn't enforce them at runtime.
    mode: str | None
    allow_empty: bool


FEEDS = (
    Feed(
        name="modes",
        url="https://api.tfl.gov.uk/Line/Meta/Modes",
        frequency=WEEKLY,
        allow_empty=False,
    ),
    Feed(
        name="severity",
        url="https://api.tfl.gov.uk/Line/Meta/Severity",
        frequency=WEEKLY,
        allow_empty=False,
    ),
    Feed(
        name="disruption_categories",
        url="https://api.tfl.gov.uk/Line/Meta/DisruptionCategories",
        frequency=WEEKLY,
        allow_empty=False,
    ),
    Feed(
        name="lines",
        url="https://api.tfl.gov.uk/Line/Mode/{mode}",
        frequency=WEEKLY,
        allow_empty=False,
        modes=ACCEPTED_MODES,
    ),
    Feed(
        name="stop_points",
        url="https://api.tfl.gov.uk/StopPoint/Mode/{mode}",
        frequency=WEEKLY,
        allow_empty=False,
        modes=ACCEPTED_MODES,
    ),
    Feed(
        name="line_status",
        url="https://api.tfl.gov.uk/Line/Mode/{mode}/Status",
        frequency=TWICE_DAILY,
        allow_empty=False,
        modes=ACCEPTED_MODES,
    ),
    Feed(
        # An empty response means nothing is disrupted, which is real data, not a failure.
        name="stop_point_disruptions",
        url="https://api.tfl.gov.uk/StopPoint/Mode/{mode}/Disruption",
        frequency=TWICE_DAILY,
        allow_empty=True,
        modes=ACCEPTED_MODES,
    ),
)


def expand_calls(frequency: str | None = None, feeds: tuple[Feed, ...] = FEEDS) -> list[Call]:
    """Resolve feeds into one Call per mode, optionally filtered to a frequency."""
    # argparse in __main__ already restricts --frequency, but the notebook (or a
    # future Lambda) can call this directly and skip it. Without this check a
    # typo like "Weekly" matches nothing, polls nothing, and the run ends green.
    if frequency is not None and frequency not in FREQUENCIES:
        raise ValueError(f"Unknown frequency {frequency!r}, expected one of {FREQUENCIES}")

    # Returns a new list rather than appending to one passed in (as the
    # notebook's get_api_urls did), so every call is independent and the caller
    # doesn't need to set up an empty list first.
    calls = []
    for feed in feeds:
        if frequency and feed.frequency != frequency:
            continue
        # Truthiness: an empty tuple, list, string, dict, 0 or None counts as
        # False in an if. So this reads "if the feed has any modes".
        if feed.modes:
            for mode in feed.modes:
                calls.append(
                    Call(
                        feed=feed.name,
                        url=feed.url.format(mode=mode),
                        mode=mode,
                        allow_empty=feed.allow_empty,
                    )
                )
        else:
            calls.append(
                Call(feed=feed.name, url=feed.url, mode=None, allow_empty=feed.allow_empty)
            )
    return calls


def validate_payload(payload: object, call: Call) -> None:
    """Raise if the payload is unusable. Everything softer is recorded, not raised."""
    # Only two hard fails, by design: not a list, or empty where empty isn't
    # allowed. Stricter checks belong in dbt tests on staging, where a failure
    # can be fixed by rerunning against raw. Messages name the feed and mode but
    # never include payload data. {x!r} shows quotes, so stray spaces are visible.
    if not isinstance(payload, list):
        raise ValueError(f"{call.feed} ({call.mode}): expected a list, got {type(payload).__name__}")
    if not payload and not call.allow_empty:
        raise ValueError(f"{call.feed} ({call.mode}): empty response")
