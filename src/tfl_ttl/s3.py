# Putting bytes into S3. Knows nothing about TfL, records or keys: it uploads
# whatever it's given to whatever key it's given.

import logging

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
