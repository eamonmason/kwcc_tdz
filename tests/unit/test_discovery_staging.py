"""Tests for discovery staging module."""

import time
from unittest.mock import MagicMock

from src.discovery.staging import DEFAULT_TTL_SECONDS, DiscoveryStaging


class TestDiscoveryStagingWriteEvents:
    """Tests for writing events to staging table."""

    def test_write_events_returns_zero_for_empty_list(self):
        """Test that write_events returns 0 for empty input."""
        mock_dynamodb = MagicMock()
        staging = DiscoveryStaging("test-table", dynamodb_resource=mock_dynamodb)

        result = staging.write_events([])

        assert result == 0

    def test_write_events_writes_to_dynamodb(self):
        """Test that write_events writes items to DynamoDB."""
        mock_table = MagicMock()
        mock_batch_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(
            return_value=mock_batch_writer
        )
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=None)

        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        staging = DiscoveryStaging("test-table", dynamodb_resource=mock_dynamodb)

        events = [
            {
                "event_id": "12345",
                "discovered_by": "rider:67890",
                "event_name": "Tour de Zwift Stage 1",
                "timestamp": 1736700000,
                "stage_number": "1",
            }
        ]

        result = staging.write_events(events)

        assert result == 1
        mock_batch_writer.put_item.assert_called_once()

        # Check the item that was written
        call_args = mock_batch_writer.put_item.call_args
        item = call_args.kwargs["Item"]
        assert item["event_id"] == "12345"
        assert item["discovered_by"] == "rider:67890"
        assert item["event_name"] == "Tour de Zwift Stage 1"
        assert item["timestamp"] == 1736700000
        assert item["stage_number"] == "1"
        assert "ttl" in item
        assert "discovery_time" in item

    def test_write_events_skips_events_without_required_fields(self):
        """Test that events without required fields are skipped."""
        mock_table = MagicMock()
        mock_batch_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(
            return_value=mock_batch_writer
        )
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=None)

        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        staging = DiscoveryStaging("test-table", dynamodb_resource=mock_dynamodb)

        events = [
            {"event_id": "12345"},  # Missing discovered_by
            {"discovered_by": "rider:67890"},  # Missing event_id
            {"event_id": "12345", "discovered_by": "rider:67890"},  # Valid
        ]

        result = staging.write_events(events)

        # Only the valid event should be written
        assert result == 3  # Returns count of input, not successful writes
        assert mock_batch_writer.put_item.call_count == 1

    def test_write_events_sets_ttl(self):
        """Test that TTL is set correctly."""
        mock_table = MagicMock()
        mock_batch_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(
            return_value=mock_batch_writer
        )
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=None)

        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        staging = DiscoveryStaging("test-table", dynamodb_resource=mock_dynamodb)

        current_time = int(time.time())
        events = [{"event_id": "12345", "discovered_by": "rider:67890"}]

        staging.write_events(events)

        call_args = mock_batch_writer.put_item.call_args
        item = call_args.kwargs["Item"]
        expected_ttl = current_time + DEFAULT_TTL_SECONDS

        # Allow for a few seconds of variance
        assert abs(item["ttl"] - expected_ttl) < 5


class TestDiscoveryStagingScanAllEvents:
    """Tests for scanning events from staging table."""

    def test_scan_all_events_returns_items(self):
        """Test that scan_all_events returns all items."""
        mock_table = MagicMock()
        mock_table.scan.return_value = {
            "Items": [
                {"event_id": "1", "discovered_by": "rider:1"},
                {"event_id": "2", "discovered_by": "rider:2"},
            ]
        }

        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        staging = DiscoveryStaging("test-table", dynamodb_resource=mock_dynamodb)

        result = staging.scan_all_events()

        assert len(result) == 2
        assert result[0]["event_id"] == "1"
        assert result[1]["event_id"] == "2"

    def test_scan_all_events_handles_pagination(self):
        """Test that scan_all_events handles pagination."""
        mock_table = MagicMock()

        # First page with LastEvaluatedKey
        first_response = {
            "Items": [{"event_id": "1", "discovered_by": "rider:1"}],
            "LastEvaluatedKey": {"event_id": "1", "discovered_by": "rider:1"},
        }

        # Second page without LastEvaluatedKey (final page)
        second_response = {
            "Items": [{"event_id": "2", "discovered_by": "rider:2"}],
        }

        mock_table.scan.side_effect = [first_response, second_response]

        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        staging = DiscoveryStaging("test-table", dynamodb_resource=mock_dynamodb)

        result = staging.scan_all_events()

        assert len(result) == 2
        assert mock_table.scan.call_count == 2


