# Moving bytes in and out of S3. Knows nothing about TfL, records or keys: it
# uploads whatever it's given to whatever key it's given, and downloads a prefix
# for local profiling.

import logging
from pathlib import Path

# boto3 builds its clients dynamically, so there's no S3 client class to point
# at. BaseClient is the common parent. For autocomplete on put_object's
# arguments, install boto3-stubs[s3] and use S3Client instead.
from botocore.client import BaseClient

logger = logging.getLogger(__name__)


def upload_to_s3(s3_client: BaseClient, bucket: str, key: str, body: bytes) -> dict:
    """Upload gzipped JSON to S3. Raises botocore ClientError if the upload fails."""
    # The client is passed in, not created here: one client per run instead of
    # one per upload, and a test can pass in a fake.
    #
    # Logged before the call, so if the upload raises, the log shows which key failed.
    logger.info("Uploading %d bytes to s3://%s/%s", len(body), bucket, key)

    # If this returns at all, S3 has stored the object; failure raises. boto3
    # retries throttling and temporary S3 errors itself before giving up.
    # An existing object at the same key is silently overwritten.
    response = s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        # The body is gzip, so say so. Don't also set ContentEncoding="gzip":
        # some clients then decompress silently on download.
        ContentType="application/gzip",
        # boto3 sends a SHA256 of the body; S3 recalculates it and rejects the
        # upload if they differ, so corrupted bytes can't be stored.
        ChecksumAlgorithm="SHA256",
    )

    # Security is mostly outside this code: S3 encrypts objects at rest by
    # default, the bucket should keep Block Public Access on, and the role
    # used to run this should only be allowed s3:PutObject on the raw prefix.
    logger.info("Uploaded s3://%s/%s etag=%s", bucket, key, response["ETag"])

    # Unused by the pipeline, but kept: the ETag and ChecksumSHA256 are a record
    # of what S3 stored, handy in the notebook and in tests.
    return response


def download_prefix(s3_client: BaseClient, bucket: str, prefix: str, dest_dir: Path) -> list[Path]:
    """Copy every object under prefix into dest_dir, keeping each key's folder path.

    For local profiling. Needs a client with read access: the pipeline's own
    writer credentials deliberately can't read. Returns the newly downloaded files.
    """
    dest_dir = Path(dest_dir).resolve()
    downloaded = []

    # list_objects_v2 returns at most 1,000 keys per call. The paginator keeps
    # asking until there are none left, so a large prefix isn't silently cut short.
    pages = s3_client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
    for page in pages:
        # A page with no matches has no "Contents" key at all, hence .get(..., []).
        for obj in page.get("Contents", []):
            key = obj["Key"]
            # Zero-byte "folder" markers made by the S3 console, not real files.
            if key.endswith("/"):
                continue

            # Keeping the key's path preserves the poll_date=... folders, so local
            # tools can read them as partitions, like Athena will.
            target = (dest_dir / key).resolve()
            # Keys are just strings: one containing "../" could write outside
            # dest_dir. Refuse rather than trust the bucket's contents.
            if not target.is_relative_to(dest_dir):
                raise ValueError(f"Refusing to write {key!r} outside {dest_dir}")

            # Raw files are never changed once written, so an existing copy is current.
            if target.exists():
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(s3_client.get_object(Bucket=bucket, Key=key)["Body"].read())
            downloaded.append(target)

    logger.info("Downloaded %d new file(s) from s3://%s/%s", len(downloaded), bucket, prefix)
    return downloaded
