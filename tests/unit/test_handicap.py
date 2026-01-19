"""Tests for handicap and stage results processing."""

from datetime import datetime

from src.models.penalty import DEFAULT_PENALTY_CONFIG
from src.models.result import RaceResult, StageResult
from src.models.rider import Rider, RiderRegistry
from src.processor.handicap import (
    apply_handicap,
    apply_handicap_and_penalty,
    get_best_result_per_rider,
    process_stage_results,
)


class TestApplyHandicap:
    """Tests for apply_handicap function."""

    def test_apply_handicap_a1_rider(self):
        """Test handicap applied to A1 rider (+10 min)."""
        rider = Rider(name="Fast A", zwiftpower_id="1", handicap_group="A1")
        race_result = RaceResult(
            rider_id="1",
            rider_name="Fast A",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=2400,  # 40 min
            finish_position=1,
            timestamp=datetime(2026, 1, 6, 18, 0, 0),
        )

        stage_result = apply_handicap(race_result, rider)

        assert stage_result.raw_time_seconds == 2400
        assert stage_result.handicap_seconds == 600  # +10 min
        assert stage_result.adjusted_time_seconds == 3000  # 50 min
        assert stage_result.penalty_seconds == 0

    def test_apply_handicap_a3_scratch_rider(self):
        """Test handicap for A3 scratch rider (0 min)."""
        rider = Rider(name="Slow A", zwiftpower_id="3", handicap_group="A3")
        race_result = RaceResult(
            rider_id="3",
            rider_name="Slow A",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=2700,  # 45 min
            finish_position=3,
            timestamp=datetime(2026, 1, 6, 18, 0, 0),
        )

        stage_result = apply_handicap(race_result, rider)

        assert stage_result.handicap_seconds == 0
        assert stage_result.adjusted_time_seconds == 2700  # No change

    def test_apply_handicap_b1_rider(self):
        """Test handicap applied to B1 rider (+15 min)."""
        rider = Rider(name="Fast B", zwiftpower_id="4", handicap_group="B1")
        race_result = RaceResult(
            rider_id="4",
            rider_name="Fast B",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=2400,
            finish_position=1,
            timestamp=datetime(2026, 1, 6, 18, 0, 0),
        )

        stage_result = apply_handicap(race_result, rider)

        assert stage_result.handicap_seconds == 900  # +15 min
        assert stage_result.adjusted_time_seconds == 3300  # 55 min

    def test_apply_handicap_b3_rider(self):
        """Test handicap applied to B3 rider (+4 min)."""
        rider = Rider(name="Mid B", zwiftpower_id="6", handicap_group="B3")
        race_result = RaceResult(
            rider_id="6",
            rider_name="Mid B",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=2700,
            finish_position=2,
            timestamp=datetime(2026, 1, 6, 18, 0, 0),
        )

        stage_result = apply_handicap(race_result, rider)

        assert stage_result.handicap_seconds == 240  # +4 min
        assert stage_result.adjusted_time_seconds == 2940

    def test_apply_handicap_preserves_rider_info(self):
        """Test that rider info is correctly transferred."""
        rider = Rider(name="Test Rider", zwiftpower_id="123", handicap_group="A2")
        race_result = RaceResult(
            rider_id="123",
            rider_name="Test Rider",
            stage_number="3.1",
            event_id="12345",
            raw_time_seconds=2500,
            finish_position=5,
            timestamp=datetime(2026, 1, 20, 18, 0, 0),
        )

        stage_result = apply_handicap(race_result, rider)

        assert stage_result.rider_name == "Test Rider"
        assert stage_result.rider_id == "123"
        assert stage_result.race_group == "A"
        assert stage_result.handicap_group == "A2"
        assert stage_result.stage_number == "3.1"
        assert stage_result.raw_position == 5


