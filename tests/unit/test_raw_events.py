"""Tests for raw event persistence (ELT pattern)."""

import json
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from src.persistence.raw_events import RawEventStore


class TestRawEventStoreLoadEvents:
    """Tests for loading persisted events."""

    def test_load_events_returns_empty_dict_when_no_file(self):
        """Test that load_events returns empty dict when file doesn't exist."""
        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
            "GetObject",
        )

        store = RawEventStore("test-bucket", s3_client=mock_s3)
        result = store.load_events()

        assert result == {}
        mock_s3.get_object.assert_called_once_with(
            Bucket="test-bucket", Key="raw/events/tdz_events.json"
        )

    def test_load_events_returns_persisted_data(self):
        """Test that load_events returns data from S3."""
        mock_s3 = MagicMock()
        persisted_data = {
            "5294594": {
                "zid": "5294594",
                "name": "Tour de Zwift 2026 - Stage 2",
                "timestamp": 1736787600,
                "discovery_timestamp": "2026-01-13T18:05:00Z",
            }
        }
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: json.dumps(persisted_data).encode())
        }

        store = RawEventStore("test-bucket", s3_client=mock_s3)
        result = store.load_events()

        assert result == persisted_data
        assert result["5294594"]["name"] == "Tour de Zwift 2026 - Stage 2"

    def test_load_events_raises_on_other_errors(self):
        """Test that load_events raises on non-NoSuchKey errors."""
        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
            "GetObject",
        )

        store = RawEventStore("test-bucket", s3_client=mock_s3)

        with pytest.raises(ClientError):
            store.load_events()


class TestRawEventStoreMergeEvents:
    """Tests for merging new events with existing."""

    def test_merge_events_adds_new_events(self):
        """Test that new events are added to existing."""
        store = RawEventStore("test-bucket")

        existing = {
            "1234": {
                "zid": "1234",
                "name": "Existing Event",
                "timestamp": 1736700000,
                "discovery_timestamp": "2026-01-12T10:00:00Z",
            }
        }

        new_events = [
            {
                "id": "5678",
                "name": "New Event",
                "timestamp": 1736787600,
            }
        ]

        result = store.merge_events(existing, new_events)

        assert len(result) == 2
        assert "1234" in result
        assert "5678" in result
        assert result["5678"]["name"] == "New Event"
        assert "discovery_timestamp" in result["5678"]

    def test_merge_events_preserves_existing(self):
        """Test that existing events are not overwritten."""
        store = RawEventStore("test-bucket")

        existing = {
            "1234": {
                "zid": "1234",
                "name": "Original Name",
                "timestamp": 1736700000,
                "discovery_timestamp": "2026-01-12T10:00:00Z",
            }
        }

        new_events = [
            {
                "id": "1234",
                "name": "Updated Name",  # Different name
                "timestamp": 1736787600,  # Different timestamp
            }
        ]

        result = store.merge_events(existing, new_events)

        assert len(result) == 1
        # Original data should be preserved
        assert result["1234"]["name"] == "Original Name"
        assert result["1234"]["timestamp"] == 1736700000
        assert result["1234"]["discovery_timestamp"] == "2026-01-12T10:00:00Z"

    def test_merge_events_handles_various_id_fields(self):
        """Test that merge handles various event ID field names."""
        store = RawEventStore("test-bucket")

        new_events = [
            {"id": "1111", "name": "Event 1"},
            {"zid": "2222", "name": "Event 2"},
            {"DT_RowId": "3333", "name": "Event 3"},
        ]

        result = store.merge_events({}, new_events)

        assert len(result) == 3
        assert "1111" in result
        assert "2222" in result
        assert "3333" in result

    def test_merge_events_handles_various_name_fields(self):
        """Test that merge handles various event name field names."""
        store = RawEventStore("test-bucket")

        new_events = [
            {"id": "1111", "name": "Name via name"},
            {"id": "2222", "t": "Name via t"},
            {"id": "3333", "title": "Name via title"},
        ]

        result = store.merge_events({}, new_events)

        assert result["1111"]["name"] == "Name via name"
        assert result["2222"]["name"] == "Name via t"
        assert result["3333"]["name"] == "Name via title"

    def test_merge_events_skips_events_without_id(self):
        """Test that events without ID are skipped."""
        store = RawEventStore("test-bucket")

        new_events = [
            {"name": "Event without ID"},
            {"id": "1234", "name": "Event with ID"},
        ]

        result = store.merge_events({}, new_events)

        assert len(result) == 1
        assert "1234" in result

    def test_merge_events_stores_raw_data(self):
        """Test that raw event data is preserved."""
        store = RawEventStore("test-bucket")

        new_events = [
            {
                "id": "1234",
                "name": "Test Event",
                "timestamp": 1736787600,
                "r": "france",
                "extra_field": "extra_value",
            }
        ]

        result = store.merge_events({}, new_events)

        assert result["1234"]["raw_data"] == new_events[0]


