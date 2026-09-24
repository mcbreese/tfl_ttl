from __future__ import annotations

from dataclasses import dataclass

ACCEPTED_MODES = ("dlr", "elizabeth-line", "overground", "tube")

TWICE_DAILY = "twice_daily"
WEEKLY = "weekly"


@dataclass(frozen=True)
class Feed:
    """One TfL endpoint and the rules for polling it."""

    name: str
    url: str
    frequency: str
    allow_empty: bool
    modes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Call:
    """A single resolved request: one feed, for one mode."""

    feed: str
    url: str
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
    calls = []
    for feed in feeds:
        if frequency and feed.frequency != frequency:
            continue
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
    if not isinstance(payload, list):
        raise ValueError(f"{call.feed} ({call.mode}): expected a list, got {type(payload).__name__}")
    if not payload and not call.allow_empty:
        raise ValueError(f"{call.feed} ({call.mode}): empty response")
