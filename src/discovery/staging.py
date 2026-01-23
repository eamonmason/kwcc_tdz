"""DynamoDB staging table operations for event discovery."""

import logging
import time
from datetime import UTC, datetime

import boto3

logger = logging.getLogger(__name__)

# TTL for staging table entries (7 days in seconds)
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60


class DiscoveryStaging:
    """
    Manage event discovery staging in DynamoDB.

    The staging table temporarily stores discovered events from the
    distributed rider discovery process. Events are deduplicated when
    read and merged into the persistent S3 event store.

    Table schema:
        - event_id (PK): ZwiftPower event ID
        - discovered_by (SK): Source of discovery (e.g., "rider:12345")
        - event_name: Name of the event
        - timestamp: Event timestamp
        - stage_number: Stage number(s) the event belongs to
        - ttl: Auto-cleanup timestamp
    """

    def __init__(
        self,
        table_name: str,
        dynamodb_resource=None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        """
        Initialize the staging manager.

        Args:
            table_name: DynamoDB table name
            dynamodb_resource: Optional boto3 DynamoDB resource (for testing)
            ttl_seconds: TTL for staging entries (default 7 days)
        """
        self.table_name = table_name
        self.ttl_seconds = ttl_seconds
        self._dynamodb = dynamodb_resource

    @property
    def dynamodb(self):
        """Lazy-load DynamoDB resource."""
        if self._dynamodb is None:
            self._dynamodb = boto3.resource("dynamodb")
        return self._dynamodb

    @property
    def table(self):
        """Get the DynamoDB table."""
        return self.dynamodb.Table(self.table_name)

    def write_events(self, events: list[dict]) -> int:
        """
        Write discovered events to the staging table.

        Args:
            events: List of event dictionaries with required fields:
                - event_id: str
                - discovered_by: str
                Optional fields:
                - event_name: str
                - timestamp: int
                - stage_number: str

        Returns:
            Number of events written
        """
        if not events:
            return 0

        ttl = int(time.time()) + self.ttl_seconds

        with self.table.batch_writer() as batch:
            for event in events:
                event_id = str(event.get("event_id", ""))
                discovered_by = event.get("discovered_by", "")

                if not event_id or not discovered_by:
                    logger.warning(f"Skipping event without required fields: {event}")
                    continue

                item = {
                    "event_id": event_id,
                    "discovered_by": discovered_by,
                    "event_name": event.get("event_name", ""),
                    "timestamp": int(event.get("timestamp", 0)),
                    "stage_number": event.get("stage_number", ""),
                    "discovery_time": datetime.now(UTC).isoformat(),
                    "ttl": ttl,
                }
                batch.put_item(Item=item)

        logger.info(f"Wrote {len(events)} events to staging table {self.table_name}")
        return len(events)

    def scan_all_events(self) -> list[dict]:
        """
        Scan all events from the staging table with pagination.

        Returns:
            List of all events in the staging table
        """
        items = []
        response = self.table.scan()
        items.extend(response.get("Items", []))

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = self.table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))

        logger.info(f"Scanned {len(items)} events from staging table {self.table_name}")
        return items

    def get_unique_events(self) -> dict[str, dict]:
        """
        Get deduplicated events from the staging table.

        Events are deduplicated by event_id, aggregating stage numbers
        and discovery sources.

        Returns:
            Dictionary mapping event_id to event data with aggregated fields
        """
        all_items = self.scan_all_events()

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

            # Aggregate stage numbers
            stage_number = item.get("stage_number", "")
            if stage_number:
                unique_events[event_id]["stage_numbers"].add(stage_number)

            # Aggregate discovery sources
            discovered_by = item.get("discovered_by", "")
            if (
                discovered_by
                and discovered_by not in unique_events[event_id]["discovered_by"]
            ):
                unique_events[event_id]["discovered_by"].append(discovered_by)

        # Convert sets to lists for serialization
        for _event_id, event_data in unique_events.items():
            event_data["stage_numbers"] = list(event_data["stage_numbers"])

        logger.info(
            f"Aggregated {len(all_items)} items to {len(unique_events)} unique events"
        )
        return unique_events

    def clear_staging(self) -> int:
        """
        Clear all items from the staging table.

        This is useful for cleanup after successful processing.
        Uses batch delete for efficiency.

        Returns:
            Number of items deleted
        """
        items = self.scan_all_events()
        if not items:
            return 0

        count = 0
        with self.table.batch_writer() as batch:
            for item in items:
                batch.delete_item(
                    Key={
                        "event_id": item["event_id"],
                        "discovered_by": item["discovered_by"],
                    }
                )
                count += 1

        logger.info(f"Cleared {count} items from staging table {self.table_name}")
        return count