class TestRawEventStoreSaveEvents:
    """Tests for saving events to S3."""

    def test_save_events_writes_to_s3(self):
        """Test that save_events writes to S3."""
        mock_s3 = MagicMock()

        store = RawEventStore("test-bucket", s3_client=mock_s3)
        events = {
            "1234": {
                "zid": "1234",
                "name": "Test Event",
                "timestamp": 1736787600,
                "discovery_timestamp": "2026-01-13T18:05:00Z",
            }
        }

        store.save_events(events)

        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"] == "raw/events/tdz_events.json"
        assert call_kwargs["ContentType"] == "application/json"

        # Verify JSON content
        body_json = json.loads(call_kwargs["Body"])
        assert body_json["1234"]["name"] == "Test Event"


class TestRawEventStoreGetStageEvents:
    """Tests for filtering events by stage."""

    def test_get_stage_events_filters_by_stage_number(self):
        """Test that events are filtered by stage number."""
        store = RawEventStore("test-bucket")

        events = {
            "1111": {
                "zid": "1111",
                "name": "Tour de Zwift 2026 - Stage 1",
                "timestamp": 1736600000,
            },
            "2222": {
                "zid": "2222",
                "name": "Tour de Zwift 2026 - Stage 2",
                "timestamp": 1736700000,
            },
            "3333": {
                "zid": "3333",
                "name": "Tour de Zwift 2026 - Stage 2",
                "timestamp": 1736800000,
            },
        }

        result = store.get_stage_events(
            events,
            stage_number=2,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        event_ids = [eid for eid, _ in result]
        assert "2222" in event_ids
        assert "3333" in event_ids
        assert "1111" not in event_ids

    def test_get_stage_events_excludes_run_events(self):
        """Test that run events are excluded."""
        store = RawEventStore("test-bucket")

        events = {
            "1111": {
                "zid": "1111",
                "name": "Tour de Zwift 2026 - Stage 2 - Run",
                "timestamp": 1736700000,
            },
            "2222": {
                "zid": "2222",
                "name": "Tour de Zwift 2026 - Stage 2",
                "timestamp": 1736700000,
            },
        }

        result = store.get_stage_events(
            events,
            stage_number=2,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        event_ids = [eid for eid, _ in result]
        assert "1111" not in event_ids
        assert "2222" in event_ids

    def test_get_stage_events_scores_by_date_range(self):
        """Test that events in date range are scored higher."""
        store = RawEventStore("test-bucket")

        # Create events - one inside date range, one outside
        inside_range_ts = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC).timestamp()
        outside_range_ts = datetime(2026, 2, 15, 12, 0, 0, tzinfo=UTC).timestamp()

        events = {
            "inside": {
                "zid": "inside",
                "name": "Tour de Zwift 2026 - Stage 2",
                "timestamp": inside_range_ts,
            },
            "outside": {
                "zid": "outside",
                "name": "Tour de Zwift 2026 - Stage 2",
                "timestamp": outside_range_ts,
            },
        }

        result = store.get_stage_events(
            events,
            stage_number=2,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        # Both should be included (outside range still included with lower score)
        event_ids = [eid for eid, _ in result]
        assert "inside" in event_ids
        assert "outside" in event_ids

        # Inside range should be first (higher score)
        assert event_ids[0] == "inside"

    def test_get_stage_events_returns_timestamps(self):
        """Test that timestamps are converted to datetime."""
        store = RawEventStore("test-bucket")

        ts = datetime(2026, 1, 15, 17, 0, 0, tzinfo=UTC).timestamp()
        events = {
            "1234": {
                "zid": "1234",
                "name": "Tour de Zwift 2026 - Stage 2",
                "timestamp": ts,
            }
        }

        result = store.get_stage_events(
            events,
            stage_number=2,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        event_id, event_dt = result[0]
        assert event_id == "1234"
        assert event_dt is not None
        assert event_dt.year == 2026
        assert event_dt.month == 1
        assert event_dt.day == 15

    def test_get_stage_events_handles_missing_timestamp(self):
        """Test that events without timestamps are handled."""
        store = RawEventStore("test-bucket")

        events = {
            "1234": {
                "zid": "1234",
                "name": "Tour de Zwift 2026 - Stage 2",
                "timestamp": 0,  # Missing timestamp
            }
        }

        result = store.get_stage_events(
            events,
            stage_number=2,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        event_id, event_dt = result[0]
        assert event_id == "1234"
        assert event_dt is None


class TestRawEventStoreGetEventNames:
    """Tests for extracting event names."""

    def test_get_event_names(self):
        """Test extracting event names from persisted events."""
        store = RawEventStore("test-bucket")

        events = {
            "1111": {"zid": "1111", "name": "Event One"},
            "2222": {"zid": "2222", "name": "Event Two"},
            "3333": {"zid": "3333", "name": ""},  # Empty name
        }

        result = store.get_event_names(events)

        assert result["1111"] == "Event One"
        assert result["2222"] == "Event Two"
        assert result["3333"] == ""


class TestRawEventStoreIntegration:
    """Integration tests for the full ELT workflow."""

    def test_full_elt_workflow(self):
        """Test the complete Extract-Load-Transform workflow."""
        mock_s3 = MagicMock()

        # Initial state: no persisted events
        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
            "GetObject",
        )

        store = RawEventStore("test-bucket", s3_client=mock_s3)

        # Load (empty)
        persisted = store.load_events()
        assert persisted == {}

        # Extract (new events from API)
        new_events = [
            {
                "id": "5294594",
                "name": "Tour de Zwift 2026 - Stage 2",
                "timestamp": 1736787600,
            },
            {
                "id": "5294595",
                "name": "Tour de Zwift 2026 - Stage 2",
                "timestamp": 1736788600,
            },
        ]

        # Merge
        merged = store.merge_events(persisted, new_events)
        assert len(merged) == 2

        # Save
        store.save_events(merged)
        mock_s3.put_object.assert_called_once()

        # Second run: simulate loading the saved events
        mock_s3.get_object.side_effect = None
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: json.dumps(merged).encode())
        }

        # Load again
        persisted2 = store.load_events()
        assert len(persisted2) == 2

        # Merge with new events (one duplicate, one new)
        more_events = [
            {
                "id": "5294594",
                "name": "Updated Name",
                "timestamp": 1736787600,
            },  # Duplicate
            {
                "id": "5294596",
                "name": "Tour de Zwift 2026 - Stage 2",
                "timestamp": 1736789600,
            },  # New
        ]

        merged2 = store.merge_events(persisted2, more_events)

        # Should have 3 events (original preserved, new added)
        assert len(merged2) == 3
        # Original name preserved
        assert merged2["5294594"]["name"] == "Tour de Zwift 2026 - Stage 2"
        # New event added
        assert "5294596" in merged2

    def test_stage_filtering_preserves_aged_events(self):
        """Test that old events not in API are still found via persisted store."""
        store = RawEventStore("test-bucket")

        # Scenario: Event 5294594 was discovered on Jan 13 but aged out of API
        # It should still be found via the persisted store
        ts_jan13 = datetime(2026, 1, 13, 17, 0, 0, tzinfo=UTC).timestamp()

        persisted_events = {
            "5294594": {
                "zid": "5294594",
                "name": "Tour de Zwift 2026 - Stage 2 - France",
                "timestamp": ts_jan13,
                "discovery_timestamp": "2026-01-13T18:05:00Z",
            }
        }

        # Query for Stage 2 events in the Jan 13-19 date range
        result = store.get_stage_events(
            persisted_events,
            stage_number=2,
            start_date=date(2026, 1, 13),
            end_date=date(2026, 1, 19),
        )

        # Event should be found even though it would have aged out of API
        event_ids = [eid for eid, _ in result]
        assert "5294594" in event_ids
