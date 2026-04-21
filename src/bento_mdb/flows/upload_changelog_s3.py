"""Upload model changelog files to S3."""

from __future__ import annotations

import boto3
from prefect import flow, get_run_logger
from prefect.blocks.system import Secret


@flow(name="upload-changelog-s3", log_prints=True)
def upload_changelog_s3_flow(
    s3_key: str,
    changelog_content: str,
) -> str:
    """Upload a changelog XML to S3 and return the S3 key."""
    logger = get_run_logger()

    bucket = Secret.load("s3-changelog-bucket").get()

    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=changelog_content.encode("utf-8"),
        ContentType="application/xml",
    )

    logger.info("Uploaded changelog to s3://%s/%s", bucket, s3_key)
    return s3_key