class TestApplyHandicapAndPenalty:
    """Tests for apply_handicap_and_penalty function."""

    def test_no_penalty_when_config_none(self):
        """Test no penalty applied when config is None."""
        rider = Rider(name="Test", zwiftpower_id="1", handicap_group="A1")
        race_result = RaceResult(
            rider_id="1",
            rider_name="Test",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=2400,
            finish_position=1,
            timestamp=datetime(2026, 1, 5, 17, 0, 0),  # Monday 5pm
        )

        stage_result = apply_handicap_and_penalty(
            race_result, rider, penalty_config=None
        )

        assert stage_result.penalty_seconds == 0
        assert stage_result.penalty_reason == ""

    def test_penalty_applied_for_monday_5pm(self):
        """Test penalty applied for Monday 5pm event."""
        rider = Rider(name="Test", zwiftpower_id="1", handicap_group="A1")
        race_result = RaceResult(
            rider_id="1",
            rider_name="Test",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=2400,
            finish_position=1,
            timestamp=datetime(2026, 1, 5, 17, 0, 0),  # Monday 5pm
        )

        stage_result = apply_handicap_and_penalty(
            race_result, rider, penalty_config=DEFAULT_PENALTY_CONFIG
        )

        assert stage_result.penalty_seconds == 60
        assert "Monday" in stage_result.penalty_reason
        assert "17:00" in stage_result.penalty_reason

    def test_combined_handicap_and_penalty(self):
        """Test both handicap and penalty are applied."""
        rider = Rider(name="Test", zwiftpower_id="1", handicap_group="A1")
        race_result = RaceResult(
            rider_id="1",
            rider_name="Test",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=2400,  # 40 min
            finish_position=1,
            timestamp=datetime(2026, 1, 5, 17, 0, 0),  # Monday 5pm
        )

        stage_result = apply_handicap_and_penalty(
            race_result, rider, penalty_config=DEFAULT_PENALTY_CONFIG
        )

        # 40 min raw + 10 min handicap + 1 min penalty = 51 min
        assert stage_result.adjusted_time_seconds == 3060

    def test_no_penalty_for_non_penalty_event(self):
        """Test no penalty for regular Tuesday event."""
        rider = Rider(name="Test", zwiftpower_id="1", handicap_group="A1")
        race_result = RaceResult(
            rider_id="1",
            rider_name="Test",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=2400,
            finish_position=1,
            timestamp=datetime(2026, 1, 6, 18, 0, 0),  # Tuesday 6pm
        )

        stage_result = apply_handicap_and_penalty(
            race_result, rider, penalty_config=DEFAULT_PENALTY_CONFIG
        )

        assert stage_result.penalty_seconds == 0
        assert stage_result.penalty_reason == ""


class TestProcessStageResults:
    """Tests for process_stage_results function."""

    def test_process_splits_groups(self, sample_riders, sample_race_results):
        """Test results are split into Group A and Group B."""
        registry = RiderRegistry(riders=sample_riders)

        group_a, group_b, _ = process_stage_results(
            sample_race_results,
            registry,
            stage_number="1",
        )

        assert len(group_a) == 3  # Tom (A1), Chris (A2), Eamon (A3)
        assert len(group_b) == 2  # Adam (B1), James (B4)

        assert all(r.race_group == "A" for r in group_a)
        assert all(r.race_group == "B" for r in group_b)

    def test_process_calculates_positions(self, sample_riders, sample_race_results):
        """Test positions are calculated correctly after handicap."""
        registry = RiderRegistry(riders=sample_riders)

        group_a, _, _ = process_stage_results(
            sample_race_results,
            registry,
            stage_number="1",
        )

        # Results sorted by adjusted time
        assert group_a[0].position == 1
        assert group_a[1].position == 2
        assert group_a[2].position == 3

    def test_process_calculates_gaps(self, sample_riders, sample_race_results):
        """Test gaps to leader are calculated correctly."""
        registry = RiderRegistry(riders=sample_riders)

        group_a, _, _ = process_stage_results(
            sample_race_results,
            registry,
            stage_number="1",
        )

        assert group_a[0].gap_to_leader == 0  # Leader
        assert group_a[1].gap_to_leader > 0  # Behind leader

    def test_process_with_penalty_config(self, sample_riders):
        """Test results include penalties when configured."""
        registry = RiderRegistry(riders=sample_riders)

        # Create race result for Monday 5pm event
        race_results = [
            RaceResult(
                rider_id="997635",  # Tom Kennett (A1)
                rider_name="Tom Kennett",
                stage_number="1",
                event_id="12345",
                raw_time_seconds=2400,
                finish_position=1,
                timestamp=datetime(2026, 1, 5, 17, 0, 0),  # Monday 5pm
            ),
        ]

        group_a, _, _ = process_stage_results(
            race_results,
            registry,
            stage_number="1",
            penalty_config=DEFAULT_PENALTY_CONFIG,
        )

        assert len(group_a) == 1
        assert group_a[0].penalty_seconds == 60

    def test_process_filters_unknown_riders(self, sample_riders):
        """Test unknown riders are filtered out."""
        registry = RiderRegistry(riders=sample_riders)

        race_results = [
            RaceResult(
                rider_id="997635",  # Known rider
                rider_name="Tom Kennett",
                stage_number="1",
                event_id="12345",
                raw_time_seconds=2400,
                finish_position=1,
                timestamp=datetime(2026, 1, 6, 18, 0, 0),
            ),
            RaceResult(
                rider_id="unknown123",  # Unknown rider
                rider_name="Unknown Person",
                stage_number="1",
                event_id="12345",
                raw_time_seconds=2300,
                finish_position=2,
                timestamp=datetime(2026, 1, 6, 18, 0, 0),
            ),
        ]

        group_a, group_b, _ = process_stage_results(
            race_results,
            registry,
            stage_number="1",
        )

        total_results = len(group_a) + len(group_b)
        assert total_results == 1  # Only known rider

    def test_process_sets_provisional_flag(self, sample_riders, sample_race_results):
        """Test provisional flag is set on results."""
        registry = RiderRegistry(riders=sample_riders)

        group_a, group_b, _ = process_stage_results(
            sample_race_results,
            registry,
            stage_number="1",
            is_provisional=True,
        )

        assert all(r.is_provisional for r in group_a)
        assert all(r.is_provisional for r in group_b)


