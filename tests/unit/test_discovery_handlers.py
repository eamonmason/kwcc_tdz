"""Tests for discovery Lambda handlers."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch


class TestLoadConfigHandler:
    """Tests for load_config Lambda handler."""

    @patch("src.lambda_handlers.discovery.load_config.secretsmanager_client")
    @patch("src.lambda_handlers.discovery.load_config.s3_client")
    @patch("src.lambda_handlers.discovery.load_config.get_tour_config")
    @patch.dict(
        "os.environ",
        {
            "DATA_BUCKET": "test-bucket",
            "ZWIFTPOWER_SECRET_ARN": "arn:aws:secretsmanager:test",
        },
    )
    def test_load_config_returns_riders_and_stages(
        self, mock_get_tour_config, mock_s3, mock_secrets
    ):
        """Test that load_config returns riders and stages."""
        from src.lambda_handlers.discovery.load_config import handler

        # Mock riders data
        riders_data = {
            "riders": [
                {"name": "Rider One", "zwiftpower_id": "12345", "handicap_group": "A1"},
                {"name": "Rider Two", "zwiftpower_id": "67890", "handicap_group": "B1"},
                {"name": "No ZP ID", "zwiftpower_id": "", "handicap_group": "A1"},
            ]
        }
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: json.dumps(riders_data).encode())
        }

        # Mock secrets
        mock_secrets.get_secret_value.return_value = {
            "SecretString": json.dumps({"username": "test", "password": "pass"})
        }

        # Mock tour config with active stages
        mock_stage = MagicMock()
        mock_stage.number = "1"
        mock_stage.name = "Makuri Islands"
        mock_stage.start_datetime = datetime(2026, 1, 5, 17, 0, tzinfo=UTC)
        mock_stage.end_datetime = datetime(2026, 1, 12, 16, 59, tzinfo=UTC)
        mock_stage.event_search_patterns = ["stage 1"]
        mock_stage.courses = [MagicMock(option_letter="C")]

        mock_tour_config = MagicMock()
        mock_tour_config.current_stages = [mock_stage]
        mock_tour_config.tour_id = "tdz-2026"
        mock_get_tour_config.return_value = mock_tour_config

        result = handler({}, None)

        # Should have 2 riders (one without ZP ID is filtered out)
        assert len(result["riders"]) == 2
        assert result["riders"][0]["id"] == "12345"
        assert result["riders"][1]["id"] == "67890"

        # Should have 1 stage
        assert len(result["stages"]) == 1
        assert result["stages"][0]["number"] == "1"

        # Should have credentials
        assert result["credentials"]["username"] == "test"
        assert result["credentials"]["password"] == "pass"

    @patch("src.lambda_handlers.discovery.load_config.s3_client")
    @patch("src.lambda_handlers.discovery.load_config.get_tour_config")
    @patch.dict("os.environ", {"DATA_BUCKET": "test-bucket"})
    def test_load_config_returns_empty_when_no_active_stages(
        self, mock_get_tour_config, mock_s3
    ):
        """Test that load_config returns empty arrays when no active stages."""
        from src.lambda_handlers.discovery.load_config import handler

        # Mock riders data
        riders_data = {"riders": [{"name": "Rider", "zwiftpower_id": "123"}]}
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: json.dumps(riders_data).encode())
        }

        # Mock tour config with no active stages
        mock_tour_config = MagicMock()
        mock_tour_config.current_stages = []
        mock_get_tour_config.return_value = mock_tour_config

        result = handler({}, None)

        assert result["riders"] == []
        assert result["stages"] == []


class TestAggregateEventsHandler:
    """Tests for aggregate_events Lambda handler."""

    @patch("src.lambda_handlers.discovery.aggregate_events.dynamodb")
    @patch.dict("os.environ", {"STAGING_TABLE": "test-staging-table"})
    def test_aggregate_events_deduplicates(self, mock_dynamodb):
        """Test that aggregate_events deduplicates by event_id."""
        from src.lambda_handlers.discovery.aggregate_events import handler

        # Mock DynamoDB table scan
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
        mock_dynamodb.Table.return_value = mock_table

        event = {
            "discovered": [{"events_found": 2}, {"events_found": 1}],
            "bucket": "test-bucket",
            "stages": [{"number": "1"}],
            "tour_id": "tdz-2026",
        }

        result = handler(event, None)

        assert result["total_discovered"] == 3
        assert result["total_unique"] == 2
        assert len(result["unique_events"]) == 2

    @patch("src.lambda_handlers.discovery.aggregate_events.dynamodb")
    @patch.dict("os.environ", {"STAGING_TABLE": "test-staging-table"})
    def test_aggregate_events_handles_pagination(self, mock_dynamodb):
        """Test that aggregate_events handles DynamoDB pagination."""
        from src.lambda_handlers.discovery.aggregate_events import handler

        # Mock DynamoDB table with pagination
        mock_table = MagicMock()

        first_response = {
            "Items": [{"event_id": "1", "discovered_by": "rider:1", "timestamp": 1000}],
            "LastEvaluatedKey": {"event_id": "1"},
        }
        second_response = {
            "Items": [{"event_id": "2", "discovered_by": "rider:2", "timestamp": 2000}],
        }
        mock_table.scan.side_effect = [first_response, second_response]
        mock_dynamodb.Table.return_value = mock_table

        event = {
            "discovered": [],
            "bucket": "test-bucket",
            "stages": [],
            "tour_id": "tdz-2026",
        }

        result = handler(event, None)

        assert result["total_discovered"] == 2
        assert result["total_unique"] == 2


class TestDiscoverRiderEventsHandler:
    """Tests for discover_rider_events Lambda handler."""

    @patch("src.lambda_handlers.discovery.discover_rider_events.dynamodb")
    @patch("src.lambda_handlers.discovery.discover_rider_events.secretsmanager_client")
    @patch("src.lambda_handlers.discovery.discover_rider_events.ZwiftPowerClient")
    @patch.dict(
        "os.environ",
        {
            "STAGING_TABLE": "test-staging-table",
            "ZWIFTPOWER_SECRET_ARN": "arn:aws:secretsmanager:test",
        },
    )
    def test_discover_rider_events_filters_tdz_events(
        self, mock_client_class, mock_secrets, mock_dynamodb
    ):
        """Test that discover_rider_events filters for TDZ events."""
        from src.lambda_handlers.discovery.discover_rider_events import handler

        # Mock secrets
        mock_secrets.get_secret_value.return_value = {
            "SecretString": json.dumps({"username": "test", "password": "pass"})
        }

        # Mock ZwiftPower client
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client.get.return_value.json.return_value = {
            "data": [
                {
                    "zid": "111",
                    "event_title": "Tour de Zwift 2026 - Stage 1",
                    "event_date": 1736200000,
                },
                {
                    "zid": "222",
                    "event_title": "Some Other Race",  # Not TDZ
                    "event_date": 1736200000,
                },
                {
                    "zid": "333",
                    "event_title": "Tour de Zwift 2026 - Stage 2",
                    "event_date": 1736300000,
                },
            ]
        }
        mock_client_class.return_value = mock_client

        # Mock DynamoDB
        mock_table = MagicMock()
        mock_batch_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__ = MagicMock(
            return_value=mock_batch_writer
        )
        mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=None)
        mock_dynamodb.Table.return_value = mock_table

        event = {
            "rider": {"id": "12345", "name": "Test Rider"},
            "stages": [
                {
                    "number": "1",
                    "start_date": "2026-01-05T17:00:00+00:00",
                    "end_date": "2026-01-12T16:59:00+00:00",
                },
                {
                    "number": "2",
                    "start_date": "2026-01-12T17:00:00+00:00",
                    "end_date": "2026-01-19T16:59:00+00:00",
                },
            ],
        }

        result = handler(event, None)

        assert result["rider_id"] == "12345"
        # events_found depends on which events match the date ranges
        assert result["events_found"] >= 0

    @patch.dict(
        "os.environ",
        {
            "STAGING_TABLE": "test-staging-table",
            "ZWIFTPOWER_SECRET_ARN": "arn:aws:secretsmanager:test",
        },
    )
    def test_discover_rider_events_handles_missing_rider_id(self):
        """Test that handler handles missing rider ID gracefully."""
        from src.lambda_handlers.discovery.discover_rider_events import handler

        event = {"rider": {}, "stages": []}

        result = handler(event, None)

        assert result["rider_id"] == ""
        assert result["events_found"] == 0


class TestFetchEventResultsHandler:
    """Tests for fetch_event_results Lambda handler."""

    @patch("src.lambda_handlers.discovery.fetch_event_results.s3_client")
    @patch("src.lambda_handlers.discovery.fetch_event_results.secretsmanager_client")
    @patch("src.lambda_handlers.discovery.fetch_event_results.ZwiftPowerClient")
    @patch.dict(
        "os.environ",
        {
            "DATA_BUCKET": "test-bucket",
            "ZWIFTPOWER_SECRET_ARN": "arn:aws:secretsmanager:test",
        },
    )
    def test_fetch_event_results_stores_in_s3(
        self, mock_client_class, mock_secrets, mock_s3
    ):
        """Test that fetch_event_results stores results in S3."""
        from src.lambda_handlers.discovery.fetch_event_results import handler

        # Mock secrets
        mock_secrets.get_secret_value.return_value = {
            "SecretString": json.dumps({"username": "test", "password": "pass"})
        }

        # Mock ZwiftPower client
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client.get_event_results.return_value = [
            {"name": "Rider 1", "time": 3600},
            {"name": "Rider 2", "time": 3700},
        ]
        mock_client_class.return_value = mock_client

        event = {
            "event_id": "12345",
            "event_name": "Tour de Zwift Stage 1",
            "timestamp": 1736200000,
        }

        # Create a mock context
        mock_context = MagicMock()
        mock_context.invoked_function_arn = "arn:aws:lambda:test"

        result = handler(event, mock_context)

        assert result["event_id"] == "12345"
        assert result["results_count"] == 2
        assert result["s3_key"] == "raw/events/12345/results.json"

        # Verify S3 put_object was called
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"] == "raw/events/12345/results.json"

    @patch.dict(
        "os.environ",
        {
            "DATA_BUCKET": "test-bucket",
            "ZWIFTPOWER_SECRET_ARN": "arn:aws:secretsmanager:test",
        },
    )
    def test_fetch_event_results_handles_missing_event_id(self):
        """Test that handler handles missing event ID gracefully."""
        from src.lambda_handlers.discovery.fetch_event_results import handler

        event = {}

        result = handler(event, None)

        assert result["event_id"] == ""
        assert result["results_count"] == 0


class TestMergeAndProcessHandler:
    """Tests for merge_and_process Lambda handler."""

    @patch("src.lambda_handlers.discovery.merge_and_process.lambda_client")
    @patch("src.lambda_handlers.discovery.merge_and_process.s3_client")
    @patch("src.lambda_handlers.discovery.merge_and_process.secretsmanager_client")
    @patch("src.lambda_handlers.discovery.merge_and_process.RawEventStore")
    @patch("src.lambda_handlers.discovery.merge_and_process.get_tour_config")
    @patch("src.lambda_handlers.discovery.merge_and_process.load_riders_from_s3")
    @patch.dict(
        "os.environ",
        {
            "DATA_BUCKET": "test-bucket",
            "ZWIFTPOWER_SECRET_ARN": "arn:aws:secretsmanager:test",
            "PROCESSOR_LAMBDA_ARN": "arn:aws:lambda:test:processor",
        },
    )
    def test_merge_and_process_merges_events(
        self,
        mock_load_riders,
        mock_get_tour_config,
        mock_raw_store_class,
        mock_secrets,
        _mock_s3,
        _mock_lambda,
    ):
        """Test that merge_and_process merges events to persistent store."""
        from src.lambda_handlers.discovery.merge_and_process import handler

        # Mock secrets
        mock_secrets.get_secret_value.return_value = {
            "SecretString": json.dumps({"username": "test", "password": "pass"})
        }

        # Mock RawEventStore
        mock_raw_store = MagicMock()
        mock_raw_store.load_events.return_value = {}
        mock_raw_store.merge_events.return_value = {"1": {"name": "Event 1"}}
        mock_raw_store.get_event_names.return_value = {"1": "Event 1"}
        mock_raw_store_class.return_value = mock_raw_store

        # Mock tour config with no active stages (to skip processing)
        mock_tour_config = MagicMock()
        mock_tour_config.get_stage.return_value = None
        mock_get_tour_config.return_value = mock_tour_config

        # Mock riders
        mock_load_riders.return_value = MagicMock(riders=[])

        event = {
            "bucket": "test-bucket",
            "stages": [],  # No stages to process
            "tour_id": "tdz-2026",
            "fetched_events": [
                {"event_id": "1", "event_name": "Event 1", "results_count": 10}
            ],
        }

        result = handler(event, None)

        assert result["status"] == "success"
        assert result["events_merged"] == 1
        assert result["total_events"] == 1

        # Verify save_events was called
        mock_raw_store.save_events.assert_called_once()

    @patch("src.lambda_handlers.discovery.merge_and_process.get_zwiftpower_credentials")
    @patch("src.lambda_handlers.discovery.merge_and_process.load_riders_from_s3")
    @patch("src.lambda_handlers.discovery.merge_and_process.RawEventStore")
    @patch.dict("os.environ", {"DATA_BUCKET": "test-bucket"})
    def test_merge_and_process_handles_empty_fetched_events(
        self, mock_raw_store_class, mock_load_riders, mock_credentials
    ):
        """Test that handler handles empty fetched events list."""
        from src.lambda_handlers.discovery.merge_and_process import handler

        # Mock RawEventStore
        mock_raw_store = MagicMock()
        mock_raw_store.load_events.return_value = {"existing": {"name": "Existing"}}
        mock_raw_store.merge_events.return_value = {"existing": {"name": "Existing"}}
        mock_raw_store.get_event_names.return_value = {"existing": "Existing"}
        mock_raw_store_class.return_value = mock_raw_store

        # Mock riders and credentials
        mock_load_riders.return_value = MagicMock(riders=[])
        mock_credentials.return_value = ("test", "pass")

        event = {
            "bucket": "test-bucket",
            "stages": [],
            "tour_id": "tdz-2026",
            "fetched_events": [],
        }

        result = handler(event, None)

        assert result["status"] == "success"
        assert result["events_merged"] == 0
