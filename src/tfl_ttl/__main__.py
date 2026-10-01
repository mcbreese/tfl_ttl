# The entry point: the only module that knows about all the others.
#
# `python -m tfl_ttl` runs this file, because running a package executes the
# __main__.py inside it.
#
# Three layers, each wrapping the one before:
#   poll()  one request: fetch -> record -> key -> upload -> validate
#   run()   one run: setup once, loop over every call, collect failures
#   main()  the command line: read --frequency, configure logging, call run()
# Anything can plug in at the layer it needs: the notebook or a future Lambda
# handler calls run() directly, and a test can call poll() with fakes. Moving
# off GitHub Actions means a new small entry point that calls run(), nothing else.

import argparse
import logging

import boto3
import requests
from botocore.client import BaseClient

from tfl_ttl import config
from tfl_ttl.feeds import FREQUENCIES, Call, expand_calls, validate_payload
from tfl_ttl.record import build_record, generate_s3_key, poll_datetime, to_gzipped_line
from tfl_ttl.s3 import upload_to_s3
from tfl_ttl.tfl_api import call_api, create_robust_session

logger = logging.getLogger(__name__)


def poll(call: Call, session: requests.Session, s3_client: BaseClient) -> None:
    polled_at = poll_datetime()
    payload = call_api(call.url, session=session, app_key=config.TFL_APP_KEY)

    record = build_record(payload, call, polled_at)
    key = generate_s3_key(config.S3_PREFIX, call, polled_at)
    upload_to_s3(s3_client, config.S3_BUCKET, key, to_gzipped_line(record))

    # Validate after landing: TfL has no history, so an unexpected payload should
    # cost a failed run, not a poll we can never fetch again.
    validate_payload(payload, call)


def run(frequency: str | None = None) -> None:
    # Run-wide problems fail here, before the loop, once and clearly. Missing
    # credentials also surface here: boto3.client raises (e.g. ProfileNotFound)
    # outside the try below, so nothing is polled that couldn't be saved.
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")

    # Created once per run and shared by every call.
    s3_client = boto3.client("s3", region_name=config.AWS_REGION)
    session = create_robust_session()

    failures = []
    for call in expand_calls(frequency):
        # Per-call problems are caught here so one bad feed doesn't lose the rest.
        # The broad `except Exception` isn't swallowing anything: the traceback
        # is logged, the failure is collected, and the run still raises below.
        # Ctrl+C and SystemExit aren't subclasses of Exception, so they still
        # stop the run immediately.
        try:
            poll(call, session, s3_client)
        except Exception:
            # logger.exception logs at ERROR level and includes the traceback.
            logger.exception("Failed: %s (%s)", call.feed, call.mode)
            failures.append(f"{call.feed} ({call.mode})")

    # Raising makes the process exit non-zero, which turns GitHub Actions red.
    if failures:
        raise RuntimeError(f"{len(failures)} feed(s) failed: {', '.join(failures)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll TfL feeds and land them in S3.")
    parser.add_argument(
        "--frequency",
        # Rejects anything else before run() is reached. Direct callers of run()
        # skip this, which is why expand_calls checks the value too.
        choices=FREQUENCIES,
        help="Only poll feeds with this frequency. Omit to poll all of them.",
    )
    args = parser.parse_args()

    # Configured here, once, in the entry point. Library modules only create
    # loggers; configuring logging inside them would fight whatever imports them.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )
    run(args.frequency)


# __name__ is "__main__" only when this file runs as the program (python -m
# tfl_ttl). When imported, e.g. `from tfl_ttl.__main__ import run` in the
# notebook, it's "tfl_ttl.__main__", so main() doesn't run. Without this guard,
# importing run would start a poll, or in Jupyter, make argparse choke on the
# kernel's own arguments and exit.
if __name__ == "__main__":
    main()
