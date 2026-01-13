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

        # Build event_names dict from course configuration
        event_names = {}
        for course in current_stage.courses:
            event_names.update(course.event_names)

        # Fetch event names from ZwiftPower if not in course config
        # This is needed for race penalty detection
        if stage_event_ids:
            missing_names = [eid for eid in stage_event_ids if eid not in event_names]
            if missing_names:
                logger.info(
                    f"Fetching event names for {len(missing_names)} events "
                    "for race penalty detection"
                )
                try:
                    with ZwiftPowerClient(username, password) as client:
                        try:
                            client.authenticate()
                        except Exception as e:
                            logger.warning(f"Authentication failed: {e}")

                        from src.fetcher.events import search_events_api

                        # Search for recent Tour de Zwift events
                        discovered_events = search_events_api(
                            client, "Tour de Zwift", days=14
                        )

                        # Map event IDs to names
                        for event in discovered_events:
                            event_id = event.get("id")
                            if event_id in missing_names:
                                event_names[event_id] = event.get("name", "")

                        found_count = len(
                            [e for e in missing_names if e in event_names]
                        )
                        logger.info(
                            f"Fetched names for {found_count} of {len(missing_names)} events via search"
                        )

                        # For remaining events without names, try fetching individually
                        # Limit to first 50 events to avoid Lambda timeout and rate limiting
                        still_missing = [
                            eid for eid in missing_names if eid not in event_names
                        ]
                        if still_missing:
                            max_individual_fetches = min(50, len(still_missing))
                            logger.info(
                                f"Fetching event details individually for up to {max_individual_fetches} "
                                f"of {len(still_missing)} remaining events"
                            )
                            from src.fetcher.events import get_event_details

                            # Fetch in batches to avoid timeouts
                            individual_count = 0
                            for event_id in still_missing[:max_individual_fetches]:
                                try:
                                    details = get_event_details(client, event_id)
                                    event_names[event_id] = details.get("title", "")
                                    individual_count += 1
                                except Exception as e:
                                    logger.debug(
                                        f"Failed to fetch details for event {event_id}: {e}"
                                    )
                                    continue

                            logger.info(
                                f"Fetched names for {individual_count} additional events individually"
                            )
                            logger.info(
                                f"Total: {found_count + individual_count} of {len(missing_names)} events have names"
                            )

                except Exception as e:
                    logger.warning(f"Failed to fetch event names: {e}")

        # If no event IDs configured, try dynamic discovery
        if not stage_event_ids:
            logger.info(
                f"No event IDs configured for Stage {current_stage.number}, "
                "attempting dynamic discovery"
            )
            try:
                from src.fetcher.events import find_tdz_race_events_with_timestamps

                with ZwiftPowerClient(username, password) as client:
                    # Attempt authentication for API access
                    try:
                        client.authenticate()
                    except Exception as e:
                        logger.warning(f"Authentication failed: {e}")

                    # Discover events for this stage
                    from src.fetcher.events import search_events_api

                    # Search for events to get names and metadata
                    discovered_events = search_events_api(
                        client, "Tour de Zwift", days=14
                    )

                    # Filter to events matching this stage
                    # Get route from primary course
                    stage_route = (
                        current_stage.courses[0].route if current_stage.courses else ""
                    )
                    events_with_ts = find_tdz_race_events_with_timestamps(
                        client,
                        current_stage.number,
                        stage_route,
                        current_stage.start_datetime.date(),
                        current_stage.end_datetime.date(),
                    )

                    if events_with_ts:
                        stage_event_ids = [event_id for event_id, _ in events_with_ts]
                        # Update event_timestamps and event_names with discovered data
                        for event_id, event_dt in events_with_ts:
                            if event_dt and event_id not in event_timestamps:
                                event_timestamps[event_id] = event_dt
                            # Find event name from discovered events
                            for discovered_event in discovered_events:
                                if discovered_event.get("id") == event_id:
                                    event_names[event_id] = discovered_event.get(
                                        "name", ""
                                    )
                                    break

                        logger.info(
                            f"Dynamically discovered {len(stage_event_ids)} events "
                            f"for Stage {current_stage.number}"
                        )
            except Exception as e:
                logger.error(f"Dynamic discovery failed: {e}")

        if not stage_event_ids:
            logger.warning(
                f"No event IDs found for Stage {current_stage.number} "
                "(neither configured nor discovered)"
            )
            return {"statusCode": 200, "body": "No event IDs found"}

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
                event_names,
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
