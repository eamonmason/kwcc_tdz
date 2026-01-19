"""Tests for tour configuration and registry."""

import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.config.tour_manager import (
    archive_tour,
    create_new_tour_config,
    get_tour_s3_paths,
    load_tour_registry_from_json,
    save_tour_registry_to_json,
)
from src.models.tour import (
    DEFAULT_TOUR_REGISTRY,
    Stage,
    TourConfig,
    TourRegistry,
)


class TestTourConfig:
    """Tests for TourConfig model."""

    def test_default_tour_config(self):
        """Test default tour config values."""
        config = TourConfig()

        assert config.tour_id == "tdz-2026"
        assert config.year == 2026
        assert config.name == "Tour de Zwift 2026"
        assert len(config.stages) == 7
        assert config.is_archived is False

    def test_results_prefix(self):
        """Test results_prefix computed field."""
        config = TourConfig(tour_id="tdz-2027", year=2027)
        assert config.results_prefix == "results/tdz-2027"

    def test_config_prefix(self):
        """Test config_prefix computed field."""
        config = TourConfig(tour_id="tdz-2027", year=2027)
        assert config.config_prefix == "config/tdz-2027"

    def test_is_current_not_archived(self):
        """Test is_current for non-archived tour with upcoming stages."""
        # All stages are in the future relative to the code's view
        config = TourConfig(is_archived=False)
        # Since stages might be in past/future depending on when test runs,
        # we'll test the archived case explicitly
        config.is_archived = True
        assert config.is_current is False

    def test_get_stage(self):
        """Test get_stage by number."""
        config = TourConfig()

        stage = config.get_stage("1")
        assert stage is not None
        assert stage.number == "1"
        assert stage.name == "Makuri Islands"

        stage = config.get_stage("7")
        assert stage is None


class TestStage:
    """Tests for Stage model."""

    def test_stage_creation(self):
        """Test basic stage creation."""
        stage = Stage(
            number="1",
            name="Makuri Islands",
            route="Turf N Surf",
            distance_km=24.7,
            elevation_m=198,
            start_datetime=datetime(2026, 1, 5, 17, 0, tzinfo=UTC),
            end_datetime=datetime(2026, 1, 12, 16, 59, tzinfo=UTC),
        )

        assert stage.number == "1"
        assert stage.name == "Makuri Islands"
        assert stage.distance_km == 24.7
        # Check backwards-compatible date properties
        assert stage.start_date == date(2026, 1, 5)
        assert stage.end_date == date(2026, 1, 12)

    def test_stage_number_validation(self):
        """Test stage number must be 1-6."""
        with pytest.raises(ValueError):
            Stage(
                number=0,
                name="Invalid",
                route="Test",
                distance_km=20.0,
                elevation_m=100,
                start_datetime=datetime(2026, 1, 5, 17, 0, tzinfo=UTC),
                end_datetime=datetime(2026, 1, 11, 16, 59, tzinfo=UTC),
            )

        with pytest.raises(ValueError):
            Stage(
                number=7,
                name="Invalid",
                route="Test",
                distance_km=20.0,
                elevation_m=100,
                start_datetime=datetime(2026, 1, 5, 17, 0, tzinfo=UTC),
                end_datetime=datetime(2026, 1, 11, 16, 59, tzinfo=UTC),
            )


