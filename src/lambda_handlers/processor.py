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
from src.processor.handicap import _calculate_positions_and_gaps

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


def load_manual_results_from_s3(
    bucket: str,
    stage: int,
    group: str,
) -> list[StageResult]:
    """Load manual result overrides from S3.

    Manual results are stored separately from automatic results and
    take precedence when merged. This allows adding results for riders
    who haven't opted into ZwiftPower data sharing.

    Args:
        bucket: S3 bucket name
        stage: Stage number (1-6)
        group: Race group (A, B, or uncategorized)

    Returns:
        List of manual StageResult entries, empty if no file exists
    """
    key = f"results/manual/stage_{stage}_group_{group}.json"

    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        data = json.loads(response["Body"].read().decode("utf-8"))
        results = [StageResult.model_validate(r) for r in data]
        if results:
            logger.info(
                f"Loaded {len(results)} manual results for stage {stage} group {group}"
            )
        return results
    except s3_client.exceptions.NoSuchKey:
        return []


def merge_results(
    automatic: list[StageResult],
    manual: list[StageResult],
) -> list[StageResult]:
    """Merge manual results with automatic results.

    Manual results take precedence over automatic results for the same rider_id.
    This allows overriding or adding results for riders missing from ZwiftPower.

    Args:
        automatic: Results fetched automatically from ZwiftPower
        manual: Manually entered results

    Returns:
        Merged list with manual results overriding automatic by rider_id
    """
    # Create lookup of automatic results by rider_id
    result_map = {r.rider_id: r for r in automatic}

    # Override with manual results
    for manual_result in manual:
        result_map[manual_result.rider_id] = manual_result
        logger.info(
            f"Manual override for rider {manual_result.rider_name} "
            f"({manual_result.rider_id})"
        )

    return list(result_map.values())


def load_all_results_from_s3(
    bucket: str,
    tour_id: str = "tdz-2026",
) -> tuple[
    dict[int, list[StageResult]],
    dict[int, list[StageResult]],
    dict[int, list[StageResult]],
]:
    """Load all stage results from S3, including manual overrides.

    Loads automatic results from ZwiftPower and merges with any manual
    result overrides. Manual results take precedence by rider_id.
    """
    group_a_results: dict[int, list[StageResult]] = {}
    group_b_results: dict[int, list[StageResult]] = {}
    uncategorized_results: dict[int, list[StageResult]] = {}

    for stage in range(1, 7):
        # Load automatic results from ZwiftPower
        a_results = load_stage_results_from_s3(bucket, stage, "A", tour_id)

        # Load and merge manual results (manual overrides automatic by rider_id)
        manual_a = load_manual_results_from_s3(bucket, stage, "A")
        if manual_a:
            a_results = merge_results(a_results, manual_a)
            # Recalculate positions after merging manual results
            a_results = _calculate_positions_and_gaps(a_results, use_stage_time=True)

        if a_results:
            group_a_results[stage] = a_results

        # Same for Group B
        b_results = load_stage_results_from_s3(bucket, stage, "B", tour_id)
        manual_b = load_manual_results_from_s3(bucket, stage, "B")
        if manual_b:
            b_results = merge_results(b_results, manual_b)
            # Recalculate positions after merging manual results
            b_results = _calculate_positions_and_gaps(b_results, use_stage_time=True)

        if b_results:
            group_b_results[stage] = b_results

        # Same for uncategorized
        uncat_results = load_stage_results_from_s3(
            bucket, stage, "uncategorized", tour_id
        )
        manual_uncat = load_manual_results_from_s3(bucket, stage, "uncategorized")
        if manual_uncat:
            uncat_results = merge_results(uncat_results, manual_uncat)
            # Recalculate positions after merging manual results
            uncat_results = _calculate_positions_and_gaps(
                uncat_results, use_stage_time=True
            )

        if uncat_results:
            uncategorized_results[stage] = uncat_results

    return group_a_results, group_b_results, uncategorized_results


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
        group_a_results, group_b_results, uncategorized_results = (
            load_all_results_from_s3(data_bucket, tour_id)
        )

        logger.info(
            f"Loaded results for {tour_id}: {len(group_a_results)} stages with Group A, "
            f"{len(group_b_results)} stages with Group B, "
            f"{len(uncategorized_results)} stages with Uncategorized"
        )

        # Calculate completed stages based on data
        completed_stages = max(len(group_a_results), len(group_b_results))

        # Determine current stage and provisional status from actual stage dates
        active_stage = tour_config.current_stage
        if active_stage:
            # A stage is actively in progress
            current_stage = active_stage.number
            is_stage_in_progress = True
        else:
            # No stage currently active (between stages or tour complete)
            current_stage = min(completed_stages, 6) if completed_stages > 0 else 1
            is_stage_in_progress = False

        # Build tour standings (include guests for client-side filtering)
        last_updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        tour_standings = build_tour_standings(
            group_a_results,
            group_b_results,
            completed_stages,
            current_stage,
            last_updated,
            is_stage_in_progress,
            include_guests=True,  # Include guests so they can be toggled on/off
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
                uncat = uncategorized_results.get(stage, [])
                if group_a or group_b or uncat:
                    stage_results[stage] = (group_a, group_b, uncat)

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
