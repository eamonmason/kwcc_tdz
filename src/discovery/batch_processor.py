"""Batch processing of rider histories for TDZ event discovery."""

import logging
import time
from datetime import UTC, datetime

from src.discovery.checkpoint import DiscoveryCheckpoint
from src.fetcher.client import ZwiftPowerClient

logger = logging.getLogger(__name__)

# Batch size for processing riders
DEFAULT_BATCH_SIZE = 5

# Rate limiting delay between batches (seconds)
DEFAULT_BATCH_DELAY = 1.5


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


class BatchDiscoveryProcessor:
    """
    Process riders in batches to discover TDZ events.

    This class handles the rider discovery phase with checkpoint support,
    allowing work to be resumed across multiple Lambda invocations.
    """

    def __init__(
        self,
        client: ZwiftPowerClient,
        stages: list[dict],
        batch_size: int = DEFAULT_BATCH_SIZE,
        batch_delay: float = DEFAULT_BATCH_DELAY,
    ):
        """
        Initialize the batch processor.

        Args:
            client: Authenticated ZwiftPower client
            stages: List of stage configurations with date ranges
            batch_size: Number of riders to process per batch
            batch_delay: Delay between batches (seconds)
        """
        self.client = client
        self.stages = stages
        self.batch_size = batch_size
        self.batch_delay = batch_delay

    def process_rider(
        self,
        rider: dict,
        checkpoint: DiscoveryCheckpoint,
    ) -> int:
        """
        Process a single rider's history to discover TDZ events.

        Args:
            rider: Rider dict with 'id' and 'name' keys
            checkpoint: Checkpoint to update with discovered events

        Returns:
            Number of events discovered for this rider
        """
        rider_id = rider.get("id", "")
        rider_name = rider.get("name", "Unknown")

        if not rider_id:
            logger.warning("No rider ID provided")
            return 0

        # Skip if already processed
        if rider_id in checkpoint.riders_processed:
            logger.debug(f"Rider {rider_name} already processed, skipping")
            return 0

        try:
            # Fetch rider's race history
            history = get_rider_race_history(self.client, rider_id)
            logger.debug(f"Fetched {len(history)} race results for rider {rider_name}")

            # Filter to TDZ events within stage date ranges
            events_found = 0
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
                for stage in self.stages:
                    if is_in_stage_range(
                        event_timestamp, stage["start_date"], stage["end_date"]
                    ):
                        checkpoint.add_discovered_event(
                            event_id=event_id,
                            event_name=event_name,
                            timestamp=event_timestamp,
                            stage_number=stage["number"],
                        )
                        events_found += 1
                        # Don't break - event might span multiple concurrent stages

            # Mark rider as processed
            checkpoint.mark_rider_processed(rider_id)

            logger.info(
                f"Discovered {events_found} TDZ events for rider {rider_name} "
                f"({rider_id})"
            )
            return events_found

        except Exception as e:
            logger.error(f"Error processing rider {rider_name} ({rider_id}): {e}")
            # Still mark as processed to avoid infinite retries
            checkpoint.mark_rider_processed(rider_id)
            return 0

    def process_batch(
        self,
        riders: list[dict],
        checkpoint: DiscoveryCheckpoint,
    ) -> tuple[int, int]:
        """
        Process a batch of riders.

        Args:
            riders: List of rider dicts to process
            checkpoint: Checkpoint to update

        Returns:
            Tuple of (riders_processed, events_discovered)
        """
        riders_processed = 0
        events_discovered = 0

        for rider in riders:
            events = self.process_rider(rider, checkpoint)
            riders_processed += 1
            events_discovered += events

        return riders_processed, events_discovered

    def process_next_batch(
        self,
        all_riders: list[dict],
        checkpoint: DiscoveryCheckpoint,
    ) -> tuple[bool, int, int]:
        """
        Process the next batch of pending riders.

        Args:
            all_riders: Complete list of riders
            checkpoint: Checkpoint with current progress

        Returns:
            Tuple of (more_work_remaining, riders_processed, events_discovered)
        """
        # Get riders not yet processed
        pending = checkpoint.get_pending_riders(all_riders)

        if not pending:
            logger.info("All riders processed")
            return False, 0, 0

        # Take next batch
        batch = pending[: self.batch_size]
        logger.info(
            f"Processing batch of {len(batch)} riders "
            f"({len(pending) - len(batch)} remaining after this batch)"
        )

        # Process the batch
        riders_processed, events_discovered = self.process_batch(batch, checkpoint)

        # Rate limiting delay
        if len(pending) > len(batch):
            time.sleep(self.batch_delay)

        more_remaining = len(pending) > len(batch)
        return more_remaining, riders_processed, events_discovered


def build_stages_info(stages) -> list[dict]:
    """
    Build stage info dictionaries from tour stage objects.

    Args:
        stages: List of Stage objects from tour config

    Returns:
        List of stage info dictionaries with required fields
    """
    return [
        {
            "number": stage.number,
            "name": stage.name,
            "start_date": stage.start_datetime.isoformat(),
            "end_date": stage.end_datetime.isoformat(),
            "event_search_patterns": stage.event_search_patterns,
            "option_letter": (stage.courses[0].option_letter if stage.courses else "C"),
        }
        for stage in stages
    ]