class TestGetBestResultPerRider:
    """Tests for get_best_result_per_rider function."""

    def test_single_result_per_rider(self):
        """Test single results are preserved."""
        results = [
            StageResult(
                rider_name="Rider 1",
                rider_id="1",
                stage_number="1",
                race_group="A",
                handicap_group="A1",
                raw_time_seconds=2400,
                handicap_seconds=600,
                position=1,
                raw_position=1,
            ),
            StageResult(
                rider_name="Rider 2",
                rider_id="2",
                stage_number="1",
                race_group="A",
                handicap_group="A2",
                raw_time_seconds=2500,
                handicap_seconds=300,
                position=2,
                raw_position=2,
            ),
        ]

        best = get_best_result_per_rider(results)

        assert len(best) == 2

    def test_keeps_best_result(self):
        """Test only best result per rider is kept."""
        results = [
            # First attempt - slower
            StageResult(
                rider_name="Rider 1",
                rider_id="1",
                stage_number="1",
                race_group="A",
                handicap_group="A1",
                raw_time_seconds=2600,  # 43:20 raw + 600 = 3200
                handicap_seconds=600,
                position=1,
                raw_position=1,
            ),
            # Second attempt - faster (best)
            StageResult(
                rider_name="Rider 1",
                rider_id="1",
                stage_number="1",
                race_group="A",
                handicap_group="A1",
                raw_time_seconds=2400,  # 40:00 raw + 600 = 3000
                handicap_seconds=600,
                position=1,
                raw_position=1,
            ),
        ]

        best = get_best_result_per_rider(results)

        assert len(best) == 1
        assert best[0].raw_time_seconds == 2400  # Best result

    def test_selects_fastest_raw_time(self):
        """
        Test best result is based on FASTEST RAW TIME, not adjusted time.

        NEW BEHAVIOR: If the fastest raw time is from a penalty stage,
        the penalty is applied to that time, even if it results in a
        slower adjusted time than another attempt.

        Example:
        - Penalty stage: raw=45:10 (2710s), +1min penalty → adjusted=46:10 (2770s)
        - Non-penalty stage: raw=45:30 (2730s), no penalty → adjusted=45:30 (2730s)
        - Result: 46:10 is used (fastest raw time with penalty applied)
        """
        results = [
            # Faster raw time but with penalty (THIS SHOULD BE SELECTED)
            StageResult(
                rider_name="Rider 1",
                rider_id="1",
                stage_number="1",
                race_group="A",
                handicap_group="A1",
                raw_time_seconds=2710,  # 45:10 raw + 600 handicap + 60 penalty = 3370
                handicap_seconds=600,
                penalty_seconds=60,
                position=1,
                raw_position=1,
            ),
            # Slower raw time but no penalty (better adjusted, but NOT selected)
            StageResult(
                rider_name="Rider 1",
                rider_id="1",
                stage_number="1",
                race_group="A",
                handicap_group="A1",
                raw_time_seconds=2730,  # 45:30 raw + 600 handicap + 0 penalty = 3330
                handicap_seconds=600,
                penalty_seconds=0,
                position=1,
                raw_position=1,
            ),
        ]

        best = get_best_result_per_rider(results)

        assert len(best) == 1
        # Should select the result with fastest RAW time (2710), even though
        # its adjusted time (3370) is slower than the other result (3330)
        assert best[0].raw_time_seconds == 2710  # Fastest raw time
        assert best[0].penalty_seconds == 60  # Has penalty
        assert (
            best[0].adjusted_time_seconds == 3370
        )  # Slower adjusted time, but that's OK

    def test_empty_list(self):
        """Test empty list returns empty list."""
        assert get_best_result_per_rider([]) == []


