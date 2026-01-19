"""Persist and accumulate raw ZwiftPower events in S3."""

import json
import logging
from datetime import UTC, date, datetime

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class RawEventStore:
    """
    Persist and accumulate raw ZwiftPower events in S3.

    Implements ELT pattern: events are accumulated over time and never deleted,
    allowing historical events to be preserved even after they age out of
    ZwiftPower's API responses.
    """

    def __init__(self, bucket: str, s3_client=None):
        """
        Initialize the raw event store.

        Args:
            bucket: S3 bucket name for storing raw events
            s3_client: Optional boto3 S3 client (for testing)
        """
        self.bucket = bucket
        self.key = "raw/events/tdz_events.json"
        self._s3_client = s3_client

    @property
    def s3_client(self):
        """Lazy-load S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3")
        return self._s3_client

    def load_events(self) -> dict[str, dict]:
        """
        Load all persisted events from S3, keyed by event_id.

        Returns:
            Dictionary mapping event_id to event data.
            Returns empty dict if no events file exists.
        """
        try:
            response = self.s3_client.get_object(Bucket=self.bucket, Key=self.key)
            data = json.loads(response["Body"].read().decode("utf-8"))
            logger.info(
                f"Loaded {len(data)} persisted events from s3://{self.bucket}/{self.key}"
            )
            return data
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.info(
                    f"No persisted events file found at s3://{self.bucket}/{self.key}"
                )
                return {}
            raise

    def merge_events(
        self,
        existing: dict[str, dict],
        new_events: list[dict],
    ) -> dict[str, dict]:
        """
        Merge new discoveries with existing events, preserving all events.

        New events get a discovery_timestamp added. Existing events are never
        overwritten - their original discovery_timestamp is preserved.

        Args:
            existing: Dictionary of existing events keyed by event_id
            new_events: List of newly discovered event dictionaries

        Returns:
            Merged dictionary with all events
        """
        merged = dict(existing)  # Copy existing events
        discovery_timestamp = datetime.now(UTC).isoformat()
        new_count = 0

        for event in new_events:
            # Extract event ID from various possible field names
            event_id = str(
                event.get("id", "") or event.get("zid", "") or event.get("DT_RowId", "")
            )

            if not event_id:
                continue

            # Only add if not already present (preserve original discovery)
            if event_id not in merged:
                merged[event_id] = {
                    "zid": event_id,
                    "name": event.get("name", "")
                    or event.get("t", "")
                    or event.get("title", ""),
                    "timestamp": event.get("timestamp", 0) or event.get("tm", 0),
                    "route_id": event.get("route_id", "") or event.get("r", ""),
                    "discovery_timestamp": discovery_timestamp,
                    "raw_data": event,
                }
                new_count += 1

        if new_count > 0:
            logger.info(
                f"Added {new_count} new events to persisted store (total: {len(merged)})"
            )
        else:
            logger.info(f"No new events to add (existing: {len(merged)})")

        return merged

    def save_events(self, events: dict[str, dict]) -> None:
        """
        Save accumulated events to S3.

        Args:
            events: Dictionary of events keyed by event_id
        """
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=self.key,
            Body=json.dumps(events, indent=2, default=str),
            ContentType="application/json",
        )
        logger.info(f"Saved {len(events)} events to s3://{self.bucket}/{self.key}")

    def get_stage_events(
        self,
        events: dict[str, dict],
        stage_number: int,
        start_date: date,
        end_date: date,
    ) -> list[tuple[str, datetime | None]]:
        """
        Filter accumulated events to a specific stage's date range.

        Args:
            events: Dictionary of all persisted events
            stage_number: Stage number to filter for (1-6)
            start_date: Stage start date
            end_date: Stage end date

        Returns:
            List of tuples (event_id, event_datetime) matching the stage
        """
        stage_pattern = f"stage {stage_number}"
        start_ts = datetime.combine(start_date, datetime.min.time()).timestamp()
        end_ts = datetime.combine(end_date, datetime.max.time()).timestamp()

        matching_events: list[tuple[str, datetime | None, int]] = []

        for event_id, event_data in events.items():
            event_name = (event_data.get("name", "") or "").lower()
            event_ts = event_data.get("timestamp", 0)

            # Must match stage number in name
            if stage_pattern not in event_name:
                continue

            # Exclude run events
            if "run" in event_name:
                continue

            # Score for sorting (prefer events in date range)
            score = 0
            if "tour de zwift" in event_name:
                score += 2
            if "advanced" in event_name:
                score -= 2

            # Check timestamp if available
            if event_ts:
                if start_ts <= event_ts <= end_ts:
                    score += 3
                else:
                    # Still include events outside date range with lower priority
                    # This helps recover events that might have slightly wrong timestamps
                    score -= 1

            event_datetime = (
                datetime.fromtimestamp(event_ts, tz=UTC) if event_ts else None
            )
            matching_events.append((event_id, event_datetime, score))

        # Sort by score descending
        matching_events.sort(key=lambda x: x[2], reverse=True)

        # Return event IDs with timestamps (without scores)
        result = [
            (event_id, event_dt) for event_id, event_dt, _score in matching_events
        ]

        logger.info(
            f"Found {len(result)} events for Stage {stage_number} "
            f"from {len(events)} persisted events"
        )
        return result

    def get_event_names(self, events: dict[str, dict]) -> dict[str, str]:
        """
        Extract event names from persisted events.

        Args:
            events: Dictionary of all persisted events

        Returns:
            Dictionary mapping event_id to event name
        """
        return {
            event_id: event_data.get("name", "") or ""
            for event_id, event_data in events.items()
        }
