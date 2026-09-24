from __future__ import annotations

import argparse
import logging

import boto3
import requests

from tfl_ttl import config
from tfl_ttl.feeds import TWICE_DAILY, WEEKLY, Call, expand_calls, validate_payload
from tfl_ttl.record import build_record, generate_s3_key, poll_datetime, to_gzipped_line
from tfl_ttl.s3 import upload_to_s3
from tfl_ttl.tfl_api import call_api, create_robust_session

logger = logging.getLogger(__name__)


def poll(call: Call, session: requests.Session, s3_client) -> None:
    polled_at = poll_datetime()
    payload = call_api(call.url, session=session, app_key=config.TFL_APP_KEY)

    record = build_record(payload, call, polled_at)
    key = generate_s3_key(config.S3_PREFIX, call, polled_at)
    upload_to_s3(s3_client, config.S3_BUCKET, key, to_gzipped_line(record))

    # Validate after landing: TfL has no history, so an unexpected payload should
    # cost a failed run, not a poll we can never fetch again.
    validate_payload(payload, call)


def run(frequency: str | None = None) -> None:
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")

    s3_client = boto3.client("s3", region_name=config.AWS_REGION)
    session = create_robust_session()

    failures = []
    for call in expand_calls(frequency):
        try:
            poll(call, session, s3_client)
        except Exception:
            # Keep polling the other feeds; one bad feed shouldn't lose the rest.
            logger.exception("Failed: %s (%s)", call.feed, call.mode)
            failures.append(f"{call.feed} ({call.mode})")

    if failures:
        raise RuntimeError(f"{len(failures)} feed(s) failed: {', '.join(failures)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll TfL feeds and land them in S3.")
    parser.add_argument(
        "--frequency",
        choices=[TWICE_DAILY, WEEKLY],
        help="Only poll feeds with this frequency. Omit to poll all of them.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )
    run(args.frequency)


if __name__ == "__main__":
    main()