class TestProcessStageResultsWithMultipleRaces:
    """Tests for process_stage_results with multiple races per rider."""

    def test_penalty_uses_fastest_raw_time(self):
        """
        Test that FASTEST RAW TIME is selected, even with penalty.

        NEW BEHAVIOR - Scenario:
        - Monday 5pm race: 33:35 raw + 1 min penalty = 34:35 adjusted
        - Monday 7pm race: 34:08 raw + 0 penalty = 34:08 adjusted
        The 5pm race should be selected as best (fastest raw time),
        even though the penalty makes the adjusted time slower.
        """
        rider = Rider(name="Judah Rand", zwiftpower_id="123", handicap_group="B4")
        registry = RiderRegistry(riders=[rider])

        # Two races from the same rider in different events
        race_results = [
            # Monday 5pm race - faster raw but with penalty (SHOULD BE SELECTED)
            RaceResult(
                rider_id="123",
                rider_name="Judah Rand",
                stage_number="1",
                event_id="5215254",  # Monday 5pm event
                raw_time_seconds=2015,  # 33:35
                finish_position=1,
                timestamp=datetime(2026, 1, 5, 17, 0, 0),  # Monday 5pm
            ),
            # Monday 7pm race - slower raw but no penalty
            RaceResult(
                rider_id="123",
                rider_name="Judah Rand",
                stage_number="1",
                event_id="5215255",  # Monday 7pm event
                raw_time_seconds=2048,  # 34:08
                finish_position=1,
                timestamp=datetime(2026, 1, 5, 19, 0, 0),  # Monday 7pm
            ),
        ]

        _group_a, group_b, _ = process_stage_results(
            race_results,
            registry,
            stage_number="1",
            penalty_config=DEFAULT_PENALTY_CONFIG,
        )

        # B4 rider should be in group B
        assert len(group_b) == 1
        result = group_b[0]

        # NEW BEHAVIOR: Should have selected the 5pm race (33:35) as best
        # because it has the fastest RAW time, even though penalty makes
        # the adjusted time slower:
        # 5pm race: 33:35 raw + 1min penalty = 34:35 adjusted (SELECTED)
        # 7pm race: 34:08 raw + 0 penalty = 34:08 adjusted
        assert result.raw_time_seconds == 2015  # 33:35 from 5pm race (fastest raw)
        assert result.penalty_seconds == 60  # Has penalty from 5pm
        assert (
            result.adjusted_time_seconds == 2075
        )  # 33:35 + 1min penalty (B4 has 0 handicap)

    def test_multiple_riders_with_multiple_races(self):
        """Test multiple riders each with multiple race results."""
        riders = [
            Rider(name="Rider A", zwiftpower_id="1", handicap_group="A1"),
            Rider(name="Rider B", zwiftpower_id="2", handicap_group="A2"),
        ]
        registry = RiderRegistry(riders=riders)

        race_results = [
            # Rider A - 5pm race (with penalty) - FASTEST RAW TIME, should be selected
            RaceResult(
                rider_id="1",
                rider_name="Rider A",
                stage_number="1",
                event_id="event1",
                raw_time_seconds=2000,  # Fastest raw + 60s penalty = 2060
                finish_position=1,
                timestamp=datetime(2026, 1, 5, 17, 0, 0),
            ),
            # Rider A - 7pm race (no penalty) - slower raw time
            RaceResult(
                rider_id="1",
                rider_name="Rider A",
                stage_number="1",
                event_id="event2",
                raw_time_seconds=2050,  # Slower raw, no penalty = 2050
                finish_position=2,
                timestamp=datetime(2026, 1, 5, 19, 0, 0),
            ),
            # Rider B - only one race
            RaceResult(
                rider_id="2",
                rider_name="Rider B",
                stage_number="1",
                event_id="event1",
                raw_time_seconds=2100,
                finish_position=3,
                timestamp=datetime(2026, 1, 5, 17, 0, 0),  # Has penalty
            ),
        ]

        group_a, group_b, _ = process_stage_results(
            race_results,
            registry,
            stage_number="1",
            penalty_config=DEFAULT_PENALTY_CONFIG,
        )

        assert len(group_a) == 2
        assert len(group_b) == 0

        # Find Rider A's result - should have fastest RAW time (5pm race)
        rider_a_result = next(r for r in group_a if r.rider_id == "1")
        assert (
            rider_a_result.raw_time_seconds == 2000
        )  # 5pm race selected (fastest raw)
        assert rider_a_result.penalty_seconds == 60  # Has penalty

        # Find Rider B's result
        rider_b_result = next(r for r in group_a if r.rider_id == "2")
        assert rider_b_result.penalty_seconds == 60  # Has penalty


