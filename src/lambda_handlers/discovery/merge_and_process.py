"""Lambda handler for merging events and triggering processing."""

import json
import logging
import os
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from src.config import get_tour_config
from src.fetcher import ZwiftPowerClient, fetch_stage_results
from src.fetcher.events import find_tdz_race_events_with_timestamps
from src.models import DEFAULT_PENALTY_CONFIG, RiderRegistry
from src.persistence import RawEventStore
from src.processor import process_stage_results

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Lazy-loaded AWS clients (avoid import-time initialization for testability)
_clients: dict = {}


def _get_s3_client():
    """Get or create S3 client."""
    if "s3" not in _clients:
        _clients["s3"] = boto3.client("s3")
    return _clients["s3"]


def _get_lambda_client():
    """Get or create Lambda client."""
    if "lambda" not in _clients:
        _clients["lambda"] = boto3.client("lambda")
    return _clients["lambda"]


def _get_secretsmanager_client():
    """Get or create Secrets Manager client."""
    if "secretsmanager" not in _clients:
        _clients["secretsmanager"] = boto3.client("secretsmanager")
    return _clients["secretsmanager"]


def get_zwiftpower_credentials() -> tuple[str, str]:
    """Get ZwiftPower credentials from Secrets Manager."""
    secret_arn = os.environ.get("ZWIFTPOWER_SECRET_ARN", "")
    if not secret_arn:
        raise ValueError("ZWIFTPOWER_SECRET_ARN not configured")

    response = _get_secretsmanager_client().get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])

    return secret.get("username", ""), secret.get("password", "")


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