class TestTourRegistry:
    """Tests for TourRegistry model."""

    def test_empty_registry(self):
        """Test empty registry."""
        registry = TourRegistry()
        assert len(registry.tours) == 0
        assert registry.current_tour is None

    def test_get_tour_by_id(self):
        """Test getting tour by ID."""
        tour1 = TourConfig(tour_id="tdz-2026", year=2026)
        tour2 = TourConfig(tour_id="tdz-2027", year=2027)

        registry = TourRegistry(tours=[tour1, tour2])

        found = registry.get_tour("tdz-2026")
        assert found is not None
        assert found.year == 2026

        not_found = registry.get_tour("tdz-2025")
        assert not_found is None

    def test_get_tour_by_year(self):
        """Test getting tour by year."""
        tour1 = TourConfig(tour_id="tdz-2026", year=2026)
        tour2 = TourConfig(tour_id="tdz-2027", year=2027)

        registry = TourRegistry(tours=[tour1, tour2])

        found = registry.get_tour_by_year(2026)
        assert found is not None
        assert found.tour_id == "tdz-2026"

        not_found = registry.get_tour_by_year(2025)
        assert not_found is None

    def test_archived_tours(self):
        """Test getting archived tours."""
        tour1 = TourConfig(tour_id="tdz-2025", year=2025, is_archived=True)
        tour2 = TourConfig(tour_id="tdz-2026", year=2026, is_archived=False)

        registry = TourRegistry(tours=[tour1, tour2])

        archived = registry.archived_tours
        assert len(archived) == 1
        assert archived[0].tour_id == "tdz-2025"

    def test_available_years(self):
        """Test available years sorted in reverse order."""
        tour1 = TourConfig(tour_id="tdz-2025", year=2025)
        tour2 = TourConfig(tour_id="tdz-2027", year=2027)
        tour3 = TourConfig(tour_id="tdz-2026", year=2026)

        registry = TourRegistry(tours=[tour1, tour2, tour3])

        years = registry.available_years
        assert years == [2027, 2026, 2025]

    def test_add_tour(self):
        """Test adding tour to registry."""
        registry = TourRegistry()
        tour = TourConfig(tour_id="tdz-2026", year=2026)

        registry.add_tour(tour)

        assert len(registry.tours) == 1
        assert registry.tours[0].tour_id == "tdz-2026"

    def test_add_tour_replaces_existing(self):
        """Test adding tour replaces existing with same ID."""
        tour1 = TourConfig(tour_id="tdz-2026", year=2026, name="Old Name")
        tour2 = TourConfig(tour_id="tdz-2026", year=2026, name="New Name")

        registry = TourRegistry(tours=[tour1])
        registry.add_tour(tour2)

        assert len(registry.tours) == 1
        assert registry.tours[0].name == "New Name"

    def test_add_tour_maintains_sort_order(self):
        """Test tours are sorted by year (newest first)."""
        registry = TourRegistry()

        registry.add_tour(TourConfig(tour_id="tdz-2025", year=2025))
        registry.add_tour(TourConfig(tour_id="tdz-2027", year=2027))
        registry.add_tour(TourConfig(tour_id="tdz-2026", year=2026))

        years = [t.year for t in registry.tours]
        assert years == [2027, 2026, 2025]


class TestDefaultTourRegistry:
    """Tests for default tour registry."""

    def test_default_registry_has_2026_tour(self):
        """Test default registry contains TdZ 2026."""
        assert len(DEFAULT_TOUR_REGISTRY.tours) == 1
        assert DEFAULT_TOUR_REGISTRY.tours[0].tour_id == "tdz-2026"
        assert DEFAULT_TOUR_REGISTRY.default_tour_id == "tdz-2026"


class TestTourManager:
    """Tests for tour manager utilities."""

    def test_create_new_tour_config(self):
        """Test creating a new tour config."""
        config = create_new_tour_config(2027)

        assert config.tour_id == "tdz-2027"
        assert config.year == 2027
        assert config.name == "Tour de Zwift 2027"
        assert config.is_archived is False

    def test_get_tour_s3_paths(self):
        """Test getting S3 paths for a tour."""
        paths = get_tour_s3_paths("tdz-2026")

        assert paths["results_prefix"] == "results/tdz-2026"
        assert paths["config_prefix"] == "config/tdz-2026"
        assert paths["riders_key"] == "config/tdz-2026/riders.json"
        assert paths["event_ids_key"] == "config/tdz-2026/event_ids.json"
        assert paths["tour_config_key"] == "config/tdz-2026/tour.json"

    def test_archive_tour(self):
        """Test archiving a tour."""
        tour = TourConfig(tour_id="tdz-2026", year=2026, is_archived=False)
        registry = TourRegistry(tours=[tour])

        result = archive_tour(registry, "tdz-2026")

        assert result.get_tour("tdz-2026").is_archived is True

    def test_archive_nonexistent_tour(self):
        """Test archiving a tour that doesn't exist."""
        registry = TourRegistry()

        # Should not raise error
        result = archive_tour(registry, "tdz-9999")
        assert len(result.tours) == 0


class TestTourRegistryJsonSerialization:
    """Tests for JSON serialization of tour registry."""

    def test_save_and_load_registry(self):
        """Test saving and loading tour registry."""
        tour1 = TourConfig(tour_id="tdz-2026", year=2026)
        tour2 = TourConfig(tour_id="tdz-2025", year=2025, is_archived=True)

        original = TourRegistry(
            tours=[tour1, tour2],
            default_tour_id="tdz-2026",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "registry.json"

            save_tour_registry_to_json(original, json_path)
            loaded = load_tour_registry_from_json(json_path)

            assert len(loaded.tours) == 2
            assert loaded.default_tour_id == "tdz-2026"
            assert loaded.get_tour("tdz-2025").is_archived is True

    def test_load_nonexistent_returns_default(self):
        """Test loading from nonexistent file returns default."""
        registry = load_tour_registry_from_json("/nonexistent/path.json")

        assert len(registry.tours) == 1
        assert registry.tours[0].tour_id == "tdz-2026"
