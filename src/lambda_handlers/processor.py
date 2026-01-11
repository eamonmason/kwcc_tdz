"""Lambda handler for processing results and generating website."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import boto3

from src.config import get_tour_config
from src.generator import WebsiteGenerator
from src.models import StageResult
from src.processor import build_tour_standings

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
s3_client = boto3.client("s3")
cloudfront_client = boto3.client("cloudfront")


def load_stage_results_from_s3(
    bucket: str,
    stage: int,
    group: str,
    tour_id: str = "tdz-2026",
) -> list[StageResult]:
    """Load stage results from S3."""
    key = f"results/{tour_id}/stage_{stage}_group_{group}.json"

    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        data = json.loads(response["Body"].read().decode("utf-8"))
        return [StageResult.model_validate(r) for r in data]
    except s3_client.exceptions.NoSuchKey:
        return []


def load_all_results_from_s3(
    bucket: str,
    tour_id: str = "tdz-2026",
) -> tuple[dict[int, list[StageResult]], dict[int, list[StageResult]]]:
    """Load all stage results from S3."""
    group_a_results: dict[int, list[StageResult]] = {}
    group_b_results: dict[int, list[StageResult]] = {}

    for stage in range(1, 7):
        a_results = load_stage_results_from_s3(bucket, stage, "A", tour_id)
        if a_results:
            group_a_results[stage] = a_results

        b_results = load_stage_results_from_s3(bucket, stage, "B", tour_id)
        if b_results:
            group_b_results[stage] = b_results

    return group_a_results, group_b_results


def upload_directory_to_s3(local_dir: str, bucket: str) -> int:
    """Upload directory contents to S3."""
    local_path = Path(local_dir)
    uploaded = 0

    content_types = {
        ".html": "text/html",
        ".css": "text/css",
        ".js": "application/javascript",
        ".json": "application/json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
    }

    for file_path in local_path.rglob("*"):
        if file_path.is_file():
            key = str(file_path.relative_to(local_path))
            content_type = content_types.get(
                file_path.suffix, "application/octet-stream"
            )

            s3_client.upload_file(
                str(file_path),
                bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )
            uploaded += 1
            logger.debug(f"Uploaded: {key}")

    return uploaded


def invalidate_cloudfront(distribution_id: str) -> str | None:
    """Create CloudFront invalidation."""
    if not distribution_id:
        logger.warning("No CloudFront distribution ID configured")
        return None

    try:
        response = cloudfront_client.create_invalidation(
            DistributionId=distribution_id,
            InvalidationBatch={
                "Paths": {"Quantity": 1, "Items": ["/*"]},
                "CallerReference": f"kwcc-tdz-{datetime.now().timestamp()}",
            },
        )
        invalidation_id = response["Invalidation"]["Id"]
        logger.info(f"Created CloudFront invalidation: {invalidation_id}")
        return invalidation_id
    except Exception as e:
        logger.error(f"Failed to invalidate CloudFront: {e}")
        return None


def handler(event, context):  # noqa: ARG001
    """
    Lambda handler for processing results and generating website.

    Can be triggered by S3 events or directly.
    """
    logger.info("Starting results processing")
    logger.info(f"Event: {json.dumps(event)}")

    data_bucket = os.environ.get("DATA_BUCKET", "")
    website_bucket = os.environ.get("WEBSITE_BUCKET", "")
    distribution_id = os.environ.get("CLOUDFRONT_DISTRIBUTION_ID", "")

    if not data_bucket or not website_bucket:
        raise ValueError("DATA_BUCKET and WEBSITE_BUCKET must be configured")

    try:
        # Get tour config
        tour_config = get_tour_config()
        tour_id = tour_config.tour_id

        # Load all results from S3
        group_a_results, group_b_results = load_all_results_from_s3(
            data_bucket, tour_id
        )

        logger.info(
            f"Loaded results for {tour_id}: {len(group_a_results)} stages with Group A, "
            f"{len(group_b_results)} stages with Group B"
        )

        # Calculate completed stages
        completed_stages = max(len(group_a_results), len(group_b_results))
        current_stage = min(completed_stages + 1, 6)

        # Build tour standings
        last_updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        tour_standings = build_tour_standings(
            group_a_results,
            group_b_results,
            completed_stages,
            current_stage,
            last_updated,
        )

        # Generate website
        with TemporaryDirectory() as temp_dir:
            generator = WebsiteGenerator(
                output_dir=temp_dir,
            )

            # Prepare stage results for generation
            stage_results = {}
            for stage in range(1, 7):
                group_a = group_a_results.get(stage, [])
                group_b = group_b_results.get(stage, [])
                if group_a or group_b:
                    stage_results[stage] = (group_a, group_b)

            # Generate all pages
            generated_files = generator.generate_all(
                stage_results,
                tour_standings,
                tour_config,
            )

            logger.info(f"Generated {len(generated_files)} files")

            # Upload to S3
            uploaded = upload_directory_to_s3(temp_dir, website_bucket)
            logger.info(f"Uploaded {uploaded} files to s3://{website_bucket}")

        # Invalidate CloudFront cache
        if distribution_id:
            invalidate_cloudfront(distribution_id)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Success",
                    "files_generated": len(generated_files),
                    "files_uploaded": uploaded,
                }
            ),
        }

    except Exception as e:
        logger.exception(f"Error processing results: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