class TestGuestRiderHandling:
    """Tests for guest rider functionality."""

    def test_guest_flag_propagated_to_stage_result(self):
        """Test guest flag is carried from Rider to StageResult."""
        guest_rider = Rider(
            name="Guest Rider",
            zwiftpower_id="999",
            handicap_group="A1",
            guest=True,
        )
        race_result = RaceResult(
            rider_id="999",
            rider_name="Guest Rider",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=2400,
            finish_position=1,
            timestamp=datetime(2026, 1, 6, 18, 0, 0),
        )

        stage_result = apply_handicap(race_result, guest_rider)

        assert stage_result.guest is True
        assert stage_result.rider_name == "Guest Rider"

    def test_non_guest_rider_has_false_guest_flag(self):
        """Test non-guest rider has guest=False by default."""
        regular_rider = Rider(
            name="Club Member",
            zwiftpower_id="123",
            handicap_group="A1",
        )
        race_result = RaceResult(
            rider_id="123",
            rider_name="Club Member",
            stage_number="1",
            event_id="12345",
            raw_time_seconds=2400,
            finish_position=1,
            timestamp=datetime(2026, 1, 6, 18, 0, 0),
        )

        stage_result = apply_handicap(race_result, regular_rider)

        assert stage_result.guest is False

    def test_guest_rider_appears_in_stage_results(self):
        """Test guest riders appear in stage results with other riders."""
        riders = [
            Rider(name="Club Rider", zwiftpower_id="1", handicap_group="A1"),
            Rider(
                name="Guest Rider",
                zwiftpower_id="2",
                handicap_group="A2",
                guest=True,
            ),
        ]
        registry = RiderRegistry(riders=riders)

        race_results = [
            RaceResult(
                rider_id="1",
                rider_name="Club Rider",
                stage_number="1",
                event_id="12345",
                raw_time_seconds=2400,
                finish_position=1,
                timestamp=datetime(2026, 1, 6, 18, 0, 0),
            ),
            RaceResult(
                rider_id="2",
                rider_name="Guest Rider",
                stage_number="1",
                event_id="12345",
                raw_time_seconds=2500,
                finish_position=2,
                timestamp=datetime(2026, 1, 6, 18, 0, 0),
            ),
        ]

        group_a, _, _ = process_stage_results(
            race_results,
            registry,
            stage_number="1",
        )

        assert len(group_a) == 2
        guest_result = next(r for r in group_a if r.rider_id == "2")
        assert guest_result.guest is True
        club_result = next(r for r in group_a if r.rider_id == "1")
        assert club_result.guest is False


