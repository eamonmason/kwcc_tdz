"""Tests for configuration loaders."""

import json
import tempfile
from pathlib import Path

import pytest

from src.config.loader import (
    load_riders_from_csv,
    load_riders_from_json,
    save_riders_to_json,
)
from src.models.rider import Rider, RiderRegistry


class TestLoadRidersFromCSV:
    """Tests for CSV rider loading."""

    def test_load_valid_csv(self):
        """Test loading valid CSV file."""
        csv_content = """Name,ZwiftPower ID,Handicap Group,ZP Racing Score
Tom Kennett,997635,A1,750
Chris Jenkins,2456208,A2,742
Eamon Mason,1231961,A3,542"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            f.flush()
            csv_path = Path(f.name)

        try:
            registry = load_riders_from_csv(csv_path)

            assert len(registry.riders) == 3
            assert registry.riders[0].name == "Tom Kennett"
            assert registry.riders[0].zwiftpower_id == "997635"
            assert registry.riders[0].handicap_group == "A1"
            assert registry.riders[0].zp_racing_score == 750
        finally:
            csv_path.unlink()

    def test_skips_missing_required_fields(self):
        """Test rows with missing required fields are skipped."""
        csv_content = """Name,ZwiftPower ID,Handicap Group,ZP Racing Score
Tom Kennett,997635,A1,750
,2456208,A2,742
Chris Jenkins,,A2,742
Eamon Mason,1231961,,542"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            f.flush()
            csv_path = Path(f.name)

        try:
            registry = load_riders_from_csv(csv_path)

            # Only Tom Kennett should be loaded
            assert len(registry.riders) == 1
            assert registry.riders[0].name == "Tom Kennett"
        finally:
            csv_path.unlink()

    def test_skips_invalid_handicap_groups(self):
        """Test rows with invalid handicap groups are skipped."""
        csv_content = """Name,ZwiftPower ID,Handicap Group,ZP Racing Score
Tom Kennett,997635,A1,750
Invalid Rider,123456,C1,500
Another Invalid,654321,A5,600"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            f.flush()
            csv_path = Path(f.name)

        try:
            registry = load_riders_from_csv(csv_path)

            assert len(registry.riders) == 1
            assert registry.riders[0].name == "Tom Kennett"
        finally:
            csv_path.unlink()

    def test_handles_tbc_racing_score(self):
        """Test TBC racing score is handled as None."""
        csv_content = """Name,ZwiftPower ID,Handicap Group,ZP Racing Score
Tom Kennett,997635,A1,TBC"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            f.flush()
            csv_path = Path(f.name)

        try:
            registry = load_riders_from_csv(csv_path)

            assert len(registry.riders) == 1
            assert registry.riders[0].zp_racing_score is None
        finally:
            csv_path.unlink()

    def test_handles_empty_racing_score(self):
        """Test empty racing score is handled as None."""
        csv_content = """Name,ZwiftPower ID,Handicap Group,ZP Racing Score
Tom Kennett,997635,A1,"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            f.flush()
            csv_path = Path(f.name)

        try:
            registry = load_riders_from_csv(csv_path)

            assert len(registry.riders) == 1
            assert registry.riders[0].zp_racing_score is None
        finally:
            csv_path.unlink()

    def test_file_not_found(self):
        """Test FileNotFoundError for non-existent file."""
        with pytest.raises(FileNotFoundError):
            load_riders_from_csv("/nonexistent/path.csv")

    def test_case_insensitive_handicap_group(self):
        """Test handicap group is uppercased."""
        csv_content = """Name,ZwiftPower ID,Handicap Group,ZP Racing Score