class TestDiscoveryStagingGetUniqueEvents:
    """Tests for getting deduplicated events."""

    def test_get_unique_events_deduplicates_by_event_id(self):
        """Test that events are deduplicated by event_id."""
        mock_table = MagicMock()
        mock_table.scan.return_value = {
            "Items": [
                {
                    "event_id": "1",
                    "discovered_by": "rider:1",
                    "event_name": "Event 1",
                    "timestamp": 1000,
                    "stage_number": "1",
                },
                {
                    "event_id": "1",
                    "discovered_by": "rider:2",
                    "event_name": "Event 1",
                    "timestamp": 1000,
                    "stage_number": "1",
                },
                {
                    "event_id": "2",
                    "discovered_by": "rider:1",
                    "event_name": "Event 2",
                    "timestamp": 2000,
                    "stage_number": "2",
                },
            ]
        }

        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        staging = DiscoveryStaging("test-table", dynamodb_resource=mock_dynamodb)

        result = staging.get_unique_events()

        assert len(result) == 2
        assert "1" in result
        assert "2" in result

    def test_get_unique_events_aggregates_stage_numbers(self):
        """Test that stage numbers are aggregated."""
        mock_table = MagicMock()
        mock_table.scan.return_value = {
            "Items": [
                {
                    "event_id": "1",
                    "discovered_by": "rider:1",
                    "event_name": "Event 1",
                    "timestamp": 1000,
                    "stage_number": "3.1",
                },
                {
                    "event_id": "1",
                    "discovered_by": "rider:2",
                    "event_name": "Event 1",
                    "timestamp": 1000,
                    "stage_number": "3.2",
                },
            ]
        }

        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        staging = DiscoveryStaging("test-table", dynamodb_resource=mock_dynamodb)

        result = staging.get_unique_events()

        assert len(result) == 1
        assert "3.1" in result["1"]["stage_numbers"]
        assert "3.2" in result["1"]["stage_numbers"]

    def test_get_unique_events_aggregates_discovery_sources(self):
        """Test that discovery sources are aggregated."""
        mock_table = MagicMock()
        mock_table.scan.return_value = {
            "Items": [
                {
                    "event_id": "1",
                    "discovered_by": "rider:1",
                    "event_name": "Event 1",
                    "timestamp": 1000,
                    "stage_number": "1",
                },
                {
                    "event_id": "1",
                    "discovered_by": "rider:2",
                    "event_name": "Event 1",
                    "timestamp": 1000,
                    "stage_number": "1",
                },
            ]
        }

        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        staging = DiscoveryStaging("test-table", dynamodb_resource=mock_dynamodb)

        result = staging.get_unique_events()

        assert len(result["1"]["discovered_by"]) == 2
        assert "rider:1" in result["1"]["discovered_by"]
        assert "rider:2" in result["1"]["discovered_by"]


class TestDiscoveryStagingClearStaging:
    """Tests for clearing the staging table."""

    def test_clear_staging_returns_zero_for_empty_table(self):
        """Test that clear_staging returns 0 for empty table."""
        mock_table = MagicMock()
        mock_table.scan.return_value = {"Items": []}

        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        staging = DiscoveryStaging("test-table", dynamodb_resource=mock_dynamodb)

        result = staging.clear_staging()

        assert result == 0

    def test_clear_staging_deletes_all_items(self):
        """Test that clear_staging deletes all items."""
        mock_table = MagicMock()
        mock_table.scan.return_value = {
            "Items": [
                {"event_id": "1", "discovered_by": "rider:1"},
                {"event_id": "2", "discovered_by": "rider:2"},
            ]
        }

        mock_batch_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(
            return_value=mock_batch_writer
        )
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=None)

        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        staging = DiscoveryStaging("test-table", dynamodb_resource=mock_dynamodb)

        result = staging.clear_staging()

        assert result == 2
        assert mock_batch_writer.delete_item.call_count == 2
