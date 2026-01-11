"""Tests for penalty configuration."""

import pytest
from datetime import datetime, time

from src.models.penalty import (
    PenaltyEvent,
    PenaltyConfig,
    DEFAULT_PENALTY_CONFIG,
    format_penalty,
)


class TestPenaltyEvent:
    """Tests for PenaltyEvent model."""

    def test_penalty_event_creation(self):
        """Test basic penalty event creation."""
        event = PenaltyEvent(
            event_time_utc=time(17, 0),
            day_of_week=0,  # Monday
            penalty_seconds=300,
            description="Monday 5pm penalty",
        )
        assert event.event_time_utc == time(17, 0)
        assert event.day_of_week == 0
        assert event.penalty_seconds == 300

    def test_day_of_week_validation(self):
        """Test day of week must be 0-6."""
        with pytest.raises(ValueError):
            PenaltyEvent(
                event_time_utc=time(17, 0),
                day_of_week=-1,
                penalty_seconds=300,
            )

        with pytest.raises(ValueError):
            PenaltyEvent(
                event_time_utc=time(17, 0),
                day_of_week=7,
                penalty_seconds=300,
            )


class TestPenaltyConfig:
    """Tests for PenaltyConfig model."""

    def test_get_penalty_monday_5pm(self):
        """Test penalty is applied for Monday 5pm event."""
        config = DEFAULT_PENALTY_CONFIG

        # Monday (day 0) at 5pm UTC
        event_dt = datetime(2026, 1, 5, 17, 0, 0)  # Monday Jan 5
        penalty = config.get_penalty(event_dt, stage_number=1)

        assert penalty == 60  # 1 minute

    def test_get_penalty_monday_6pm(self):
        """Test penalty is applied for Monday 6pm event."""
        config = DEFAULT_PENALTY_CONFIG

        # Monday (day 0) at 6pm UTC
        event_dt = datetime(2026, 1, 5, 18, 0, 0)  # Monday Jan 5
        penalty = config.get_penalty(event_dt, stage_number=1)

        assert penalty == 60  # 1 minute

    def test_no_penalty_other_days(self):
        """Test no penalty for non-Monday events."""
        config = DEFAULT_PENALTY_CONFIG

        # Tuesday at 5pm
        tuesday = datetime(2026, 1, 6, 17, 0, 0)
        assert config.get_penalty(tuesday, stage_number=1) == 0

        # Wednesday at 6pm
        wednesday = datetime(2026, 1, 7, 18, 0, 0)
        assert config.get_penalty(wednesday, stage_number=1) == 0

        # Sunday at 5pm
        sunday = datetime(2026, 1, 11, 17, 0, 0)
        assert config.get_penalty(sunday, stage_number=1) == 0

    def test_no_penalty_other_times(self):
        """Test no penalty for Monday at other times."""
        config = DEFAULT_PENALTY_CONFIG

        # Monday at 3pm
        monday_3pm = datetime(2026, 1, 5, 15, 0, 0)
        assert config.get_penalty(monday_3pm, stage_number=1) == 0

        # Monday at 8pm
        monday_8pm = datetime(2026, 1, 5, 20, 0, 0)
        assert config.get_penalty(monday_8pm, stage_number=1) == 0

    def test_penalty_free_week(self):
        """Test penalty is not applied during penalty-free weeks."""
        config = PenaltyConfig(
            penalty_free_weeks=[2],  # Stage 2 has no penalties
            penalty_events=[
                PenaltyEvent(
                    event_time_utc=time(17, 0),
                    day_of_week=0,
                    penalty_seconds=300,
                ),
            ],
        )

        # Monday 5pm during stage 1 - penalty applies
        stage1_monday = datetime(2026, 1, 5, 17, 0, 0)
        assert config.get_penalty(stage1_monday, stage_number=1) == 300

        # Monday 5pm during stage 2 - no penalty (penalty-free week)
        stage2_monday = datetime(2026, 1, 12, 17, 0, 0)
        assert config.get_penalty(stage2_monday, stage_number=2) == 0

        # Monday 5pm during stage 3 - penalty applies
        stage3_monday = datetime(2026, 1, 19, 17, 0, 0)
        assert config.get_penalty(stage3_monday, stage_number=3) == 300

    def test_time_tolerance(self):
        """Test 15-minute tolerance for event times."""
        config = DEFAULT_PENALTY_CONFIG

        # Monday at 5:14pm (within 15 min tolerance)
        within_tolerance = datetime(2026, 1, 5, 17, 14, 0)
        assert config.get_penalty(within_tolerance, stage_number=1) == 60

        # Monday at 5:16pm (outside 15 min tolerance)
        outside_tolerance = datetime(2026, 1, 5, 17, 16, 0)
        assert config.get_penalty(outside_tolerance, stage_number=1) == 0

        # Monday at 4:46pm (within 15 min tolerance before 5pm)
        before_tolerance = datetime(2026, 1, 5, 16, 46, 0)
        assert config.get_penalty(before_tolerance, stage_number=1) == 60

    def test_empty_config(self):
        """Test empty config returns no penalty."""
        config = PenaltyConfig(penalty_events=[])

        monday_5pm = datetime(2026, 1, 5, 17, 0, 0)
        assert config.get_penalty(monday_5pm, stage_number=1) == 0

    def test_multiple_penalty_events(self):
        """Test config with multiple penalty events on different days."""
        config = PenaltyConfig(
            penalty_events=[
                PenaltyEvent(
                    event_time_utc=time(17, 0),
                    day_of_week=0,  # Monday
                    penalty_seconds=300,
                ),
                PenaltyEvent(
                    event_time_utc=time(17, 0),
                    day_of_week=4,  # Friday
                    penalty_seconds=180,  # Different penalty
                ),
            ],
        )

        monday = datetime(2026, 1, 5, 17, 0, 0)
        assert config.get_penalty(monday, stage_number=1) == 300

        friday = datetime(2026, 1, 9, 17, 0, 0)
        assert config.get_penalty(friday, stage_number=1) == 180


class TestDefaultPenaltyConfig:
    """Tests for the default penalty configuration."""

    def test_default_config_has_monday_penalties(self):
        """Test default config includes Monday penalties."""
        config = DEFAULT_PENALTY_CONFIG

        assert len(config.penalty_events) == 2

        monday_events = [
            e for e in config.penalty_events if e.day_of_week == 0
        ]
        assert len(monday_events) == 2

        times = {e.event_time_utc for e in monday_events}
        assert time(17, 0) in times
        assert time(18, 0) in times

    def test_default_config_no_penalty_free_weeks(self):
        """Test default config has no penalty-free weeks by default."""
        assert DEFAULT_PENALTY_CONFIG.penalty_free_weeks == []


class TestFormatPenalty:
    """Tests for penalty formatting."""

    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0, ""),
            (30, "+30s"),
            (60, "+1m"),
            (90, "+1m"),  # Rounds down to minutes
            (180, "+3m"),
            (300, "+5m"),
        ],
    )
    def test_format_penalty(self, seconds: int, expected: str):
        """Test penalty formatting."""
        assert format_penalty(seconds) == expected