Tom Kennett,997635,a1,750
Chris Jenkins,2456208,b3,742"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            f.flush()
            csv_path = Path(f.name)

        try:
            registry = load_riders_from_csv(csv_path)

            assert len(registry.riders) == 2
            assert registry.riders[0].handicap_group == "A1"
            assert registry.riders[1].handicap_group == "B3"
        finally:
            csv_path.unlink()

    def test_strips_whitespace(self):
        """Test whitespace is stripped from fields."""
        csv_content = """Name,ZwiftPower ID,Handicap Group,ZP Racing Score
  Tom Kennett  ,  997635  ,  A1  ,750"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            f.flush()
            csv_path = Path(f.name)

        try:
            registry = load_riders_from_csv(csv_path)

            assert len(registry.riders) == 1
            assert registry.riders[0].name == "Tom Kennett"
            assert registry.riders[0].zwiftpower_id == "997635"
            assert registry.riders[0].handicap_group == "A1"
        finally:
            csv_path.unlink()


class TestLoadRidersFromJSON:
    """Tests for JSON rider loading."""

    def test_load_list_format(self):
        """Test loading JSON file with list format."""
        riders_data = [
            {
                "name": "Tom Kennett",
                "zwiftpower_id": "997635",
                "handicap_group": "A1",
                "zp_racing_score": 750,
            },
            {
                "name": "Chris Jenkins",
                "zwiftpower_id": "2456208",
                "handicap_group": "A2",
                "zp_racing_score": 742,
            },
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(riders_data, f)
            f.flush()
            json_path = Path(f.name)

        try:
            registry = load_riders_from_json(json_path)

            assert len(registry.riders) == 2
            assert registry.riders[0].name == "Tom Kennett"
            assert registry.riders[1].name == "Chris Jenkins"
        finally:
            json_path.unlink()

    def test_load_dict_format(self):
        """Test loading JSON file with dict/riders key format."""
        data = {
            "riders": [
                {
                    "name": "Tom Kennett",
                    "zwiftpower_id": "997635",
                    "handicap_group": "A1",
                    "zp_racing_score": 750,
                },
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            json_path = Path(f.name)

        try:
            registry = load_riders_from_json(json_path)

            assert len(registry.riders) == 1
            assert registry.riders[0].name == "Tom Kennett"
        finally:
            json_path.unlink()

    def test_file_not_found(self):
        """Test FileNotFoundError for non-existent file."""
        with pytest.raises(FileNotFoundError):
            load_riders_from_json("/nonexistent/path.json")

    def test_invalid_format(self):
        """Test ValueError for invalid JSON format."""
        # Just a string, not list or dict with riders
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump("invalid", f)
            f.flush()
            json_path = Path(f.name)

        try:
            with pytest.raises(ValueError):
                load_riders_from_json(json_path)
        finally:
            json_path.unlink()


class TestSaveRidersToJSON:
    """Tests for JSON rider saving."""

    def test_save_creates_file(self):
        """Test saving creates JSON file."""
        registry = RiderRegistry(
            riders=[
                Rider(
                    name="Tom Kennett",
                    zwiftpower_id="997635",
                    handicap_group="A1",
                    zp_racing_score=750,
                ),
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "riders.json"

            save_riders_to_json(registry, json_path)

            assert json_path.exists()

            with json_path.open() as f:
                data = json.load(f)

            assert "riders" in data
            assert len(data["riders"]) == 1
            assert data["riders"][0]["name"] == "Tom Kennett"

    def test_save_creates_parent_directories(self):
        """Test saving creates parent directories if needed."""
        registry = RiderRegistry(riders=[])

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "nested" / "path" / "riders.json"

            save_riders_to_json(registry, json_path)

            assert json_path.exists()

    def test_round_trip(self):
        """Test save then load preserves data."""
        original = RiderRegistry(
            riders=[
                Rider(
                    name="Tom Kennett",
                    zwiftpower_id="997635",
                    handicap_group="A1",
                    zp_racing_score=750,
                ),
                Rider(
                    name="Chris Jenkins",
                    zwiftpower_id="2456208",
                    handicap_group="B3",
                    zp_racing_score=None,
                ),
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "riders.json"

            save_riders_to_json(original, json_path)
            loaded = load_riders_from_json(json_path)

            assert len(loaded.riders) == len(original.riders)
            assert loaded.riders[0].name == original.riders[0].name
            assert loaded.riders[0].zwiftpower_id == original.riders[0].zwiftpower_id
            assert loaded.riders[0].handicap_group == original.riders[0].handicap_group
            assert loaded.riders[0].zp_racing_score == original.riders[0].zp_racing_score
            assert loaded.riders[1].zp_racing_score == original.riders[1].zp_racing_score
