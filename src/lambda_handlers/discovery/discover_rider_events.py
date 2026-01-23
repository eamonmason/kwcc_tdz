"""Lambda handler for discovering TDZ events from a single rider's history."""

import json
import logging
import os
import time
from datetime import UTC, datetime

import boto3

from src.fetcher.client import ZwiftPowerClient

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
dynamodb = boto3.resource("dynamodb")
secretsmanager_client = boto3.client("secretsmanager")

# TTL for staging table entries (7 days in seconds)
STAGING_TTL_SECONDS = 7 * 24 * 60 * 60


def get_zwiftpower_credentials() -> tuple[str, str]:
    """Get ZwiftPower credentials from Secrets Manager."""
    secret_arn = os.environ.get("ZWIFTPOWER_SECRET_ARN", "")
    if not secret_arn:
        raise ValueError("ZWIFTPOWER_SECRET_ARN not configured")

    response = secretsmanager_client.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])

    return secret.get("username", ""), secret.get("password", "")


def get_rider_race_history(
    client: ZwiftPowerClient,
    rider_id: str,
) -> list[dict]:
    """
    Fetch a rider's race history from ZwiftPower.

    Args:
        client: ZwiftPower client
        rider_id: ZwiftPower rider ID

    Returns:
        List of race result dictionaries
    """
    logger.debug(f"Fetching race history for rider {rider_id}")

    try:
        # Use the cached profile endpoint which includes race history
        cache_url = f"/cache3/profile/{rider_id}_all.json"
        response = client.get(cache_url)
        data = response.json()

        # Extract race history from profile data
        if data and "data" in data:
            return data["data"]

        return []

    except Exception as e:
        logger.warning(f"Failed to fetch history for rider {rider_id}: {e}")
        return []


def is_in_stage_range(
    event_timestamp: int,
    stage_start: str,
    stage_end: str,
) -> bool:
    """Check if an event timestamp falls within stage date range."""
    if not event_timestamp:
        return False

    start_dt = datetime.fromisoformat(stage_start.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(stage_end.replace("Z", "+00:00"))
    event_dt = datetime.fromtimestamp(event_timestamp, tz=UTC)

    return start_dt <= event_dt <= end_dt


def write_to_staging(table_name: str, events: list[dict]) -> int:
    """
    Write discovered events to DynamoDB staging table.

    Args:
        table_name: DynamoDB table name
        events: List of event dictionaries

    Returns:
        Number of events written
    """
    if not events:
        return 0

    table = dynamodb.Table(table_name)
    ttl = int(time.time()) + STAGING_TTL_SECONDS

    with table.batch_writer() as batch:
        for event in events:
            item = {
                "event_id": str(event["event_id"]),
                "discovered_by": event["discovered_by"],
                "event_name": event.get("event_name", ""),
                "timestamp": event.get("timestamp", 0),
                "stage_number": event.get("stage_number", ""),
                "ttl": ttl,
            }
            batch.put_item(Item=item)

    return len(events)


def handler(event, context):  # noqa: ARG001
    """
    Discover TDZ events from a single rider's race history.

    This handler is called once per rider in the Map state, processing
    the rider's ZwiftPower history to find TDZ events.

    Input (from Step Function Map state):
        rider: {id: str, name: str} - Rider info
        stages: list[dict] - Stage configurations with date ranges

    Output:
        rider_id: str - The rider's ZwiftPower ID
        events_found: int - Number of TDZ events discovered
    """
    logger.info(f"Processing rider discovery: {json.dumps(event)}")

    rider = event.get("rider", {})
    stages = event.get("stages", [])
    rider_id = rider.get("id", "")
    rider_name = rider.get("name", "Unknown")

    if not rider_id:
        logger.warning("No rider ID provided")
        return {"rider_id": "", "events_found": 0}

    staging_table = os.environ.get("STAGING_TABLE", "")
    if not staging_table:
        raise ValueError("STAGING_TABLE not configured")

    try:
        # Get credentials and fetch rider history
        username, password = get_zwiftpower_credentials()

        with ZwiftPowerClient(username, password) as client:
            try:
                client.authenticate()
            except Exception as e:
                logger.warning(f"Authentication failed (continuing anyway): {e}")

            history = get_rider_race_history(client, rider_id)

        logger.info(f"Fetched {len(history)} race results for rider {rider_name}")

        # Filter to TDZ events within stage date ranges
        tdz_events = []
        for result in history:
            # Get event name from result data
            event_name = (
                result.get("event_title", "")
                or result.get("f_t", "")
                or result.get("name", "")
            )

            # Check if this is a Tour de Zwift event
            if "tour de zwift" not in event_name.lower():
                continue

            # Get event timestamp
            event_timestamp = result.get("event_date", 0) or result.get("tm", 0)

            # Get event ID
            event_id = str(
                result.get("zid", "")
                or result.get("event_id", "")
                or result.get("DT_RowId", "")
            )

            if not event_id:
                continue

            # Check which stage(s) this event falls into
            for stage in stages:
                if is_in_stage_range(
                    event_timestamp, stage["start_date"], stage["end_date"]
                ):
                    tdz_events.append(
                        {
                            "event_id": event_id,
                            "event_name": event_name,
                            "timestamp": event_timestamp,
                            "stage_number": stage["number"],
                            "discovered_by": f"rider:{rider_id}",
                        }
                    )
                    # Don't break - event might span multiple concurrent stages

        # Write to DynamoDB staging table
        written = write_to_staging(staging_table, tdz_events)

        logger.info(
            f"Discovered {len(tdz_events)} TDZ events for rider {rider_name}, "
            f"wrote {written} to staging"
        )

        return {
            "rider_id": rider_id,
            "rider_name": rider_name,
            "events_found": len(tdz_events),
        }

    except Exception as e:
        logger.exception(f"Error processing rider {rider_id}: {e}")
        # Return partial success - don't fail the entire Map state
        return {
            "rider_id": rider_id,
            "rider_name": rider_name,
            "events_found": 0,
            "error": str(e),
        }
