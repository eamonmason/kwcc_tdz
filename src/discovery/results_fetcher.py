"""Batch fetching of event results for discovered TDZ events."""

import json
import logging
import time
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from src.discovery.checkpoint import DiscoveryCheckpoint
from src.fetcher.client import ZwiftPowerClient
from src.fetcher.events import get_event_details

logger = logging.getLogger(__name__)

# Batch size for fetching events
DEFAULT_BATCH_SIZE = 3

# Rate limiting delay between batches (seconds)
DEFAULT_BATCH_DELAY = 2.0


class BatchResultsFetcher:
    """
    Fetch event results in batches with checkpoint support.

    This class handles the results fetching phase, caching results to S3
    and tracking progress via checkpoint.
    """

    def __init__(
        self,
        client: ZwiftPowerClient,
        bucket: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        batch_delay: float = DEFAULT_BATCH_DELAY,
        s3_client=None,
    ):
        """
        Initialize the results fetcher.

        Args:
            client: Authenticated ZwiftPower client
            bucket: S3 bucket for storing results
            batch_size: Number of events to fetch per batch
            batch_delay: Delay between batches (seconds)
            s3_client: Optional boto3 S3 client (for testing)
        """
        self.client = client
        self.bucket = bucket
        self.batch_size = batch_size
        self.batch_delay = batch_delay
        self._s3_client = s3_client

    @property
    def s3_client(self):
        """Lazy-load S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3")
        return self._s3_client

    def is_cached(self, event_id: str) -> bool:
        """Check if event results are already cached in S3."""
        key = f"raw/events/{event_id}/results.json"
        try:
            self.s3_client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def fetch_event(
        self,
        event_id: str,
        event_info: dict,
        checkpoint: DiscoveryCheckpoint,
    ) -> tuple[int, str]:
        """
        Fetch results for a single event and cache to S3.

        Args:
            event_id: ZwiftPower event ID
            event_info: Event info dict from checkpoint
            checkpoint: Checkpoint to update

        Returns:
            Tuple of (results_count, s3_key)
        """
        # Skip if already fetched
        if event_id in checkpoint.events_fetched:
            logger.debug(f"Event {event_id} already fetched, skipping")
            return 0, ""

        # Check S3 cache
        s3_key = f"raw/events/{event_id}/results.json"
        if self.is_cached(event_id):
            logger.debug(f"Event {event_id} already cached in S3, marking as fetched")
            checkpoint.mark_event_fetched(event_id)
            return 0, s3_key

        event_name = event_info.get("event_name", "")
        timestamp = event_info.get("timestamp", 0)

        try:
            # Fetch event name if not provided
            if not event_name:
                try:
                    details = get_event_details(self.client, event_id)
                    event_name = details.get("title", f"Event {event_id}")
                    logger.info(f"Fetched event name: {event_name}")
                except Exception as e:
                    logger.warning(f"Failed to fetch event details: {e}")
                    event_name = f"Event {event_id}"

            # Fetch event results
            results = self.client.get_event_results(event_id)
            logger.info(f"Fetched {len(results)} results for event {event_id}")

            # Store raw results in S3
            result_data = {
                "event_id": event_id,
                "event_name": event_name,
                "timestamp": timestamp,
                "fetched_at": datetime.now(UTC).isoformat(),
                "results": results,
            }

            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=json.dumps(result_data, indent=2, default=str),
                ContentType="application/json",
            )

            logger.info(f"Stored results to s3://{self.bucket}/{s3_key}")

            # Mark as fetched
            checkpoint.mark_event_fetched(event_id)

            return len(results), s3_key

        except Exception as e:
            logger.error(f"Error fetching event {event_id}: {e}")
            # Mark as fetched to avoid infinite retries
            checkpoint.mark_event_fetched(event_id)
            return 0, ""

    def fetch_batch(
        self,
        event_ids: list[str],
        checkpoint: DiscoveryCheckpoint,
    ) -> tuple[int, int]:
        """
        Fetch results for a batch of events.

        Args:
            event_ids: List of event IDs to fetch
            checkpoint: Checkpoint with event info

        Returns:
            Tuple of (events_fetched, total_results)
        """
        events_fetched = 0
        total_results = 0

        for event_id in event_ids:
            event_info = checkpoint.events_discovered.get(event_id, {})
            results_count, _ = self.fetch_event(event_id, event_info, checkpoint)
            events_fetched += 1
            total_results += results_count

        return events_fetched, total_results

    def fetch_next_batch(
        self,
        checkpoint: DiscoveryCheckpoint,
    ) -> tuple[bool, int, int]:
        """
        Fetch the next batch of pending events.

        Args:
            checkpoint: Checkpoint with current progress

        Returns:
            Tuple of (more_work_remaining, events_fetched, total_results)
        """
        # Get events not yet fetched
        pending = checkpoint.get_pending_events()

        if not pending:
            logger.info("All events fetched")
            return False, 0, 0

        # Take next batch
        batch = pending[: self.batch_size]
        logger.info(
            f"Fetching batch of {len(batch)} events "
            f"({len(pending) - len(batch)} remaining after this batch)"
        )

        # Fetch the batch
        events_fetched, total_results = self.fetch_batch(batch, checkpoint)

        # Rate limiting delay
        if len(pending) > len(batch):
            time.sleep(self.batch_delay)

        more_remaining = len(pending) > len(batch)
        return more_remaining, events_fetched, total_results


def get_fetched_events_from_checkpoint(
    checkpoint: DiscoveryCheckpoint,
) -> list[dict]:
    """
    Build list of fetched event info from checkpoint for processing.

    Args:
        checkpoint: Checkpoint with discovered events

    Returns:
        List of event dicts suitable for merge_and_process logic
    """
    return [
        {
            "event_id": event_id,
            "event_name": event_info.get("event_name", ""),
            "timestamp": event_info.get("timestamp", 0),
            "stage_numbers": event_info.get("stage_numbers", []),
            "results_count": 1,  # Assume results exist if in fetched list
        }
        for event_id, event_info in checkpoint.events_discovered.items()
        if event_id in checkpoint.events_fetched
    ]
