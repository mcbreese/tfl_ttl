"""S3 helpers for landing raw TfL API responses.

Deliberately minimal: one function to upload a local file (or bytes) to the
configured bucket under a given key. Extend once the ingestion script's
partitioning scheme (e.g. date-based prefixes) is decided.
"""

from __future__ import annotations

import boto3

from tfl_ttl.config import AWS_PROFILE, AWS_REGION, S3_BUCKET


def _client():
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    return session.client("s3")


def upload_bytes(data: bytes, key: str, bucket: str | None = None) -> None:
    """Upload raw bytes (e.g. a JSON API response) to S3 at the given key."""
    _client().put_object(Bucket=bucket or S3_BUCKET, Key=key, Body=data)
