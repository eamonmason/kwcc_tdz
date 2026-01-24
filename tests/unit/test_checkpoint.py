"""Tests for checkpoint manager module."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from src.discovery.checkpoint import (
    CHECKPOINT_TTL_HOURS,
    CheckpointManager,
    DiscoveryCheckpoint,
)


class TestDiscoveryCheckpoint:
    """Tests for DiscoveryCheckpoint dataclass."""

    def test_default_values(self):
        """Test that checkpoint initializes with correct defaults."""
        checkpoint = DiscoveryCheckpoint()

        assert checkpoint.phase == "discover_riders"
        assert checkpoint.riders_processed == []
        assert checkpoint.events_discovered == {}
        assert checkpoint.events_fetched == []
        assert checkpoint.last_updated == ""
        assert checkpoint.run_count == 0
        assert checkpoint.started_at == ""
        assert checkpoint.completed_at == ""
        assert checkpoint.stage_numbers == []
        assert checkpoint.tour_id == ""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        checkpoint = DiscoveryCheckpoint(
            phase="fetch_results",
            riders_processed=["123", "456"],
            events_discovered={"event1": {"event_name": "Test Event"}},
            events_fetched=["event1"],
            run_count=2,
        )

        result = checkpoint.to_dict()

        assert result["phase"] == "fetch_results"
        assert result["riders_processed"] == ["123", "456"]
        assert result["events_discovered"] == {"event1": {"event_name": "Test Event"}}
        assert result["events_fetched"] == ["event1"]
        assert result["run_count"] == 2

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "phase": "complete",
            "riders_processed": ["123"],
            "events_discovered": {"e1": {"event_name": "Test"}},
            "events_fetched": ["e1"],
            "run_count": 5,
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T01:00:00+00:00",
            "stage_numbers": ["1", "2"],
            "tour_id": "tdz-2026",
        }

        checkpoint = DiscoveryCheckpoint.from_dict(data)

        assert checkpoint.phase == "complete"
        assert checkpoint.riders_processed == ["123"]
        assert checkpoint.events_discovered == {"e1": {"event_name": "Test"}}
        assert checkpoint.events_fetched == ["e1"]
        assert checkpoint.run_count == 5
        assert checkpoint.stage_numbers == ["1", "2"]
        assert checkpoint.tour_id == "tdz-2026"

    def test_from_dict_with_missing_fields(self):
        """Test creation from dictionary with missing fields uses defaults."""
        data = {"phase": "fetch_results"}

        checkpoint = DiscoveryCheckpoint.from_dict(data)

        assert checkpoint.phase == "fetch_results"
        assert checkpoint.riders_processed == []
        assert checkpoint.events_discovered == {}

    def test_is_expired_returns_false_when_not_completed(self):
        """Test that incomplete checkpoints are not expired."""
        checkpoint = DiscoveryCheckpoint(phase="discover_riders")

        assert checkpoint.is_expired() is False

    def test_is_expired_returns_false_when_within_ttl(self):
        """Test that recently completed checkpoints are not expired."""
        completed_time = datetime.now(UTC) - timedelta(hours=1)
        checkpoint = DiscoveryCheckpoint(
            phase="complete",
            completed_at=completed_time.isoformat(),
        )

        assert checkpoint.is_expired() is False

    def test_is_expired_returns_true_when_past_ttl(self):
        """Test that old completed checkpoints are expired."""
        completed_time = datetime.now(UTC) - timedelta(hours=CHECKPOINT_TTL_HOURS + 1)
        checkpoint = DiscoveryCheckpoint(
            phase="complete",
            completed_at=completed_time.isoformat(),
        )

        assert checkpoint.is_expired() is True

    def test_get_pending_riders(self):
        """Test getting riders not yet processed."""
        checkpoint = DiscoveryCheckpoint(
            riders_processed=["123", "456"],
        )

        all_riders = [
            {"id": "123", "name": "Rider 1"},
            {"id": "456", "name": "Rider 2"},
            {"id": "789", "name": "Rider 3"},
        ]

        pending = checkpoint.get_pending_riders(all_riders)

        assert len(pending) == 1
        assert pending[0]["id"] == "789"

    def test_get_pending_events(self):
        """Test getting events not yet fetched."""
        checkpoint = DiscoveryCheckpoint(
            events_discovered={
                "e1": {"event_name": "Event 1"},
                "e2": {"event_name": "Event 2"},
                "e3": {"event_name": "Event 3"},
            },
            events_fetched=["e1"],
        )

        pending = checkpoint.get_pending_events()

        assert len(pending) == 2
        assert "e2" in pending
        assert "e3" in pending
        assert "e1" not in pending

    def test_mark_rider_processed(self):
        """Test marking a rider as processed."""
        checkpoint = DiscoveryCheckpoint()

        checkpoint.mark_rider_processed("123")
        checkpoint.mark_rider_processed("456")
        checkpoint.mark_rider_processed("123")  # Duplicate

        assert checkpoint.riders_processed == ["123", "456"]

    def test_add_discovered_event(self):
        """Test adding a discovered event."""
        checkpoint = DiscoveryCheckpoint()

        checkpoint.add_discovered_event(
            event_id="e1",
            event_name="Tour de Zwift Stage 1",
            timestamp=1736700000,
            stage_number="1",
        )

        assert "e1" in checkpoint.events_discovered
        assert (
            checkpoint.events_discovered["e1"]["event_name"] == "Tour de Zwift Stage 1"
        )
        assert checkpoint.events_discovered["e1"]["timestamp"] == 1736700000
        assert checkpoint.events_discovered["e1"]["stage_numbers"] == ["1"]

    def test_add_discovered_event_aggregates_stages(self):
        """Test that adding the same event for different stages aggregates."""
        checkpoint = DiscoveryCheckpoint()

        checkpoint.add_discovered_event(
            event_id="e1",
            event_name="Tour de Zwift",
            timestamp=1736700000,
            stage_number="3.1",
        )
        checkpoint.add_discovered_event(
            event_id="e1",
            event_name="Tour de Zwift",
            timestamp=1736700000,
            stage_number="3.2",
        )

        assert checkpoint.events_discovered["e1"]["stage_numbers"] == ["3.1", "3.2"]

    def test_mark_event_fetched(self):
        """Test marking an event as fetched."""
        checkpoint = DiscoveryCheckpoint()

        checkpoint.mark_event_fetched("e1")
        checkpoint.mark_event_fetched("e2")
        checkpoint.mark_event_fetched("e1")  # Duplicate

        assert checkpoint.events_fetched == ["e1", "e2"]

    def test_update_timestamp(self):
        """Test updating the last_updated timestamp."""
        checkpoint = DiscoveryCheckpoint()

        checkpoint.update_timestamp()

        assert checkpoint.last_updated != ""
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(checkpoint.last_updated)

    def test_increment_run_count(self):
        """Test incrementing the run counter."""
        checkpoint = DiscoveryCheckpoint()

        checkpoint.increment_run_count()
        assert checkpoint.run_count == 1
        assert checkpoint.started_at != ""

        checkpoint.increment_run_count()
        assert checkpoint.run_count == 2

    def test_mark_complete(self):
        """Test marking the checkpoint as complete."""
        checkpoint = DiscoveryCheckpoint(phase="fetch_results")

        checkpoint.mark_complete()

        assert checkpoint.phase == "complete"
        assert checkpoint.completed_at != ""


class TestCheckpointManager:
    """Tests for CheckpointManager class."""

    def test_load_returns_new_checkpoint_when_not_exists(self):
        """Test that load returns new checkpoint when none exists."""
        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey"}},
            "GetObject",
        )

        manager = CheckpointManager("test-bucket", s3_client=mock_s3)

        checkpoint = manager.load()

        assert checkpoint.phase == "discover_riders"
        assert checkpoint.run_count == 0

    def test_load_returns_existing_checkpoint(self):
        """Test that load returns existing checkpoint from S3."""
        checkpoint_data = {
            "phase": "fetch_results",
            "riders_processed": ["123"],
            "events_discovered": {"e1": {"event_name": "Test"}},
            "events_fetched": [],
            "run_count": 3,
            "last_updated": "2026-01-01T00:00:00+00:00",
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "",
            "stage_numbers": ["1"],
            "tour_id": "tdz-2026",
        }

        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(
                read=MagicMock(return_value=json.dumps(checkpoint_data).encode())
            )
        }

        manager = CheckpointManager("test-bucket", s3_client=mock_s3)

        checkpoint = manager.load()

        assert checkpoint.phase == "fetch_results"
        assert checkpoint.riders_processed == ["123"]
        assert checkpoint.run_count == 3

    def test_load_returns_new_checkpoint_when_expired(self):
        """Test that load returns new checkpoint when existing is expired."""
        completed_time = datetime.now(UTC) - timedelta(hours=CHECKPOINT_TTL_HOURS + 1)
        checkpoint_data = {
            "phase": "complete",
            "riders_processed": ["123"],
            "events_discovered": {},
            "events_fetched": [],
            "run_count": 3,
            "last_updated": "",
            "started_at": "",
            "completed_at": completed_time.isoformat(),
            "stage_numbers": [],
            "tour_id": "",
        }

        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(
                read=MagicMock(return_value=json.dumps(checkpoint_data).encode())
            )
        }

        manager = CheckpointManager("test-bucket", s3_client=mock_s3)

        checkpoint = manager.load()

        # Should return fresh checkpoint since old one is expired
        assert checkpoint.phase == "discover_riders"
        assert checkpoint.run_count == 0

    def test_save_writes_to_s3(self):
        """Test that save writes checkpoint to S3."""
        mock_s3 = MagicMock()
        manager = CheckpointManager("test-bucket", s3_client=mock_s3)

        checkpoint = DiscoveryCheckpoint(
            phase="fetch_results",
            riders_processed=["123"],
        )

        manager.save(checkpoint)

        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"] == "discovery/checkpoint.json"
        assert call_kwargs["ContentType"] == "application/json"

        # Verify the saved data
        saved_data = json.loads(call_kwargs["Body"])
        assert saved_data["phase"] == "fetch_results"
        assert saved_data["riders_processed"] == ["123"]
        assert saved_data["last_updated"] != ""  # Should be updated

    def test_save_updates_timestamp(self):
        """Test that save updates the last_updated timestamp."""
        mock_s3 = MagicMock()
        manager = CheckpointManager("test-bucket", s3_client=mock_s3)

        checkpoint = DiscoveryCheckpoint(last_updated="old-timestamp")

        manager.save(checkpoint)

        call_kwargs = mock_s3.put_object.call_args.kwargs
        saved_data = json.loads(call_kwargs["Body"])
        assert saved_data["last_updated"] != "old-timestamp"

    def test_clear_deletes_from_s3(self):
        """Test that clear deletes checkpoint from S3."""
        mock_s3 = MagicMock()
        manager = CheckpointManager("test-bucket", s3_client=mock_s3)

        manager.clear()

        mock_s3.delete_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="discovery/checkpoint.json",
        )

    def test_clear_handles_missing_checkpoint(self):
        """Test that clear handles missing checkpoint gracefully."""
        mock_s3 = MagicMock()
        mock_s3.delete_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey"}},
            "DeleteObject",
        )

        manager = CheckpointManager("test-bucket", s3_client=mock_s3)

        # Should not raise
        manager.clear()

    def test_exists_returns_true_when_checkpoint_exists(self):
        """Test that exists returns True when checkpoint exists."""
        mock_s3 = MagicMock()
        manager = CheckpointManager("test-bucket", s3_client=mock_s3)

        result = manager.exists()

        assert result is True
        mock_s3.head_object.assert_called_once()

    def test_exists_returns_false_when_checkpoint_missing(self):
        """Test that exists returns False when checkpoint is missing."""
        mock_s3 = MagicMock()
        mock_s3.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}},
            "HeadObject",
        )

        manager = CheckpointManager("test-bucket", s3_client=mock_s3)

        result = manager.exists()

        assert result is False

    def test_custom_key(self):
        """Test using a custom S3 key."""
        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey"}},
            "GetObject",
        )

        manager = CheckpointManager(
            "test-bucket",
            key="custom/path/checkpoint.json",
            s3_client=mock_s3,
        )

        manager.load()

        mock_s3.get_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="custom/path/checkpoint.json",
        )
