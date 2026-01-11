"""Tests for data models."""

from datetime import datetime

import pytest

from src.models.result import RaceResult, StageResult, format_time, parse_time
from src.models.rider import Rider


class TestRider:
    """Tests for Rider model."""

    def test_rider_creation(self):
        """Test basic rider creation."""
        rider = Rider(
            name="Tom Kennett",
            zwiftpower_id="997635",
            handicap_group="A1",
            zp_racing_score=750,
        )
        assert rider.name == "Tom Kennett"
        assert rider.zwiftpower_id == "997635"
        assert rider.handicap_group == "A1"
        assert rider.zp_racing_score == 750

    def test_race_group_computed_field(self):
        """Test race group is extracted from handicap group."""
        rider_a = Rider(name="Test A", zwiftpower_id="1", handicap_group="A2")
        rider_b = Rider(name="Test B", zwiftpower_id="2", handicap_group="B3")

        assert rider_a.race_group == "A"
        assert rider_b.race_group == "B"

    @pytest.mark.parametrize(
        "handicap_group,expected_seconds",
        [
            ("A1", 600),  # 10 min
            ("A2", 300),  # 5 min
            ("A3", 0),    # scratch
            ("B1", 900),  # 15 min
            ("B2", 600),  # 10 min
            ("B3", 240),  # 4 min
            ("B4", 0),    # scratch
        ],
    )
    def test_handicap_seconds(self, handicap_group: str, expected_seconds: int):
        """Test handicap seconds for each group."""
        rider = Rider(name="Test", zwiftpower_id="1", handicap_group=handicap_group)
        assert rider.handicap_seconds == expected_seconds

    @pytest.mark.parametrize(
        "handicap_group,expected_display",
        [
            ("A1", "+10 min"),
            ("A2", "+5 min"),
            ("A3", "scratch"),
            ("B1", "+15 min"),
            ("B2", "+10 min"),
            ("B3", "+4 min"),
            ("B4", "scratch"),
        ],
    )
    def test_handicap_display(self, handicap_group: str, expected_display: str):
        """Test handicap display formatting."""
        rider = Rider(name="Test", zwiftpower_id="1", handicap_group=handicap_group)
        assert rider.handicap_display == expected_display

    def test_invalid_handicap_group(self):
        """Test that invalid handicap groups are rejected."""
        with pytest.raises(ValueError):
            Rider(name="Test", zwiftpower_id="1", handicap_group="C1")

        with pytest.raises(ValueError):
            Rider(name="Test", zwiftpower_id="1", handicap_group="A5")


class TestRiderRegistry:
    """Tests for RiderRegistry model."""

    def test_get_by_zwiftpower_id(self, rider_registry):
        """Test finding rider by ZwiftPower ID."""
        rider = rider_registry.get_by_zwiftpower_id("997635")
        assert rider is not None
        assert rider.name == "Tom Kennett"

    def test_get_by_zwiftpower_id_not_found(self, rider_registry):
        """Test finding non-existent rider returns None."""
        rider = rider_registry.get_by_zwiftpower_id("nonexistent")
        assert rider is None

    def test_get_by_name(self, rider_registry):
        """Test finding rider by name."""
        rider = rider_registry.get_by_name("Tom Kennett")
        assert rider is not None
        assert rider.zwiftpower_id == "997635"

    def test_get_by_name_partial_match(self, rider_registry):
        """Test finding rider by partial name."""
        rider = rider_registry.get_by_name("Kennett")
        assert rider is not None
        assert rider.name == "Tom Kennett"

    def test_get_by_name_case_insensitive(self, rider_registry):
        """Test name search is case-insensitive."""
        rider = rider_registry.get_by_name("TOM KENNETT")
        assert rider is not None
        assert rider.name == "Tom Kennett"

    def test_get_group_riders(self, rider_registry):
        """Test getting riders by race group."""
        group_a = rider_registry.get_group_riders("A")
        group_b = rider_registry.get_group_riders("B")

        assert len(group_a) == 3  # A1, A2, A3 riders
        assert len(group_b) == 4  # B1, B2, B3, B4 riders

        assert all(r.race_group == "A" for r in group_a)
        assert all(r.race_group == "B" for r in group_b)

    def test_group_a_riders_property(self, rider_registry):
        """Test group_a_riders property."""
        group_a = rider_registry.group_a_riders
        assert len(group_a) == 3
        assert all(r.race_group == "A" for r in group_a)

    def test_group_b_riders_property(self, rider_registry):
        """Test group_b_riders property."""
        group_b = rider_registry.group_b_riders
        assert len(group_b) == 4
        assert all(r.race_group == "B" for r in group_b)


