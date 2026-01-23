"""Lambda handler for loading configuration and preparing for distributed discovery."""

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

from src.config import get_tour_config
from src.models import RiderRegistry

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Lazy-loaded AWS clients (avoid import-time initialization for testability)
_clients: dict = {}


def _get_s3_client():
    """Get or create S3 client."""
    if "s3" not in _clients:
        _clients["s3"] = boto3.client("s3")
    return _clients["s3"]


def _get_secretsmanager_client():
    """Get or create Secrets Manager client."""
    if "secretsmanager" not in _clients:
        _clients["secretsmanager"] = boto3.client("secretsmanager")
    return _clients["secretsmanager"]


def load_riders_from_s3(bucket: str, key: str = "config/riders.json") -> RiderRegistry:
    """Load rider registry from S3."""
    try:
        response = _get_s3_client().get_object(Bucket=bucket, Key=key)
        data = json.loads(response["Body"].read().decode("utf-8"))
        return RiderRegistry.model_validate(data)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            logger.warning(f"Riders file not found: s3://{bucket}/{key}")
            return RiderRegistry(riders=[])
        raise


def get_zwiftpower_credentials() -> tuple[str, str]:
    """Get ZwiftPower credentials from Secrets Manager."""
    secret_arn = os.environ.get("ZWIFTPOWER_SECRET_ARN", "")
    if not secret_arn:
        raise ValueError("ZWIFTPOWER_SECRET_ARN not configured")

    response = _get_secretsmanager_client().get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])

    return secret.get("username", ""), secret.get("password", "")


def handler(event, context):  # noqa: ARG001
    """
    Load configuration and prepare for distributed discovery.

    Returns configuration needed for subsequent Step Function steps:
    - List of riders with ZwiftPower IDs
    - List of stages to process
    - Data bucket name
    - ZwiftPower credentials (encrypted in transit)

    Event payload options:
        stage_override: str - Force processing for a specific stage number (e.g., '1', '3.1')
    """
    logger.info("Loading configuration for distributed discovery")
    logger.info(f"Event: {json.dumps(event)}")

    data_bucket = os.environ.get("DATA_BUCKET", "")
    if not data_bucket:
        raise ValueError("DATA_BUCKET not configured")

    try:
        # Load rider registry
        rider_registry = load_riders_from_s3(data_bucket)
        if not rider_registry.riders:
            logger.error("No riders found in registry")
            return {"statusCode": 500, "body": "No rider registry"}

        # Filter to riders with ZwiftPower IDs
        riders_with_ids = [
            {"id": r.zwiftpower_id, "name": r.name}
            for r in rider_registry.riders
            if r.zwiftpower_id
        ]

        logger.info(f"Found {len(riders_with_ids)} riders with ZwiftPower IDs")

        # Get tour configuration
        tour_config = get_tour_config()

        # Determine stages to process
        stage_override = event.get("stage_override") if event else None

        if stage_override:
            stage_override_str = str(stage_override)
            current_stage = tour_config.get_stage(stage_override_str)
            if not current_stage:
                return {"statusCode": 400, "body": f"Invalid stage: {stage_override}"}
            logger.info(f"Stage override: processing Stage {stage_override_str}")
            stages_to_process = [current_stage]
        else:
            stages_to_process = tour_config.current_stages
            if not stages_to_process:
                logger.info("No active stages")
                return {
                    "statusCode": 200,
                    "body": "No active stages",
                    "riders": [],
                    "stages": [],
                }

        logger.info(
            f"Processing {len(stages_to_process)} stage(s): "
            f"{[s.number for s in stages_to_process]}"
        )

        # Get credentials
        username, password = get_zwiftpower_credentials()

        # Build stage info for Step Function
        stages_info = [
            {
                "number": stage.number,
                "name": stage.name,
                "start_date": stage.start_datetime.isoformat(),
                "end_date": stage.end_datetime.isoformat(),
                "event_search_patterns": stage.event_search_patterns,
                "option_letter": (
                    stage.courses[0].option_letter if stage.courses else "C"
                ),
            }
            for stage in stages_to_process
        ]

        return {
            "riders": riders_with_ids,
            "stages": stages_info,
            "bucket": data_bucket,
            "tour_id": tour_config.tour_id,
            "credentials": {
                "username": username,
                "password": password,
            },
        }

    except Exception as e:
        logger.exception(f"Error loading configuration: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
