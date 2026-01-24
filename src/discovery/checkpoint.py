"""S3-based checkpoint management for incremental batch discovery."""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Checkpoint TTL - auto-expire after 24 hours of completion
CHECKPOINT_TTL_HOURS = 24


@dataclass
class DiscoveryCheckpoint:
    """
    Checkpoint state for incremental batch discovery.

    Phases:
        - discover_riders: Processing rider histories to find TDZ events
        - fetch_results: Fetching full results for discovered events
        - complete: All processing finished, ready to generate website

    The checkpoint preserves progress across Lambda invocations, allowing
    work to resume after timeout or failure.
    """

    phase: str = "discover_riders"
    riders_processed: list[str] = field(default_factory=list)
    events_discovered: dict[str, dict] = field(default_factory=dict)
    events_fetched: list[str] = field(default_factory=list)
    last_updated: str = ""
    run_count: int = 0
    started_at: str = ""
    completed_at: str = ""
    stage_numbers: list[str] = field(default_factory=list)
    tour_id: str = ""

    def to_dict(self) -> dict:
        """Convert checkpoint to dictionary for JSON serialization."""
        return {
            "phase": self.phase,
            "riders_processed": self.riders_processed,
            "events_discovered": self.events_discovered,
            "events_fetched": self.events_fetched,
            "last_updated": self.last_updated,
            "run_count": self.run_count,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "stage_numbers": self.stage_numbers,
            "tour_id": self.tour_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DiscoveryCheckpoint":
        """Create checkpoint from dictionary."""
        return cls(
            phase=data.get("phase", "discover_riders"),
            riders_processed=data.get("riders_processed", []),
            events_discovered=data.get("events_discovered", {}),
            events_fetched=data.get("events_fetched", []),
            last_updated=data.get("last_updated", ""),
            run_count=data.get("run_count", 0),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            stage_numbers=data.get("stage_numbers", []),
            tour_id=data.get("tour_id", ""),
        )

    def is_expired(self) -> bool:
        """Check if checkpoint has expired (completed more than TTL hours ago)."""
        if not self.completed_at:
            return False

        try:
            completed_dt = datetime.fromisoformat(self.completed_at)
            expiry_dt = completed_dt + timedelta(hours=CHECKPOINT_TTL_HOURS)
            return datetime.now(UTC) > expiry_dt
        except (ValueError, TypeError):
            return False

    def get_pending_riders(self, all_riders: list[dict]) -> list[dict]:
        """Get riders that haven't been processed yet."""
        processed_ids = set(self.riders_processed)
        return [r for r in all_riders if r.get("id") not in processed_ids]

    def get_pending_events(self) -> list[str]:
        """Get event IDs that haven't been fetched yet."""
        fetched_ids = set(self.events_fetched)
        return [
            event_id
            for event_id in self.events_discovered
            if event_id not in fetched_ids
        ]

    def mark_rider_processed(self, rider_id: str) -> None:
        """Mark a rider as processed."""
        if rider_id not in self.riders_processed:
            self.riders_processed.append(rider_id)

    def add_discovered_event(
        self,
        event_id: str,
        event_name: str,
        timestamp: int,
        stage_number: str,
    ) -> None:
        """Add a discovered event to the checkpoint."""
        if event_id not in self.events_discovered:
            self.events_discovered[event_id] = {
                "event_name": event_name,
                "timestamp": timestamp,
                "stage_numbers": [stage_number],
            }
        else:
            # Add stage number if not already present
            existing_stages = self.events_discovered[event_id].get("stage_numbers", [])
            if stage_number not in existing_stages:
                existing_stages.append(stage_number)
                self.events_discovered[event_id]["stage_numbers"] = existing_stages

    def mark_event_fetched(self, event_id: str) -> None:
        """Mark an event as fetched."""
        if event_id not in self.events_fetched:
            self.events_fetched.append(event_id)

    def update_timestamp(self) -> None:
        """Update the last_updated timestamp."""
        self.last_updated = datetime.now(UTC).isoformat()

    def increment_run_count(self) -> None:
        """Increment the run counter."""
        self.run_count += 1
        if not self.started_at:
            self.started_at = datetime.now(UTC).isoformat()

    def mark_complete(self) -> None:
        """Mark the checkpoint as complete."""
        self.phase = "complete"
        self.completed_at = datetime.now(UTC).isoformat()


class CheckpointManager:
    """
    Manage S3-based checkpoints for incremental batch discovery.

    Provides atomic checkpoint operations with automatic expiry handling.
    """

    def __init__(
        self,
        bucket: str,
        key: str = "discovery/checkpoint.json",
        s3_client=None,
    ):
        """
        Initialize the checkpoint manager.

        Args:
            bucket: S3 bucket name
            key: S3 key for checkpoint file
            s3_client: Optional boto3 S3 client (for testing)
        """
        self.bucket = bucket
        self.key = key
        self._s3_client = s3_client

    @property
    def s3_client(self):
        """Lazy-load S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3")
        return self._s3_client

    def load(self) -> DiscoveryCheckpoint:
        """
        Load checkpoint from S3.

        Returns:
            DiscoveryCheckpoint instance (new checkpoint if none exists or expired)
        """
        try:
            response = self.s3_client.get_object(Bucket=self.bucket, Key=self.key)
            data = json.loads(response["Body"].read().decode("utf-8"))
            checkpoint = DiscoveryCheckpoint.from_dict(data)

            # Check if checkpoint is expired
            if checkpoint.is_expired():
                logger.info(
                    f"Checkpoint expired (completed at {checkpoint.completed_at}), "
                    "starting fresh"
                )
                return DiscoveryCheckpoint()

            logger.info(
                f"Loaded checkpoint: phase={checkpoint.phase}, "
                f"riders_processed={len(checkpoint.riders_processed)}, "
                f"events_discovered={len(checkpoint.events_discovered)}, "
                f"events_fetched={len(checkpoint.events_fetched)}, "
                f"run_count={checkpoint.run_count}"
            )
            return checkpoint

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.info(
                    f"No checkpoint found at s3://{self.bucket}/{self.key}, "
                    "starting fresh"
                )
                return DiscoveryCheckpoint()
            raise

    def save(self, checkpoint: DiscoveryCheckpoint) -> None:
        """
        Save checkpoint to S3.

        Args:
            checkpoint: DiscoveryCheckpoint to save
        """
        checkpoint.update_timestamp()

        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=self.key,
            Body=json.dumps(checkpoint.to_dict(), indent=2, default=str),
            ContentType="application/json",
        )

        logger.info(
            f"Saved checkpoint: phase={checkpoint.phase}, "
            f"riders_processed={len(checkpoint.riders_processed)}, "
            f"events_discovered={len(checkpoint.events_discovered)}, "
            f"events_fetched={len(checkpoint.events_fetched)}"
        )

    def clear(self) -> None:
        """
        Delete checkpoint from S3.

        Called after successful completion to allow fresh start next time.
        """
        try:
            self.s3_client.delete_object(Bucket=self.bucket, Key=self.key)
            logger.info(f"Cleared checkpoint at s3://{self.bucket}/{self.key}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "NoSuchKey":
                raise
            logger.debug("Checkpoint already cleared")

    def exists(self) -> bool:
        """Check if a checkpoint exists."""
        try:
            self.s3_client.head_object(Bucket=self.bucket, Key=self.key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise
