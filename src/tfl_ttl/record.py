from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone

from tfl_ttl.feeds import Call


def poll_datetime() -> datetime:
    return datetime.now(timezone.utc)


def build_record(payload: object, call: Call, polled_at: datetime) -> dict:
    """Wrap the untouched response with what's needed to audit the poll later."""
    return {
        "polled_at": polled_at.isoformat(),
        "feed": call.feed,
        "mode": call.mode,
        "source_url": call.url,
        "record_count": len(payload) if isinstance(payload, list) else None,
        "response": payload,
    }


def to_gzipped_line(record: dict) -> bytes:
    """Serialise to one line of JSON, as Athena reads one record per line, then gzip it."""
    line = json.dumps(record) + "\n"
    return gzip.compress(line.encode("utf-8"))


def generate_s3_key(prefix: str, call: Call, polled_at: datetime) -> str:
    mode_suffix = f"_{call.mode}" if call.mode else ""
    return (
        f"{prefix}/{call.feed}"
        f"/poll_date={polled_at:%Y-%m-%d}"
        f"/{polled_at:%Y%m%dT%H%M%SZ}{mode_suffix}.json.gz"
    )
