"""Lambda handler for aggregating and deduplicating discovered events."""

import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Lazy-loaded AWS clients (avoid import-time initialization for testability)
_resources: dict = {}


def _get_dynamodb_resource():
    """Get or create DynamoDB resource."""
    if "dynamodb" not in _resources:
        _resources["dynamodb"] = boto3.resource("dynamodb")
    return _resources["dynamodb"]


def scan_all_items(table) -> list[dict]:
    """
    Scan all items from DynamoDB table with pagination.

    Args:
        table: DynamoDB table resource

    Returns:
        List of all items in the table
    """
    items = []
    response = table.scan()
    items.extend(response.get("Items", []))

    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    return items


def handler(event, context):  # noqa: ARG001
    """
    Read all discovered events from staging and deduplicate.

    This handler aggregates events discovered by the Map state (one per rider)
    and deduplicates them by event_id.

    Input (from Step Function):
        discovered: list[dict] - Results from DiscoverRiderEvents Map state
        bucket: str - S3 bucket name
        stages: list[dict] - Stage configurations
        tour_id: str - Tour identifier

    Output:
        unique_events: list[dict] - Deduplicated events for fetching
        total_discovered: int - Total events found across all riders
        total_unique: int - Number of unique events
    """
    logger.info(f"Aggregating discovered events: {json.dumps(event)[:500]}...")

    staging_table_name = os.environ.get("STAGING_TABLE", "")
    if not staging_table_name:
        raise ValueError("STAGING_TABLE not configured")

    # Pass through config from previous step
    bucket = event.get("bucket", "")
    stages = event.get("stages", [])
    tour_id = event.get("tour_id", "tdz-2026")

    # Log Map state results summary
    discovered = event.get("discovered", [])
    total_rider_events = sum(d.get("events_found", 0) for d in discovered if d)
    riders_with_events = sum(
        1 for d in discovered if d and d.get("events_found", 0) > 0
    )

    logger.info(
        f"Rider discovery summary: {riders_with_events} riders found events, "
        f"{total_rider_events} total events across all riders"
    )

    try:
        # Scan staging table for all discovered events
        table = _get_dynamodb_resource().Table(staging_table_name)
        all_items = scan_all_items(table)

        logger.info(f"Scanned {len(all_items)} items from staging table")

        # Deduplicate by event_id
        unique_events: dict[str, dict] = {}
        for item in all_items:
            event_id = item.get("event_id", "")
            if not event_id:
                continue

            if event_id not in unique_events:
                unique_events[event_id] = {
                    "event_id": event_id,
                    "event_name": item.get("event_name", ""),
                    "timestamp": int(item.get("timestamp", 0)),
                    "stage_numbers": set(),
                    "discovered_by": [],
                }

            # Track stage numbers and discovery sources
            stage_number = item.get("stage_number", "")
            if stage_number:
                unique_events[event_id]["stage_numbers"].add(stage_number)

            discovered_by = item.get("discovered_by", "")
            if (
                discovered_by
                and discovered_by not in unique_events[event_id]["discovered_by"]
            ):
                unique_events[event_id]["discovered_by"].append(discovered_by)

        # Convert sets to lists for JSON serialization
        events_list = [
            {
                "event_id": v["event_id"],
                "event_name": v["event_name"],
                "timestamp": v["timestamp"],
                "stage_numbers": list(v["stage_numbers"]),
                "discovered_by_count": len(v["discovered_by"]),
            }
            for v in unique_events.values()
        ]

        # Sort by timestamp (newest first)
        events_list.sort(key=lambda x: x["timestamp"], reverse=True)

        logger.info(
            f"Aggregation complete: {len(all_items)} discovered -> "
            f"{len(events_list)} unique events"
        )

        return {
            "unique_events": events_list,
            "total_discovered": len(all_items),
            "total_unique": len(events_list),
            "bucket": bucket,
            "stages": stages,
            "tour_id": tour_id,
        }

    except Exception as e:
        logger.exception(f"Error aggregating events: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
            "unique_events": [],
            "total_discovered": 0,
            "total_unique": 0,
            "bucket": bucket,
            "stages": stages,
            "tour_id": tour_id,
        }