class TestRaceEventPenalty:
    """Tests for race event penalty handling."""

    def test_race_penalty_applied(self):
        """Test race event penalty is applied when configured."""
        from src.models.tour import Course, Stage

        rider = Rider(name="Test Rider", zwiftpower_id="1", handicap_group="A1")
        registry = RiderRegistry(riders=[rider])

        # Create a stage with race events allowed and 60s penalty
        stage = Stage(
            number="1",
            name="Test Stage",
            courses=[
                Course(
                    route="Test Route",
                    distance_km=20.0,
                    elevation_m=100,
                    event_ids=["race123"],
                    allow_race_events=True,
                    race_event_penalty_seconds=60,
                    event_names={"race123": "Tour de Zwift Stage 1 - Race"},
                )
            ],
            start_datetime=datetime(2026, 1, 5, 17, 0),
            end_datetime=datetime(2026, 1, 12, 16, 59),
        )

        race_results = [
            RaceResult(
                rider_id="1",
                rider_name="Test Rider",
                stage_number="1",
                event_id="race123",
                event_name="Tour de Zwift Stage 1 - Race",
                raw_time_seconds=2400,
                finish_position=1,
                timestamp=datetime(2026, 1, 6, 18, 0, 0),
            ),
        ]

        group_a, _, _ = process_stage_results(
            race_results,
            registry,
            stage_number="1",
            stage=stage,
        )

        assert len(group_a) == 1
        assert group_a[0].penalty_seconds == 60
        assert "Race event" in group_a[0].penalty_reason

    def test_race_penalty_combined_with_time_penalty(self):
        """Test race penalty is combined with time-based penalty."""
        from src.models.penalty import PenaltyEvent
        from src.models.tour import Course, Stage

        rider = Rider(name="Test Rider", zwiftpower_id="1", handicap_group="A1")
        registry = RiderRegistry(riders=[rider])

        # Create a stage with both race penalty and time penalty
        stage = Stage(
            number="1",
            name="Test Stage",
            courses=[
                Course(
                    route="Test Route",
                    distance_km=20.0,
                    elevation_m=100,
                    event_ids=["race123"],
                    penalty_events=[
                        PenaltyEvent(
                            event_time_utc=datetime(2026, 1, 5, 17, 0).time(),
                            day_of_week=0,  # Monday
                            penalty_seconds=60,
                            description="Monday 5pm",
                        )
                    ],
                    allow_race_events=True,
                    race_event_penalty_seconds=60,
                    event_names={"race123": "Tour de Zwift Stage 1 - Race"},
                )
            ],
            start_datetime=datetime(2026, 1, 5, 17, 0),
            end_datetime=datetime(2026, 1, 12, 16, 59),
        )

        race_results = [
            RaceResult(
                rider_id="1",
                rider_name="Test Rider",
                stage_number="1",
                event_id="race123",
                event_name="Tour de Zwift Stage 1 - Race",
                raw_time_seconds=2400,
                finish_position=1,
                timestamp=datetime(2026, 1, 5, 17, 0, 0),  # Monday 5pm
            ),
        ]

        group_a, _, _ = process_stage_results(
            race_results,
            registry,
            stage_number="1",
            stage=stage,
        )

        assert len(group_a) == 1
        # Should have both penalties: 60s time penalty + 60s race penalty = 120s
        assert group_a[0].penalty_seconds == 120
        assert "Monday" in group_a[0].penalty_reason
        assert "Race event" in group_a[0].penalty_reason

    def test_no_race_penalty_for_ride_events(self):
        """Test no race penalty is applied for ride (non-race) events."""
        from src.models.tour import Course, Stage

        rider = Rider(name="Test Rider", zwiftpower_id="1", handicap_group="A1")
        registry = RiderRegistry(riders=[rider])

        stage = Stage(
            number="1",
            name="Test Stage",
            courses=[
                Course(
                    route="Test Route",
                    distance_km=20.0,
                    elevation_m=100,
                    event_ids=["ride123"],
                    allow_race_events=True,
                    race_event_penalty_seconds=60,
                    event_names={"ride123": "Tour de Zwift Stage 1 - Group Ride"},
                )
            ],
            start_datetime=datetime(2026, 1, 5, 17, 0),
            end_datetime=datetime(2026, 1, 12, 16, 59),
        )

        race_results = [
            RaceResult(
                rider_id="1",
                rider_name="Test Rider",
                stage_number="1",
                event_id="ride123",
                event_name="Tour de Zwift Stage 1 - Group Ride",
                raw_time_seconds=2400,
                finish_position=1,
                timestamp=datetime(2026, 1, 6, 18, 0, 0),
            ),
        ]

        group_a, _, _ = process_stage_results(
            race_results,
            registry,
            stage_number="1",
            stage=stage,
        )

        assert len(group_a) == 1
        # No race penalty for ride events
        assert group_a[0].penalty_seconds == 0


