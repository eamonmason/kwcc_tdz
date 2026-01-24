"""Tests for batch processor module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from src.discovery.batch_processor import (
    BatchDiscoveryProcessor,
    build_stages_info,
    get_rider_race_history,
    is_in_stage_range,
)
from src.discovery.checkpoint import DiscoveryCheckpoint


class TestIsInStageRange:
    """Tests for is_in_stage_range function."""

    def test_returns_false_for_zero_timestamp(self):
        """Test that zero timestamp returns False."""
        result = is_in_stage_range(
            0,
            "2026-01-13T00:00:00+00:00",
            "2026-01-20T23:59:59+00:00",
        )
        assert result is False

    def test_returns_true_for_timestamp_in_range(self):
        """Test that timestamp within range returns True."""
        # Jan 15, 2026 12:00 UTC
        timestamp = int(datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC).timestamp())

        result = is_in_stage_range(
            timestamp,
            "2026-01-13T00:00:00+00:00",
            "2026-01-20T23:59:59+00:00",
        )
        assert result is True

    def test_returns_false_for_timestamp_before_range(self):
        """Test that timestamp before range returns False."""
        # Jan 10, 2026
        timestamp = int(datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC).timestamp())

        result = is_in_stage_range(
            timestamp,
            "2026-01-13T00:00:00+00:00",
            "2026-01-20T23:59:59+00:00",
        )
        assert result is False

    def test_returns_false_for_timestamp_after_range(self):
        """Test that timestamp after range returns False."""
        # Jan 25, 2026
        timestamp = int(datetime(2026, 1, 25, 12, 0, 0, tzinfo=UTC).timestamp())

        result = is_in_stage_range(
            timestamp,
            "2026-01-13T00:00:00+00:00",
            "2026-01-20T23:59:59+00:00",
        )
        assert result is False

    def test_returns_true_for_timestamp_at_start_boundary(self):
        """Test that timestamp at start boundary returns True."""
        timestamp = int(datetime(2026, 1, 13, 0, 0, 0, tzinfo=UTC).timestamp())

        result = is_in_stage_range(
            timestamp,
            "2026-01-13T00:00:00+00:00",
            "2026-01-20T23:59:59+00:00",
        )
        assert result is True


class TestGetRiderRaceHistory:
    """Tests for get_rider_race_history function."""

    def test_returns_data_from_profile(self):
        """Test that function returns data from profile response."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"event_title": "Tour de Zwift Stage 1", "zid": "12345"},
                {"event_title": "Tour de Zwift Stage 2", "zid": "12346"},
            ]
        }
        mock_client.get.return_value = mock_response

        result = get_rider_race_history(mock_client, "rider123")

        assert len(result) == 2
        mock_client.get.assert_called_once_with("/cache3/profile/rider123_all.json")

    def test_returns_empty_list_on_exception(self):
        """Test that function returns empty list on exception."""
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("Network error")

        result = get_rider_race_history(mock_client, "rider123")

        assert result == []

    def test_returns_empty_list_for_empty_response(self):
        """Test that function returns empty list for empty response."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_client.get.return_value = mock_response

        result = get_rider_race_history(mock_client, "rider123")

        assert result == []


class TestBatchDiscoveryProcessor:
    """Tests for BatchDiscoveryProcessor class."""

    def test_process_rider_skips_already_processed(self):
        """Test that already processed riders are skipped."""
        mock_client = MagicMock()
        processor = BatchDiscoveryProcessor(mock_client, stages=[])

        checkpoint = DiscoveryCheckpoint(riders_processed=["123"])
        rider = {"id": "123", "name": "Test Rider"}

        events = processor.process_rider(rider, checkpoint)

        assert events == 0
        mock_client.get.assert_not_called()

    def test_process_rider_marks_as_processed(self):
        """Test that rider is marked as processed after processing."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_client.get.return_value = mock_response

        processor = BatchDiscoveryProcessor(mock_client, stages=[])
        checkpoint = DiscoveryCheckpoint()
        rider = {"id": "123", "name": "Test Rider"}

        processor.process_rider(rider, checkpoint)

        assert "123" in checkpoint.riders_processed

    def test_process_rider_discovers_tdz_events(self):
        """Test that TDZ events are discovered from rider history."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        # Jan 15, 2026 12:00 UTC
        event_timestamp = int(datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC).timestamp())
        mock_response.json.return_value = {
            "data": [
                {
                    "event_title": "Tour de Zwift Stage 1",
                    "zid": "12345",
                    "event_date": event_timestamp,
                },
                {
                    "event_title": "Some Other Event",
                    "zid": "99999",
                    "event_date": event_timestamp,
                },
            ]
        }
        mock_client.get.return_value = mock_response

        stages = [
            {
                "number": "1",
                "start_date": "2026-01-13T00:00:00+00:00",
                "end_date": "2026-01-20T23:59:59+00:00",
            }
        ]

        processor = BatchDiscoveryProcessor(mock_client, stages=stages)
        checkpoint = DiscoveryCheckpoint()
        rider = {"id": "123", "name": "Test Rider"}

        events = processor.process_rider(rider, checkpoint)

        assert events == 1
        assert "12345" in checkpoint.events_discovered
        assert "99999" not in checkpoint.events_discovered

    def test_process_rider_handles_concurrent_stages(self):
        """Test that events spanning concurrent stages are added to both."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        # Event timestamp that falls within both stages
        event_timestamp = int(datetime(2026, 1, 28, 12, 0, 0, tzinfo=UTC).timestamp())
        mock_response.json.return_value = {
            "data": [
                {
                    "event_title": "Tour de Zwift Stage 3",
                    "zid": "12345",
                    "event_date": event_timestamp,
                },
            ]
        }
        mock_client.get.return_value = mock_response

        # Concurrent stages 3.1 and 3.2
        stages = [
            {
                "number": "3.1",
                "start_date": "2026-01-27T00:00:00+00:00",
                "end_date": "2026-02-03T23:59:59+00:00",
            },
            {
                "number": "3.2",
                "start_date": "2026-01-27T00:00:00+00:00",
                "end_date": "2026-02-03T23:59:59+00:00",
            },
        ]

        processor = BatchDiscoveryProcessor(mock_client, stages=stages)
        checkpoint = DiscoveryCheckpoint()
        rider = {"id": "123", "name": "Test Rider"}

        events = processor.process_rider(rider, checkpoint)

        assert events == 2  # One event counted for each stage
        assert "12345" in checkpoint.events_discovered
        stage_numbers = checkpoint.events_discovered["12345"]["stage_numbers"]
        assert "3.1" in stage_numbers
        assert "3.2" in stage_numbers

    def test_process_batch(self):
        """Test processing a batch of riders."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_client.get.return_value = mock_response

        processor = BatchDiscoveryProcessor(mock_client, stages=[])
        checkpoint = DiscoveryCheckpoint()

        riders = [
            {"id": "1", "name": "Rider 1"},
            {"id": "2", "name": "Rider 2"},
            {"id": "3", "name": "Rider 3"},
        ]

        riders_processed, events_discovered = processor.process_batch(
            riders, checkpoint
        )

        assert riders_processed == 3
        assert events_discovered == 0
        assert len(checkpoint.riders_processed) == 3

    def test_process_next_batch_returns_false_when_all_done(self):
        """Test that process_next_batch returns False when no pending riders."""
        mock_client = MagicMock()
        processor = BatchDiscoveryProcessor(mock_client, stages=[])
        checkpoint = DiscoveryCheckpoint(riders_processed=["1", "2"])

        all_riders = [
            {"id": "1", "name": "Rider 1"},
            {"id": "2", "name": "Rider 2"},
        ]

        more_work, _, _ = processor.process_next_batch(all_riders, checkpoint)

        assert more_work is False

    def test_process_next_batch_processes_batch_size(self):
        """Test that process_next_batch respects batch size."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_client.get.return_value = mock_response

        processor = BatchDiscoveryProcessor(
            mock_client,
            stages=[],
            batch_size=2,
            batch_delay=0,  # No delay for tests
        )
        checkpoint = DiscoveryCheckpoint()

        all_riders = [
            {"id": "1", "name": "Rider 1"},
            {"id": "2", "name": "Rider 2"},
            {"id": "3", "name": "Rider 3"},
            {"id": "4", "name": "Rider 4"},
        ]

        more_work, riders_processed, _ = processor.process_next_batch(
            all_riders, checkpoint
        )

        assert more_work is True
        assert riders_processed == 2
        assert len(checkpoint.riders_processed) == 2


