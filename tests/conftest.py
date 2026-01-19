"""Pytest fixtures for KWCC TdZ tests."""

from datetime import datetime

import pytest

from src.models import (
    RaceResult,
    Rider,
    RiderRegistry,
)


@pytest.fixture
def sample_riders() -> list[Rider]:
    """Create sample riders for testing."""
    return [
        Rider(
            name="Tom Kennett",
            zwiftpower_id="997635",
            handicap_group="A1",
            zp_racing_score=750,
        ),
        Rider(
            name="Chris Jenkins",
            zwiftpower_id="2456208",
            handicap_group="A2",
            zp_racing_score=742,
        ),
        Rider(
            name="Eamon Mason",
            zwiftpower_id="1231961",
            handicap_group="A3",
            zp_racing_score=542,
        ),
        Rider(
            name="Adam Currie",
            zwiftpower_id="4037257",
            handicap_group="B1",
            zp_racing_score=234,
        ),
        Rider(
            name="Gareth Edwards",
            zwiftpower_id="1746490",
            handicap_group="B2",
            zp_racing_score=263,
        ),
        Rider(
            name="Tom Bagley",
            zwiftpower_id="783382",
            handicap_group="B3",
            zp_racing_score=226,
        ),
        Rider(
            name="James Turner",
            zwiftpower_id="1098357",
            handicap_group="B4",
            zp_racing_score=216,
        ),
    ]


@pytest.fixture
def rider_registry(sample_riders) -> RiderRegistry:
    """Create a rider registry with sample riders."""
    return RiderRegistry(riders=sample_riders)


@pytest.fixture
def sample_race_results() -> list[RaceResult]:
    """Create sample race results for testing."""
    return [
        RaceResult(
            rider_id="997635",
            rider_name="Tom Kennett",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=2400,  # 40 minutes
            finish_position=1,
            timestamp=datetime(2026, 1, 6, 18, 0, 0),
        ),
        RaceResult(
            rider_id="2456208",
            rider_name="Chris Jenkins",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=2520,  # 42 minutes
            finish_position=2,
            timestamp=datetime(2026, 1, 6, 18, 0, 0),
        ),
        RaceResult(
            rider_id="1231961",
            rider_name="Eamon Mason",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=2700,  # 45 minutes
            finish_position=3,
            timestamp=datetime(2026, 1, 6, 18, 0, 0),
        ),
        RaceResult(
            rider_id="4037257",
            rider_name="Adam Currie",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=3000,  # 50 minutes
            finish_position=4,
            timestamp=datetime(2026, 1, 6, 18, 0, 0),
        ),
        RaceResult(
            rider_id="1098357",
            rider_name="James Turner",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=3300,  # 55 minutes
            finish_position=5,
            timestamp=datetime(2026, 1, 6, 18, 0, 0),
        ),
    ]


@pytest.fixture
def penalty_race_result() -> RaceResult:
    """Create a race result from a penalty event (Monday 5pm)."""
    return RaceResult(
        rider_id="1231961",
        rider_name="Eamon Mason",
        stage_number="1",
        event_id="12346",
        raw_time_seconds=2600,  # 43:20
        finish_position=1,
        timestamp=datetime(2026, 1, 6, 17, 0, 0),  # Monday 5pm UTC
    )
