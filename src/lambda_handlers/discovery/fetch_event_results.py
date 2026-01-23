"""Lambda handler for fetching results for a single event."""

import json
import logging
import os

import boto3

from src.fetcher.client import ZwiftPowerClient
from src.fetcher.events import get_event_details

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
s3_client = boto3.client("s3")
secretsmanager_client = boto3.client("secretsmanager")


def get_zwiftpower_credentials() -> tuple[str, str]:
    """Get ZwiftPower credentials from Secrets Manager."""
    secret_arn = os.environ.get("ZWIFTPOWER_SECRET_ARN", "")
    if not secret_arn:
        raise ValueError("ZWIFTPOWER_SECRET_ARN not configured")

    response = secretsmanager_client.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])

    return secret.get("username", ""), secret.get("password", "")


def handler(event, context):
    """
    Fetch full results for a single event and persist to S3.

    This handler is called once per unique event in the Map state.

    Input (from Step Function Map state - single event):
        event_id: str - ZwiftPower event ID
        event_name: str - Event name (may be empty)
        timestamp: int - Event timestamp
        stage_numbers: list[str] - Stage numbers this event belongs to

    Output:
        event_id: str - The event ID
        event_name: str - The event name (fetched if needed)
        results_count: int - Number of results fetched
        s3_key: str - S3 key where results are stored
    """
    logger.info(f"Fetching event results: {json.dumps(event)}")

    event_id = event.get("event_id", "")
    event_name = event.get("event_name", "")
    timestamp = event.get("timestamp", 0)

    if not event_id:
        logger.warning("No event ID provided")
        return {"event_id": "", "results_count": 0}

    data_bucket = os.environ.get("DATA_BUCKET", "")
    if not data_bucket:
        raise ValueError("DATA_BUCKET not configured")

    try:
        # Get credentials
        username, password = get_zwiftpower_credentials()

        with ZwiftPowerClient(username, password) as client:
            try:
                client.authenticate()
            except Exception as e:
                logger.warning(f"Authentication failed (continuing anyway): {e}")

            # Fetch event name if not provided
            if not event_name:
                try:
                    details = get_event_details(client, event_id)
                    event_name = details.get("title", f"Event {event_id}")
                    logger.info(f"Fetched event name: {event_name}")
                except Exception as e:
                    logger.warning(f"Failed to fetch event details: {e}")
                    event_name = f"Event {event_id}"

            # Fetch event results
            results = client.get_event_results(event_id)

        logger.info(f"Fetched {len(results)} results for event {event_id}")

        # Store raw results in S3
        s3_key = f"raw/events/{event_id}/results.json"
        result_data = {
            "event_id": event_id,
            "event_name": event_name,
            "timestamp": timestamp,
            "fetched_at": str(context.invoked_function_arn if context else "local"),
            "results": results,
        }

        s3_client.put_object(
            Bucket=data_bucket,
            Key=s3_key,
            Body=json.dumps(result_data, indent=2, default=str),
            ContentType="application/json",
        )

        logger.info(f"Stored results to s3://{data_bucket}/{s3_key}")

        return {
            "event_id": event_id,
            "event_name": event_name,
            "timestamp": timestamp,
            "results_count": len(results),
            "s3_key": s3_key,
        }

    except Exception as e:
        logger.exception(f"Error fetching event {event_id}: {e}")
        # Return partial success - don't fail the entire Map state
        return {
            "event_id": event_id,
            "event_name": event_name,
            "timestamp": timestamp,
            "results_count": 0,
            "error": str(e),
        }
