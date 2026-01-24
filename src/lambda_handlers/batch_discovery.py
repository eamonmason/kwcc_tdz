"""
Lambda handler for batch discovery with S3 checkpointing.

This handler replaces the Step Functions pipeline with a single Lambda
that processes work incrementally, saving progress to S3 after each batch.
Work continues across multiple invocations until complete.
"""

import json
import logging
import os
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from src.config import get_tour_config
from src.discovery.batch_processor import BatchDiscoveryProcessor, build_stages_info
from src.discovery.checkpoint import CheckpointManager, DiscoveryCheckpoint
from src.discovery.results_fetcher import (
    BatchResultsFetcher,
    get_fetched_events_from_checkpoint,
)
from src.fetcher import ZwiftPowerClient, fetch_stage_results
from src.fetcher.events import find_tdz_race_events_with_timestamps
from src.models import DEFAULT_PENALTY_CONFIG, RiderRegistry
from src.persistence import RawEventStore
from src.processor import process_stage_results

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Minimum remaining time before stopping (1 minute buffer)
MIN_REMAINING_TIME_MS = 60_000

# Lazy-loaded AWS clients
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
            Payload=json.dumps({"source": "batch_discovery"}),
        )
        logger.info(f"Invoked processor Lambda, status: {response['StatusCode']}")
        return response
    except Exception as e:
        logger.error(f"Failed to invoke processor Lambda: {e}")
        return None


def has_time_remaining(context, buffer_ms: int = MIN_REMAINING_TIME_MS) -> bool:
    """Check if Lambda has enough remaining execution time."""
    if context is None:
        return True  # For local testing
    remaining = context.get_remaining_time_in_millis()
    return remaining > buffer_ms


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


def process_and_generate_website(
    bucket: str,
    checkpoint: DiscoveryCheckpoint,
    tour_id: str,
) -> dict:
    """
    Process all fetched results and generate the website.

    This is the final phase, processing all discovered events and
    triggering website generation.
    """
    logger.info("Processing results and generating website")

    # Load tour config and riders
    tour_config = get_tour_config()
    rider_registry = load_riders_from_s3(bucket)
    username, password = get_zwiftpower_credentials()

    # Load persistent event store
    raw_store = RawEventStore(bucket)
    existing_events = raw_store.load_events()

    # Merge newly discovered events to persistent store
    fetched_events = get_fetched_events_from_checkpoint(checkpoint)
    new_events = [
        {
            "id": e["event_id"],
            "name": e.get("event_name", ""),
            "timestamp": e.get("timestamp", 0),
        }
        for e in fetched_events
    ]

    merged = raw_store.merge_events(existing_events, new_events)
    raw_store.save_events(merged)

    new_event_count = len(merged) - len(existing_events)
    logger.info(f"Merged {new_event_count} new events to store (total: {len(merged)})")

    # Build event_names and event_timestamps dicts
    event_names = {e["event_id"]: e.get("event_name", "") for e in fetched_events}
    event_names.update(raw_store.get_event_names(merged))

    event_timestamps = {}
    for e in fetched_events:
        if e.get("timestamp"):
            event_timestamps[e["event_id"]] = datetime.fromtimestamp(
                e["timestamp"], tz=UTC
            )

    # Process each stage
    processed_stages = []
    total_results = 0

    for stage_number in checkpoint.stage_numbers:
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

        stage_route = current_stage.courses[0].route if current_stage.courses else ""

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
                    logger.warning(f"No events found for Stage {current_stage.number}")
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
                )

            if not race_results:
                logger.warning(f"No results fetched for Stage {current_stage.number}")
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

    # Trigger processor Lambda to regenerate website
    if processed_stages:
        invoke_processor_lambda()

    return {
        "events_merged": new_event_count,
        "total_events": len(merged),
        "stages_processed": processed_stages,
        "total_results": total_results,
    }


