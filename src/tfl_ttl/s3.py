from __future__ import annotations

import logging

from botocore.client import BaseClient

logger = logging.getLogger(__name__)


def upload_to_s3(s3_client: BaseClient, bucket: str, key: str, body: bytes) -> dict:
    """Upload gzipped JSON to S3. Raises botocore ClientError if the upload fails."""
    logger.info("Uploading %d bytes to s3://%s/%s", len(body), bucket, key)

    response = s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/gzip",
        ChecksumAlgorithm="SHA256",
    )

    logger.info("Uploaded s3://%s/%s etag=%s", bucket, key, response["ETag"])
    return response