class TestRaceResult:
    """Tests for RaceResult model."""

    def test_race_result_creation(self):
        """Test basic RaceResult creation."""
        result = RaceResult(
            rider_id="997635",
            rider_name="Tom Kennett",
            stage_number=1,
            event_id="12345",
            raw_time_seconds=2400,
            finish_position=1,
            timestamp=datetime(2026, 1, 6, 18, 0, 0),
        )
        assert result.rider_id == "997635"
        assert result.raw_time_seconds == 2400
        assert result.finish_position == 1

    def test_raw_time_display(self):
        """Test raw time display formatting."""
        result = RaceResult(
            rider_id="1",
            rider_name="Test",
            stage_number=1,
            event_id="12345",
            raw_time_seconds=2400,  # 40:00
            finish_position=1,
            timestamp=datetime(2026, 1, 6, 18, 0, 0),
        )
        assert result.raw_time_display == "40:00"

    def test_stage_number_validation(self):
        """Test stage number must be 1-6."""
        with pytest.raises(ValueError):
            RaceResult(
                rider_id="1",
                rider_name="Test",
                stage_number=0,
                event_id="12345",
                raw_time_seconds=2400,
                finish_position=1,
                timestamp=datetime(2026, 1, 6, 18, 0, 0),
            )

        with pytest.raises(ValueError):
            RaceResult(
                rider_id="1",
                rider_name="Test",
                stage_number=7,
                event_id="12345",
                raw_time_seconds=2400,
                finish_position=1,
                timestamp=datetime(2026, 1, 6, 18, 0, 0),
            )


class TestStageResult:
    """Tests for StageResult model."""

    def test_stage_result_creation(self):
        """Test basic StageResult creation."""
        result = StageResult(
            rider_name="Tom Kennett",
            rider_id="997635",
            stage_number=1,
            race_group="A",
            handicap_group="A1",
            raw_time_seconds=2400,
            handicap_seconds=600,
            position=1,
            raw_position=1,
        )
        assert result.rider_name == "Tom Kennett"
        assert result.handicap_seconds == 600

    def test_adjusted_time_seconds(self):
        """Test adjusted time calculation."""
        result = StageResult(
            rider_name="Test",
            rider_id="1",
            stage_number=1,
            race_group="A",
            handicap_group="A1",
            raw_time_seconds=2400,  # 40 min
            handicap_seconds=600,    # +10 min
            penalty_seconds=0,
            position=1,
            raw_position=1,
        )
        assert result.adjusted_time_seconds == 3000  # 50 min

    def test_adjusted_time_with_penalty(self):
        """Test adjusted time includes penalty."""
        result = StageResult(
            rider_name="Test",
            rider_id="1",
            stage_number=1,
            race_group="A",
            handicap_group="A1",
            raw_time_seconds=2400,  # 40 min
            handicap_seconds=600,   # +10 min
            penalty_seconds=60,     # +1 min
            penalty_reason="Monday 17:00 UTC event",
            position=1,
            raw_position=1,
        )
        assert result.adjusted_time_seconds == 3060  # 51 min
        assert result.has_penalty is True
        assert result.penalty_display == "+1m"

    def test_no_penalty_display(self):
        """Test penalty display when no penalty."""
        result = StageResult(
            rider_name="Test",
            rider_id="1",
            stage_number=1,
            race_group="A",
            handicap_group="A1",
            raw_time_seconds=2400,
            handicap_seconds=600,
            penalty_seconds=0,
            position=1,
            raw_position=1,
        )
        assert result.has_penalty is False
        assert result.penalty_display == ""

    def test_handicap_display(self):
        """Test handicap display formatting."""
        result_with_handicap = StageResult(
            rider_name="Test",
            rider_id="1",
            stage_number=1,
            race_group="A",
            handicap_group="A1",
            raw_time_seconds=2400,
            handicap_seconds=600,
            position=1,
            raw_position=1,
        )
        assert result_with_handicap.handicap_display == "+10m"

        result_scratch = StageResult(
            rider_name="Test",
            rider_id="1",
            stage_number=1,
            race_group="A",
            handicap_group="A3",
            raw_time_seconds=2400,
            handicap_seconds=0,
            position=1,
            raw_position=1,
        )
        assert result_scratch.handicap_display == "scratch"

    def test_gap_display(self):
        """Test gap to leader display."""
        leader = StageResult(
            rider_name="Leader",
            rider_id="1",
            stage_number=1,
            race_group="A",
            handicap_group="A1",
            raw_time_seconds=2400,
            handicap_seconds=600,
            position=1,
            raw_position=1,
            gap_to_leader=0,
        )
        assert leader.gap_display == "-"

        follower = StageResult(
            rider_name="Follower",
            rider_id="2",
            stage_number=1,
            race_group="A",
            handicap_group="A2",
            raw_time_seconds=2450,
            handicap_seconds=300,
            position=2,
            raw_position=2,
            gap_to_leader=150,
        )
        assert follower.gap_display == "+2:30"


class TestTimeFormatting:
    """Tests for time formatting utilities."""

    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0, "0:00"),
            (30, "0:30"),
            (60, "1:00"),
            (90, "1:30"),
            (2400, "40:00"),
            (2550, "42:30"),
            (3600, "1:00:00"),
            (3661, "1:01:01"),
            (7325, "2:02:05"),
        ],
    )
    def test_format_time(self, seconds: int, expected: str):
        """Test time formatting."""
        assert format_time(seconds) == expected

    @pytest.mark.parametrize(
        "time_str,expected_seconds",
        [
            ("0:00", 0),
            ("0:30", 30),
            ("1:00", 60),
            ("40:00", 2400),
            ("42:30", 2550),
            ("1:00:00", 3600),
            ("1:01:01", 3661),
            ("2:02:05", 7325),
        ],
    )
    def test_parse_time(self, time_str: str, expected_seconds: int):
        """Test time parsing."""
        assert parse_time(time_str) == expected_seconds

    def test_parse_time_invalid(self):
        """Test invalid time format raises error."""
        with pytest.raises(ValueError):
            parse_time("invalid")

        with pytest.raises(ValueError):
            parse_time("1:2:3:4")
