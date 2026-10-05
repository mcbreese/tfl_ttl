# Shaping what lands in S3: the wrapper record, its serialised form, and its key.
#
# Pure functions: no network, no disk. Same input, same output, which makes
# them the easiest part of the pipeline to test.

import gzip
import json
from datetime import datetime, timezone

from tfl_ttl.feeds import Call, records_of


def poll_datetime() -> datetime:
    # timezone.utc makes the datetime "aware": it knows it's UTC. A plain
    # datetime.now() is local time with no zone attached, which becomes
    # ambiguous when the clocks change.
    return datetime.now(timezone.utc)


def build_record(payload: object, call: Call, polled_at: datetime) -> dict:
    """Wrap the untouched response with what's needed to audit the poll later."""
    # "Record, don't fail": these fields let a SQL query over S3 check that every
    # expected poll happened and spot suspiciously small ones, without opening
    # each response.
    #
    # The grain is the *scheduled* slot (08:00/17:00), but only the actual time
    # is stored. Staging derives the slot from polled_at in London time; a very
    # late run could be mislabelled. Revisit at M5 (pass the slot in instead?).
    #
    # This runs before validate_payload (land first, check after), so the
    # payload may not be what's expected. len() of a dict would count its keys
    # and look like a plausible record count; None says "no list where this feed
    # expects one". For wrapped feeds (list_field), it counts the inner list.
    records = records_of(payload, call)
    return {
        "polled_at": polled_at.isoformat(),
        "feed": call.feed,
        "mode": call.mode,
        # call.url never contains the app key; it's added as a request param.
        "source_url": call.url,
        "record_count": len(records) if records is not None else None,
        "response": payload,
    }


def to_gzipped_line(record: dict) -> bytes:
    """Serialise to one line of JSON, as Athena reads one record per line, then gzip it."""
    # Named for what it does: serialise and compress. "Transform" is kept for
    # the T in ELT, the modelling that happens later in dbt.
    #
    # The trailing newline keeps each record on its own line if files are ever
    # concatenated (e.g. compacting a day's polls); without it they'd merge into
    # one invalid line.
    line = json.dumps(record) + "\n"
    # gzip works on bytes, so encode the string first.
    return gzip.compress(line.encode("utf-8"))


def generate_s3_key(prefix: str, call: Call, polled_at: datetime) -> str:
    # polled_at is taken per call, and calls take well under a second each, so
    # several calls in one run can share a timestamp. Without the mode in the
    # name they'd build the same key, and S3 silently overwrites.
    mode_suffix = f"_{call.mode}" if call.mode else ""
    # poll_date=... is Hive-style partition naming, so Athena can prune by date.
    # It's the UTC date: fine for 08:00/17:00 London polls, but a poll between
    # midnight and 1am London time in summer would file under the previous day.
    #
    # {polled_at:%Y-%m-%d}: text after the colon is a format spec, and datetimes
    # accept strftime codes there. Adjacent string literals inside brackets are
    # joined automatically, so no + is needed between the lines.
    return (
        f"{prefix}/{call.feed}"
        f"/poll_date={polled_at:%Y-%m-%d}"
        f"/{polled_at:%Y%m%dT%H%M%SZ}{mode_suffix}.json.gz"
    )
