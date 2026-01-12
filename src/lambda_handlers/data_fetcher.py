"""Lambda handler for fetching ZwiftPower results."""

import json
import logging
import os
from datetime import datetime

import boto3

from src.config import get_tour_config
from src.fetcher import ZwiftPowerClient, fetch_stage_results
from src.models import DEFAULT_PENALTY_CONFIG
from src.processor import process_stage_results

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
s3_client = boto3.client("s3")
secretsmanager_client = boto3.client("secretsmanager")
lambda_client = boto3.client("lambda")


def get_zwiftpower_credentials() -> tuple[str, str]:
    """Get ZwiftPower credentials from Secrets Manager."""
    secret_arn = os.environ.get("ZWIFTPOWER_SECRET_ARN", "")
    if not secret_arn:
        raise ValueError("ZWIFTPOWER_SECRET_ARN not configured")

    response = secretsmanager_client.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])

    return secret.get("username", ""), secret.get("password", "")


def load_riders_from_s3(bucket: str, key: str = "config/riders.json"):
    """Load rider registry from S3."""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        data = json.loads(response["Body"].read().decode("utf-8"))

        from src.models import RiderRegistry

        return RiderRegistry.model_validate(data)
    except s3_client.exceptions.NoSuchKey:
        logger.warning(f"Riders file not found: s3://{bucket}/{key}")
        return None


def load_event_ids_from_s3(bucket: str, key: str = "config/event_ids.json"):
    """Load event IDs from S3."""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        data = json.loads(response["Body"].read().decode("utf-8"))
        return {int(k): v for k, v in data.items()}
    except s3_client.exceptions.NoSuchKey:
        logger.warning(f"Event IDs file not found: s3://{bucket}/{key}")
        return {}


def load_event_timestamps_from_s3(
    bucket: str, key: str = "config/event_timestamps.json"
):
    """Load event timestamps from S3 for penalty calculation."""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        data = json.loads(response["Body"].read().decode("utf-8"))
        # Convert string timestamps to datetime objects
        return {k: datetime.fromisoformat(v) for k, v in data.items()}
    except s3_client.exceptions.NoSuchKey:
        logger.warning(f"Event timestamps file not found: s3://{bucket}/{key}")
        return {}


def save_results_to_s3(
    bucket: str,
    stage: int,
    group: str,
    results: list,
    tour_id: str = "tdz-2026",
):
    """Save stage results to S3."""
    key = f"results/{tour_id}/stage_{stage}_group_{group}.json"
    data = [r.model_dump(mode="json") for r in results]

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, indent=2, default=str),
        ContentType="application/json",
    )

    logger.info(f"Saved {len(results)} results to s3://{bucket}/{key}")


def invoke_processor_lambda():
    """Invoke the results processor Lambda to generate the website."""
    processor_arn = os.environ.get("PROCESSOR_LAMBDA_ARN", "")
    if not processor_arn:
        logger.warning(
            "PROCESSOR_LAMBDA_ARN not configured, skipping processor invocation"
        )
        return None

    try:
        response = lambda_client.invoke(
            FunctionName=processor_arn,
            InvocationType="Event",  # Async invocation
            Payload=json.dumps({"source": "data_fetcher"}),
        )
        logger.info(f"Invoked processor Lambda, status: {response['StatusCode']}")
        return response
    except Exception as e:
        logger.error(f"Failed to invoke processor Lambda: {e}")
        return None


def handler(event, context):  # noqa: ARG001
    """
    Lambda handler for fetching ZwiftPower results.

    Triggered hourly by EventBridge, or manually with optional stage override.

    Event payload options:
        stage_override: int - Force fetch for a specific stage number (1-6)
    """
    logger.info("Starting ZwiftPower data fetch")
    logger.info(f"Event: {json.dumps(event)}")

    data_bucket = os.environ.get("DATA_BUCKET", "")

    if not data_bucket:
        raise ValueError("DATA_BUCKET not configured")

    try:
        # Load configuration
        rider_registry = load_riders_from_s3(data_bucket)
        if not rider_registry:
            logger.error("No rider registry found")
            return {"statusCode": 500, "body": "No rider registry"}

        event_ids = load_event_ids_from_s3(data_bucket)
        event_timestamps = load_event_timestamps_from_s3(data_bucket)
        tour_config = get_tour_config()

        # Get credentials
        username, password = get_zwiftpower_credentials()

        # Check for stage override in event payload
        stage_override = event.get("stage_override") if event else None

        if stage_override:
            # Manual override - fetch specific stage regardless of dates
            current_stage = tour_config.get_stage(int(stage_override))
            if not current_stage:
                return {"statusCode": 400, "body": f"Invalid stage: {stage_override}"}
            logger.info(f"Stage override: fetching Stage {stage_override}")
            is_provisional = False  # Treat overridden fetches as final
        else:
            # Normal operation - use current active stage
            current_stage = tour_config.current_stage
            if not current_stage:
                logger.info("No active stage")
                return {"statusCode": 200, "body": "No active stage"}
            is_provisional = current_stage.is_active

        logger.info(f"Processing Stage {current_stage.number}: {current_stage.name}")

        # Get event IDs for current stage
        stage_event_ids = event_ids.get(current_stage.number, [])
        if not stage_event_ids:
            logger.warning(f"No event IDs configured for Stage {current_stage.number}")
            return {"statusCode": 200, "body": "No event IDs configured"}

        # Fetch results from ZwiftPower
        with ZwiftPowerClient(username, password) as client:
            # Attempt authentication (optional - public data may be accessible)
            try:
                client.authenticate()
            except Exception as e:
                logger.warning(f"Authentication failed: {e}")

            # Fetch results for current stage
            race_results = fetch_stage_results(
                client,
                stage_event_ids,
                current_stage.number,
                rider_registry,
                event_timestamps,
            )

        logger.info(f"Fetched {len(race_results)} results")

        if race_results:
            # Process results with handicaps and penalties
            group_a, group_b, uncategorized = process_stage_results(
                race_results,
                rider_registry,
                current_stage.number,
                is_provisional=is_provisional,
                penalty_config=DEFAULT_PENALTY_CONFIG,
                stage=current_stage,
            )

            # Save to S3
            tour_id = tour_config.tour_id
            save_results_to_s3(data_bucket, current_stage.number, "A", group_a, tour_id)
            save_results_to_s3(data_bucket, current_stage.number, "B", group_b, tour_id)

            # Save uncategorized results if any
            if uncategorized:
                save_results_to_s3(
                    data_bucket,
                    current_stage.number,
                    "uncategorized",
                    uncategorized,
                    tour_id,
                )

            logger.info(
                f"Processed Stage {current_stage.number}: "
                f"{len(group_a)} Group A, {len(group_b)} Group B, {len(uncategorized)} Uncategorized"
            )

            # Trigger processor Lambda to regenerate website
            invoke_processor_lambda()

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Success",
                    "stage": current_stage.number,
                    "results_fetched": len(race_results),
                }
            ),
        }

    except Exception as e:
        logger.exception(f"Error fetching results: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