def save_results_to_s3(
    bucket: str,
    stage: str,
    group: str,
    results: list,
    tour_id: str = "tdz-2026",
):
    """Save stage results to S3."""
    key = f"results/{tour_id}/stage_{stage}_group_{group}.json"
    data = [r.model_dump(mode="json") for r in results]

    _get_s3_client().put_object(
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
        response = _get_lambda_client().invoke(
            FunctionName=processor_arn,
            InvocationType="Event",  # Async invocation
            Payload=json.dumps({"source": "discovery_pipeline"}),
        )
        logger.info(f"Invoked processor Lambda, status: {response['StatusCode']}")
        return response
    except Exception as e:
        logger.error(f"Failed to invoke processor Lambda: {e}")
        return None


def handler(event, context):  # noqa: ARG001
    """
    Merge events to persistent store and process results.

    This is the final step in the discovery pipeline:
    1. Merge newly discovered events to the persistent event store
    2. Process all active stages with the updated event store
    3. Trigger the processor Lambda to regenerate the website

    Input (from Step Function):
        fetched_events: list[dict] - Results from FetchEventResults Map state
        bucket: str - S3 bucket name
        stages: list[dict] - Stage configurations
        tour_id: str - Tour identifier
        unique_events: list[dict] - Unique events from aggregation

    Output:
        events_merged: int - Number of new events added to store
        stages_processed: list[str] - Stage numbers that were processed
        status: str - "success" or "error"
    """
    logger.info(f"Merging and processing: {json.dumps(event)[:500]}...")

    bucket = event.get("bucket", "")
    stages = event.get("stages", [])
    tour_id = event.get("tour_id", "tdz-2026")
    fetched_events = event.get("fetched_events", [])

    if not bucket:
        bucket = os.environ.get("DATA_BUCKET", "")

    if not bucket:
        raise ValueError("DATA_BUCKET not configured")

    try:
        # 1. Merge to persistent event store
        raw_store = RawEventStore(bucket)
        existing_events = raw_store.load_events()

        # Convert fetched events to the format expected by merge_events
        new_events = [
            {
                "id": e["event_id"],
                "name": e.get("event_name", ""),
                "timestamp": e.get("timestamp", 0),
            }
            for e in fetched_events
            if e.get("results_count", 0) > 0
        ]

        merged = raw_store.merge_events(existing_events, new_events)
        raw_store.save_events(merged)

        new_event_count = len(merged) - len(existing_events)
        logger.info(
            f"Merged {new_event_count} new events to store (total: {len(merged)})"
        )

        # 2. Process each stage with updated event store
        tour_config = get_tour_config()
        rider_registry = load_riders_from_s3(bucket)
        username, password = get_zwiftpower_credentials()

        # Build event_names dict from fetched events
        event_names = {
            e["event_id"]: e.get("event_name", "") for e in fetched_events if e
        }
        event_names.update(raw_store.get_event_names(merged))

        # Build event_timestamps dict
        event_timestamps = {}
        for e in fetched_events:
            if e and e.get("timestamp"):
                event_timestamps[e["event_id"]] = datetime.fromtimestamp(
                    e["timestamp"], tz=UTC
                )

        processed_stages = []
        total_results = 0

        for stage_info in stages:
            stage_number = stage_info["number"]
            current_stage = tour_config.get_stage(stage_number)

            if not current_stage:
                logger.warning(f"Stage {stage_number} not found in tour config")
                continue

            logger.info(f"Processing Stage {stage_number}: {current_stage.name}")

            # Filter events for this stage from persisted store
            events_list = [
                {
                    "id": event_id,
                    "name": event_data.get("name", ""),
                    "timestamp": event_data.get("timestamp", 0),
                    "route_id": event_data.get("route_id", ""),
                }
                for event_id, event_data in merged.items()
            ]

            stage_route = (
                current_stage.courses[0].route if current_stage.courses else ""
            )

            try:
                with ZwiftPowerClient(username, password) as client:
                    try:
                        client.authenticate()
                    except Exception as e:
                        logger.warning(f"Authentication failed: {e}")

                    events_with_ts = find_tdz_race_events_with_timestamps(
                        client,
                        current_stage.number,
                        stage_route,
                        current_stage.start_datetime.date(),
                        current_stage.end_datetime.date(),
                        preloaded_events=events_list,
                        event_search_patterns=current_stage.event_search_patterns,
                    )

                    if not events_with_ts:
                        logger.warning(
                            f"No events found for Stage {current_stage.number}"
                        )
                        continue

                    stage_event_ids = [event_id for event_id, _ in events_with_ts]
                    for event_id, event_dt in events_with_ts:
                        if event_dt and event_id not in event_timestamps:
                            event_timestamps[event_id] = event_dt

                    logger.info(
                        f"Found {len(stage_event_ids)} events for Stage {current_stage.number}"
                    )

                    # Fetch results
                    category_filter = (
                        current_stage.courses[0].option_letter
                        if current_stage.courses
                        else None
                    )

                    race_results = fetch_stage_results(
                        client,
                        stage_event_ids,
                        current_stage.number,
                        rider_registry,
                        event_timestamps,
                        event_names,
                        category_filter,
                        expected_route=stage_route,
                    )

                if not race_results:
                    logger.warning(
                        f"No results fetched for Stage {current_stage.number}"
                    )
                    continue

                logger.info(
                    f"Fetched {len(race_results)} results for Stage {current_stage.number}"
                )

                # Process results with handicaps and penalties
                group_a, group_b, uncategorized = process_stage_results(
                    race_results,
                    rider_registry,
                    current_stage.number,
                    is_provisional=True,  # Active stages are provisional
                    penalty_config=DEFAULT_PENALTY_CONFIG,
                    stage=current_stage,
                )

                # Save to S3
                save_results_to_s3(bucket, current_stage.number, "A", group_a, tour_id)
                save_results_to_s3(bucket, current_stage.number, "B", group_b, tour_id)

                if uncategorized:
                    save_results_to_s3(
                        bucket,
                        current_stage.number,
                        "uncategorized",
                        uncategorized,
                        tour_id,
                    )

                processed_stages.append(current_stage.number)
                total_results += len(race_results)

                logger.info(
                    f"Processed Stage {current_stage.number}: "
                    f"{len(group_a)} Group A, {len(group_b)} Group B, "
                    f"{len(uncategorized)} Uncategorized"
                )

            except Exception as e:
                logger.error(f"Error processing Stage {stage_number}: {e}")
                continue

        # 3. Trigger processor Lambda to regenerate website
        if processed_stages:
            invoke_processor_lambda()

        return {
            "events_merged": new_event_count,
            "total_events": len(merged),
            "stages_processed": processed_stages,
            "total_results": total_results,
            "status": "success",
        }

    except Exception as e:
        logger.exception(f"Error in merge and process: {e}")
        return {
            "events_merged": 0,
            "stages_processed": [],
            "status": "error",
            "error": str(e),
        }
