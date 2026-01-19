"""Tests for race vs ride detection in Course model."""

from datetime import UTC, datetime

from src.models.tour import Course


class TestRaceDetection:
    """Tests for Course.is_race_event()."""

    def test_detects_race_with_space_before(self):
        """Test detection of ' race' pattern."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
        )

        assert course.is_race_event("event1", "Tour de Zwift Stage 1 Race") is True

    def test_detects_race_with_space_after(self):
        """Test detection of 'race ' pattern."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
        )

        assert course.is_race_event("event1", "Race Event - Stage 1") is True

    def test_detects_race_with_dash(self):
        """Test detection of '-race-' pattern."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
        )

        assert course.is_race_event("event1", "Stage 1 - Race - Tour de Zwift") is True

    def test_detects_race_with_parentheses(self):
        """Test detection of '(race)' pattern."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
        )

        assert course.is_race_event("event1", "Tour de Zwift Stage 1 (Race)") is True

    def test_detects_race_with_brackets(self):
        """Test detection of '[race]' pattern."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
        )

        assert course.is_race_event("event1", "Tour de Zwift Stage 1 [Race]") is True

    def test_does_not_detect_trace_as_race(self):
        """Test 'trace' in route name is not detected as race."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
        )

        # "Watopia Trace" should not be detected as a race
        assert course.is_race_event("event1", "Watopia Trace - Group Ride") is False

    def test_detects_group_ride_as_not_race(self):
        """Test Group Ride is not detected as race."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
        )

        assert (
            course.is_race_event("event1", "Tour de Zwift Stage 1 - Group Ride")
            is False
        )

    def test_case_insensitive_detection(self):
        """Test race detection is case insensitive."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
        )

        assert course.is_race_event("event1", "Tour de Zwift Stage 1 RACE") is True
        assert course.is_race_event("event1", "Tour de Zwift Stage 1 Race") is True
        assert course.is_race_event("event1", "Tour de Zwift Stage 1 race") is True

    def test_uses_event_names_dict(self):
        """Test event name lookup from event_names dict."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
            event_names={
                "race123": "Tour de Zwift Stage 1 - Race",
                "ride456": "Tour de Zwift Stage 1 - Group Ride",
            },
        )

        # Should use stored event name
        assert course.is_race_event("race123") is True
        assert course.is_race_event("ride456") is False

    def test_provided_name_overrides_stored_name(self):
        """Test provided event_name overrides stored name."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
            event_names={
                "event1": "Stored Name - Race",
            },
        )

        # Provided name should override
        assert course.is_race_event("event1", "Override Name - Group Ride") is False

    def test_returns_false_for_missing_event_name(self):
        """Test returns False when event name is not available."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
        )

        # No event name provided or stored
        assert course.is_race_event("unknown_event") is False


class TestGetRacePenalty:
    """Tests for Course.get_race_penalty()."""

    def test_returns_penalty_for_race_when_allowed(self):
        """Test penalty is returned for race event when allowed."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
            allow_race_events=True,
            race_event_penalty_seconds=60,
        )

        penalty = course.get_race_penalty("event1", "Tour de Zwift Stage 1 - Race")
        assert penalty == 60

    def test_returns_zero_for_race_when_not_allowed(self):
        """Test zero penalty for race event when not allowed (will be excluded)."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
            allow_race_events=False,
            race_event_penalty_seconds=60,
        )

        penalty = course.get_race_penalty("event1", "Tour de Zwift Stage 1 - Race")
        assert penalty == 0  # Will be excluded instead

    def test_returns_zero_for_ride_event(self):
        """Test no penalty for ride (non-race) event."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
            allow_race_events=True,
            race_event_penalty_seconds=60,
        )

        penalty = course.get_race_penalty(
            "event1", "Tour de Zwift Stage 1 - Group Ride"
        )
        assert penalty == 0

    def test_custom_penalty_amount(self):
        """Test custom penalty amount is used."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
            allow_race_events=True,
            race_event_penalty_seconds=120,  # 2 minutes
        )

        penalty = course.get_race_penalty("event1", "Tour de Zwift Stage 1 - Race")
        assert penalty == 120


class TestShouldExcludeResult:
    """Tests for Course.should_exclude_result()."""

    def test_excludes_race_when_not_allowed(self):
        """Test race results are excluded when races not allowed."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
            allow_race_events=False,
        )

        should_exclude = course.should_exclude_result(
            "event1", "Tour de Zwift Stage 2 - Race"
        )
        assert should_exclude is True

    def test_does_not_exclude_race_when_allowed(self):
        """Test race results are not excluded when races allowed."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
            allow_race_events=True,
        )

        should_exclude = course.should_exclude_result(
            "event1", "Tour de Zwift Stage 1 - Race"
        )
        assert should_exclude is False

    def test_does_not_exclude_ride_event(self):
        """Test ride events are never excluded."""
        course = Course(
            route="Test Route",
            distance_km=20.0,
            elevation_m=100,
            allow_race_events=False,
        )

        should_exclude = course.should_exclude_result(
            "event1", "Tour de Zwift Stage 2 - Group Ride"
        )
        assert should_exclude is False


class TestStageRaceMethods:
    """Tests for Stage-level race detection methods."""

    def test_stage_delegates_to_course(self):
        """Test Stage methods delegate to appropriate Course."""
        from src.models.tour import Stage

        stage = Stage(
            number="1",
            name="Test Stage",
            courses=[
                Course(
                    route="Route A",
                    distance_km=20.0,
                    elevation_m=100,
                    event_ids=["event1"],
                    allow_race_events=True,
                    race_event_penalty_seconds=60,
                    event_names={"event1": "Stage 1 - Race"},
                ),
            ],
            start_datetime=datetime(2026, 1, 5, 17, 0, tzinfo=UTC),
            end_datetime=datetime(2026, 1, 12, 16, 59, tzinfo=UTC),
        )

        # Test get_race_penalty
        penalty = stage.get_race_penalty("event1")
        assert penalty == 60

        # Test should_exclude_result
        should_exclude = stage.should_exclude_result("event1")
        assert should_exclude is False

    def test_stage_falls_back_to_primary_course(self):
        """Test Stage falls back to primary course for unknown events."""
        from src.models.tour import Stage

        stage = Stage(
            number="2",
            name="Test Stage",
            courses=[
                Course(
                    route="Route A",
                    distance_km=20.0,
                    elevation_m=100,
                    event_ids=["event1"],
                    allow_race_events=False,  # Primary course: races not allowed
                ),
            ],
            start_datetime=datetime(2026, 1, 12, 17, 0, tzinfo=UTC),
            end_datetime=datetime(2026, 1, 19, 16, 59, tzinfo=UTC),
        )

        # Unknown event should use primary course settings
        should_exclude = stage.should_exclude_result("unknown_event", "Stage 2 - Race")
        assert should_exclude is True

    def test_stage_with_multiple_courses(self):
        """Test Stage with multiple courses selects correct one."""
        from src.models.tour import Stage

        stage = Stage(
            number="3.1",
            name="Test Stage",
            courses=[
                Course(
                    route="Route A",
                    distance_km=30.0,
                    elevation_m=300,
                    event_ids=["event_a"],
                    allow_race_events=False,
                ),
                Course(
                    route="Route B",
                    distance_km=20.0,
                    elevation_m=200,
                    event_ids=["event_b"],
                    allow_race_events=True,
                    race_event_penalty_seconds=90,
                ),
            ],
            start_datetime=datetime(2026, 1, 19, 17, 0, tzinfo=UTC),
            end_datetime=datetime(2026, 1, 26, 16, 59, tzinfo=UTC),
        )

        # Event A: races not allowed
        assert stage.should_exclude_result("event_a", "Race") is True
        assert stage.get_race_penalty("event_a", "Race") == 0

        # Event B: races allowed with 90s penalty
        assert stage.should_exclude_result("event_b", "Race") is False
        assert stage.get_race_penalty("event_b", "Race") == 90