class TestBuildStagesInfo:
    """Tests for build_stages_info function."""

    def test_builds_stage_info_dict(self):
        """Test that stages are converted to info dictionaries."""
        mock_stage = MagicMock()
        mock_stage.number = "1"
        mock_stage.name = "Stage 1"
        mock_stage.start_datetime = datetime(2026, 1, 13, 0, 0, 0, tzinfo=UTC)
        mock_stage.end_datetime = datetime(2026, 1, 20, 23, 59, 59, tzinfo=UTC)
        mock_stage.event_search_patterns = ["stage 1"]

        mock_course = MagicMock()
        mock_course.option_letter = "C"
        mock_stage.courses = [mock_course]

        result = build_stages_info([mock_stage])

        assert len(result) == 1
        assert result[0]["number"] == "1"
        assert result[0]["name"] == "Stage 1"
        assert result[0]["event_search_patterns"] == ["stage 1"]
        assert result[0]["option_letter"] == "C"

    def test_handles_stage_without_courses(self):
        """Test that stages without courses get default option letter."""
        mock_stage = MagicMock()
        mock_stage.number = "1"
        mock_stage.name = "Stage 1"
        mock_stage.start_datetime = datetime(2026, 1, 13, 0, 0, 0, tzinfo=UTC)
        mock_stage.end_datetime = datetime(2026, 1, 20, 23, 59, 59, tzinfo=UTC)
        mock_stage.event_search_patterns = []
        mock_stage.courses = []

        result = build_stages_info([mock_stage])

        assert result[0]["option_letter"] == "C"