def handler(event, context):
    """
    Batch discovery Lambda handler with S3 checkpointing.

    This handler processes work incrementally across multiple invocations:
    1. discover_riders phase: Process rider histories to find TDZ events
    2. fetch_results phase: Fetch full results for discovered events
    3. complete phase: Process results and generate website

    Progress is saved to S3 after each batch, allowing work to resume
    if the Lambda times out or fails.

    Event payload options:
        stage_override: str - Force processing for a specific stage number
        force_restart: bool - Clear existing checkpoint and start fresh
    """
    logger.info("Batch discovery handler started")
    logger.info(f"Event: {json.dumps(event)}")

    data_bucket = os.environ.get("DATA_BUCKET", "")
    if not data_bucket:
        raise ValueError("DATA_BUCKET not configured")

    # Initialize checkpoint manager
    checkpoint_mgr = CheckpointManager(data_bucket)

    # Handle force restart
    if event and event.get("force_restart"):
        logger.info("Force restart requested, clearing checkpoint")
        checkpoint_mgr.clear()

    # Load or create checkpoint
    checkpoint = checkpoint_mgr.load()
    checkpoint.increment_run_count()

    try:
        # Load configuration
        tour_config = get_tour_config()
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
                    "status": "no_work",
                }

        # Build stages info
        stages_info = build_stages_info(stages_to_process)
        stage_numbers = [s.number for s in stages_to_process]

        logger.info(f"Processing {len(stages_to_process)} stage(s): {stage_numbers}")

        # Check if checkpoint stage_numbers match requested stages
        # If different (e.g., stage_override changed), start fresh
        if checkpoint.stage_numbers and set(checkpoint.stage_numbers) != set(
            stage_numbers
        ):
            logger.info(
                f"Checkpoint stages {checkpoint.stage_numbers} don't match "
                f"requested stages {stage_numbers}, starting fresh"
            )
            checkpoint_mgr.clear()
            checkpoint = DiscoveryCheckpoint()
            checkpoint.increment_run_count()

        # Initialize checkpoint with stage info if not already set
        if not checkpoint.stage_numbers:
            checkpoint.stage_numbers = stage_numbers
            checkpoint.tour_id = tour_config.tour_id

        # Get credentials
        username, password = get_zwiftpower_credentials()

        # Main processing loop - continue until timeout or complete
        with ZwiftPowerClient(username, password) as client:
            try:
                client.authenticate()
            except Exception as e:
                logger.warning(f"Authentication failed (continuing anyway): {e}")

            while has_time_remaining(context):
                if checkpoint.phase == "discover_riders":
                    # Phase 1: Discover events from rider histories
                    processor = BatchDiscoveryProcessor(
                        client=client,
                        stages=stages_info,
                    )

                    more_work, riders_processed, events_discovered = (
                        processor.process_next_batch(riders_with_ids, checkpoint)
                    )

                    logger.info(
                        f"Rider batch: {riders_processed} processed, "
                        f"{events_discovered} events found"
                    )

                    # Save checkpoint after each batch
                    checkpoint_mgr.save(checkpoint)

                    if not more_work:
                        logger.info(
                            "All riders processed, transitioning to fetch_results phase"
                        )
                        checkpoint.phase = "fetch_results"
                        checkpoint_mgr.save(checkpoint)

                elif checkpoint.phase == "fetch_results":
                    # Phase 2: Fetch results for discovered events
                    fetcher = BatchResultsFetcher(
                        client=client,
                        bucket=data_bucket,
                    )

                    more_work, events_fetched, total_results = fetcher.fetch_next_batch(
                        checkpoint
                    )

                    logger.info(
                        f"Event batch: {events_fetched} fetched, "
                        f"{total_results} results"
                    )

                    # Save checkpoint after each batch
                    checkpoint_mgr.save(checkpoint)

                    if not more_work:
                        logger.info(
                            "All events fetched, transitioning to complete phase"
                        )
                        checkpoint.phase = "complete"
                        checkpoint_mgr.save(checkpoint)

                elif checkpoint.phase == "complete":
                    # Phase 3: Process all results and generate website
                    result = process_and_generate_website(
                        bucket=data_bucket,
                        checkpoint=checkpoint,
                        tour_id=tour_config.tour_id,
                    )

                    # Mark checkpoint as complete
                    checkpoint.mark_complete()
                    checkpoint_mgr.save(checkpoint)

                    logger.info(
                        f"Discovery complete! "
                        f"Processed {len(checkpoint.riders_processed)} riders, "
                        f"discovered {len(checkpoint.events_discovered)} events, "
                        f"across {checkpoint.run_count} Lambda invocations"
                    )

                    return {
                        "statusCode": 200,
                        "status": "complete",
                        "run_count": checkpoint.run_count,
                        "riders_processed": len(checkpoint.riders_processed),
                        "events_discovered": len(checkpoint.events_discovered),
                        "events_fetched": len(checkpoint.events_fetched),
                        **result,
                    }

        # Ran out of time, will continue on next invocation
        logger.info(
            f"Timeout approaching, saving checkpoint. "
            f"Phase: {checkpoint.phase}, "
            f"Riders: {len(checkpoint.riders_processed)}/{len(riders_with_ids)}, "
            f"Events discovered: {len(checkpoint.events_discovered)}, "
            f"Events fetched: {len(checkpoint.events_fetched)}"
        )

        return {
            "statusCode": 200,
            "status": "partial",
            "phase": checkpoint.phase,
            "run_count": checkpoint.run_count,
            "riders_processed": len(checkpoint.riders_processed),
            "riders_total": len(riders_with_ids),
            "events_discovered": len(checkpoint.events_discovered),
            "events_fetched": len(checkpoint.events_fetched),
        }

    except Exception as e:
        logger.exception(f"Error in batch discovery: {e}")
        # Save checkpoint to preserve progress
        checkpoint_mgr.save(checkpoint)
        return {
            "statusCode": 500,
            "status": "error",
            "error": str(e),
            "phase": checkpoint.phase,
            "run_count": checkpoint.run_count,
        }