class TestRaceEventExclusion:
    """Tests for race event exclusion (Stages 2-6)."""

    def test_race_events_excluded_when_not_allowed(self):
        """Test race events are excluded when allow_race_events=False."""
        from src.models.tour import Course, Stage

        rider = Rider(name="Test Rider", zwiftpower_id="1", handicap_group="A1")
        registry = RiderRegistry(riders=[rider])

        # Stage 2+ configuration: races not allowed
        stage = Stage(
            number="2",
            name="Test Stage",
            courses=[
                Course(
                    route="Test Route",
                    distance_km=20.0,
                    elevation_m=100,
                    event_ids=["race123", "ride456"],
                    allow_race_events=False,  # Races not allowed
                    event_names={
                        "race123": "Tour de Zwift Stage 2 - Race",
                        "ride456": "Tour de Zwift Stage 2 - Group Ride",
                    },
                )
            ],
            start_datetime=datetime(2026, 1, 12, 17, 0),
            end_datetime=datetime(2026, 1, 19, 16, 59),
        )

        race_results = [
            # Race event - should be excluded
            RaceResult(
                rider_id="1",
                rider_name="Test Rider",
                stage_number="2",
                event_id="race123",
                event_name="Tour de Zwift Stage 2 - Race",
                raw_time_seconds=2300,  # Faster time
                finish_position=1,
                timestamp=datetime(2026, 1, 13, 18, 0, 0),
            ),
            # Ride event - should be included
            RaceResult(
                rider_id="1",
                rider_name="Test Rider",
                stage_number="2",
                event_id="ride456",
                event_name="Tour de Zwift Stage 2 - Group Ride",
                raw_time_seconds=2400,  # Slower time
                finish_position=1,
                timestamp=datetime(2026, 1, 13, 19, 0, 0),
            ),
        ]

        group_a, _, _ = process_stage_results(
            race_results,
            registry,
            stage_number="2",
            stage=stage,
        )

        # Only the ride event should be in results
        assert len(group_a) == 1
        assert group_a[0].event_id == "ride456"
        assert group_a[0].raw_time_seconds == 2400

    def test_multiple_riders_some_race_some_ride(self):
        """Test some riders do race (excluded) while others do ride (included)."""
        from src.models.tour import Course, Stage

        riders = [
            Rider(name="Rider A", zwiftpower_id="1", handicap_group="A1"),
            Rider(name="Rider B", zwiftpower_id="2", handicap_group="A2"),
        ]
        registry = RiderRegistry(riders=riders)

        stage = Stage(
            number="2",
            name="Test Stage",
            courses=[
                Course(
                    route="Test Route",
                    distance_km=20.0,
                    elevation_m=100,
                    event_ids=["race123", "ride456"],
                    allow_race_events=False,
                    event_names={
                        "race123": "Stage 2 - Race",
                        "ride456": "Stage 2 - Group Ride",
                    },
                )
            ],
            start_datetime=datetime(2026, 1, 12, 17, 0),
            end_datetime=datetime(2026, 1, 19, 16, 59),
        )

        race_results = [
            # Rider A did race - excluded
            RaceResult(
                rider_id="1",
                rider_name="Rider A",
                stage_number="2",
                event_id="race123",
                event_name="Stage 2 - Race",
                raw_time_seconds=2300,
                finish_position=1,
                timestamp=datetime(2026, 1, 13, 18, 0, 0),
            ),
            # Rider B did ride - included
            RaceResult(
                rider_id="2",
                rider_name="Rider B",
                stage_number="2",
                event_id="ride456",
                event_name="Stage 2 - Group Ride",
                raw_time_seconds=2400,
                finish_position=1,
                timestamp=datetime(2026, 1, 13, 19, 0, 0),
            ),
        ]

        group_a, _, _ = process_stage_results(
            race_results,
            registry,
            stage_number="2",
            stage=stage,
        )

        # Only Rider B should have results
        assert len(group_a) == 1
        assert group_a[0].rider_id == "2"
