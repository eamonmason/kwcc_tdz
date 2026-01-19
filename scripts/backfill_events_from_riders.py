#!/usr/bin/env python3
"""
One-off script to backfill raw events from rider race history.

This fetches each rider's race history from ZwiftPower and extracts
Tour de Zwift events that may have aged out of the main event list API.
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import boto3
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fetcher.client import ZwiftPowerClient
from src.persistence.raw_events import RawEventStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configuration
DATA_BUCKET = os.environ.get("DATA_BUCKET", "kwcc-tdz-2026-data-ci")
ZWIFTPOWER_USERNAME = os.environ.get("ZWIFTPOWER_USERNAME", "")
ZWIFTPOWER_PASSWORD = os.environ.get("ZWIFTPOWER_PASSWORD", "")


def get_rider_race_history(client: ZwiftPowerClient, rider_id: str) -> list[dict]:
    """
    Fetch a rider's race history from ZwiftPower.

    Args:
        client: ZwiftPower client
        rider_id: ZwiftPower rider ID

    Returns:
        List of race result dictionaries
    """
    # Try the profile results API
    try:
        # ZwiftPower profile results endpoint
        response = client.get(f"/api3.php?do=profile_results&z={rider_id}")
        data = response.json()
        if data and "data" in data:
            return data["data"]
    except Exception as e:
        logger.debug(f"API endpoint failed for rider {rider_id}: {e}")

    # Try cached profile results
    try:
        response = client.get(f"/cache3/profile/{rider_id}_results.json")
        data = response.json()
        if data and "data" in data:
            return data["data"]
    except Exception as e:
        logger.debug(f"Cache endpoint failed for rider {rider_id}: {e}")

    return []


def extract_tdz_events(race_history: list[dict]) -> list[dict]:
    """
    Extract Tour de Zwift events from race history.

    Args:
        race_history: List of race results

    Returns:
        List of event dictionaries
    """
    tdz_events = []
    seen_ids = set()

    for result in race_history:
        # Get event name - rider history API uses 'event_title' field
        # Note: 'name' field is the rider name, NOT the event name
        event_name = (
            result.get("event_title", "")
            or result.get("t", "")
            or result.get("title", "")
        )

        # Check if it's a Tour de Zwift event
        event_name_lower = event_name.lower()
        if "tour de zwift" not in event_name_lower:
            continue

        # Only include 2026 events (January 2026 onwards)
        # January 1, 2026 00:00:00 UTC = 1767225600
        event_timestamp = result.get("event_date", 0)
        if event_timestamp < 1767225600:  # Before Jan 1, 2026
            continue

        # Get event ID
        event_id = str(
            result.get("zid", "")
            or result.get("event_id", "")
            or result.get("DT_RowId", "")
        )

        if not event_id or event_id in seen_ids:
            continue

        seen_ids.add(event_id)
        logger.debug(f"Found TdZ event: {event_id} - {event_name}")

        # Extract event data - rider history API uses 'event_date' for timestamp
        timestamp = result.get("event_date", 0) or result.get("tm", 0)
        if isinstance(timestamp, str):
            try:
                timestamp = int(
                    datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
                )
            except ValueError:
                timestamp = 0

        tdz_events.append(
            {
                "id": event_id,
                "name": event_name,
                "timestamp": timestamp,
                "route_id": result.get("r", "") or result.get("route", ""),
            }
        )

    return tdz_events


def main():
    """Main function to backfill events from rider history."""
    logger.info(f"Backfilling events from rider history to {DATA_BUCKET}")

    if not ZWIFTPOWER_USERNAME or not ZWIFTPOWER_PASSWORD:
        logger.error("ZWIFTPOWER_USERNAME and ZWIFTPOWER_PASSWORD must be set")
        sys.exit(1)

    # Initialize S3 client and raw event store
    s3_client = boto3.client("s3")
    raw_store = RawEventStore(DATA_BUCKET, s3_client=s3_client)

    # Load existing persisted events
    persisted_events = raw_store.load_events()
    logger.info(f"Loaded {len(persisted_events)} existing persisted events")

    # Load riders from S3
    try:
        response = s3_client.get_object(Bucket=DATA_BUCKET, Key="config/riders.json")
        riders_data = json.loads(response["Body"].read().decode("utf-8"))
        riders = riders_data.get("riders", [])
    except Exception as e:
        logger.error(f"Failed to load riders: {e}")
        sys.exit(1)

    logger.info(f"Processing {len(riders)} riders")

    # Fetch race history for each rider
    all_tdz_events = []
    with ZwiftPowerClient(ZWIFTPOWER_USERNAME, ZWIFTPOWER_PASSWORD) as client:
        try:
            client.authenticate()
            logger.info("Authenticated with ZwiftPower")
        except Exception as e:
            logger.warning(f"Authentication failed: {e}")

        for i, rider in enumerate(riders):
            rider_name = rider.get("name", "Unknown")
            rider_id = rider.get("zwiftpower_id")

            if not rider_id:
                logger.debug(f"Skipping {rider_name} - no ZwiftPower ID")
                continue

            logger.info(
                f"[{i + 1}/{len(riders)}] Fetching history for {rider_name} ({rider_id})"
            )

            try:
                race_history = get_rider_race_history(client, str(rider_id))
                logger.info(f"  Found {len(race_history)} races in history")

                tdz_events = extract_tdz_events(race_history)
                if tdz_events:
                    logger.info(f"  Extracted {len(tdz_events)} Tour de Zwift events")
                    all_tdz_events.extend(tdz_events)

            except Exception as e:
                logger.warning(f"  Failed to fetch history: {e}")
                continue

    # Count unique new events
    new_event_ids = set()
    for event in all_tdz_events:
        event_id = event.get("id")
        if event_id and event_id not in persisted_events:
            new_event_ids.add(event_id)

    logger.info(f"\nFound {len(all_tdz_events)} total TdZ events from rider history")
    logger.info(f"Found {len(new_event_ids)} new unique events not in persisted store")

    if new_event_ids:
        # Merge new events
        merged_events = raw_store.merge_events(persisted_events, all_tdz_events)
        logger.info(f"Merged to {len(merged_events)} total events")

        # Save to S3
        raw_store.save_events(merged_events)
        logger.info("Saved updated events to S3")

        # Show what was added
        logger.info("\nNewly added events:")
        for event_id in sorted(new_event_ids):
            event = merged_events.get(event_id, {})
            ts = event.get("timestamp", 0)
            dt = datetime.fromtimestamp(ts, tz=UTC) if ts else None
            date_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "unknown"
            logger.info(f"  {event_id}: {date_str} - {event.get('name', '')[:60]}")
    else:
        logger.info("No new events to add")


if __name__ == "__main__":
    main()
