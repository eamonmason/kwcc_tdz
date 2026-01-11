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
            stage_number=1,
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
            stage_number=1,
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
            stage_number=1,
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
            stage_number=1,
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
            stage_number=3,
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
        assert stage_result.stage_number == 3
        assert stage_result.raw_position == 5


class TestApplyHandicapAndPenalty:
    """Tests for apply_handicap_and_penalty function."""

    def test_no_penalty_when_config_none(self):
        """Test no penalty applied when config is None."""
        rider = Rider(name="Test", zwiftpower_id="1", handicap_group="A1")
        race_result = RaceResult(
            rider_id="1",
            rider_name="Test",
            stage_number=1,
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
            stage_number=1,
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
            stage_number=1,
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
            stage_number=1,
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

        group_a, group_b = process_stage_results(
            sample_race_results,
            registry,
            stage_number=1,
        )

        assert len(group_a) == 3  # Tom (A1), Chris (A2), Eamon (A3)
        assert len(group_b) == 2  # Adam (B1), James (B4)

        assert all(r.race_group == "A" for r in group_a)
        assert all(r.race_group == "B" for r in group_b)

    def test_process_calculates_positions(self, sample_riders, sample_race_results):
        """Test positions are calculated correctly after handicap."""
        registry = RiderRegistry(riders=sample_riders)

        group_a, _ = process_stage_results(
            sample_race_results,
            registry,
            stage_number=1,
        )

        # Results sorted by adjusted time
        assert group_a[0].position == 1
        assert group_a[1].position == 2
        assert group_a[2].position == 3

    def test_process_calculates_gaps(self, sample_riders, sample_race_results):
        """Test gaps to leader are calculated correctly."""
        registry = RiderRegistry(riders=sample_riders)

        group_a, _ = process_stage_results(
            sample_race_results,
            registry,
            stage_number=1,
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
                stage_number=1,
                event_id="12345",
                raw_time_seconds=2400,
                finish_position=1,
                timestamp=datetime(2026, 1, 5, 17, 0, 0),  # Monday 5pm
            ),
        ]

        group_a, _ = process_stage_results(
            race_results,
            registry,
            stage_number=1,
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
                stage_number=1,
                event_id="12345",
                raw_time_seconds=2400,
                finish_position=1,
                timestamp=datetime(2026, 1, 6, 18, 0, 0),
            ),
            RaceResult(
                rider_id="unknown123",  # Unknown rider
                rider_name="Unknown Person",
                stage_number=1,
                event_id="12345",
                raw_time_seconds=2300,
                finish_position=2,
                timestamp=datetime(2026, 1, 6, 18, 0, 0),
            ),
        ]

        group_a, group_b = process_stage_results(
            race_results,
            registry,
            stage_number=1,
        )

        total_results = len(group_a) + len(group_b)
        assert total_results == 1  # Only known rider

    def test_process_sets_provisional_flag(self, sample_riders, sample_race_results):
        """Test provisional flag is set on results."""
        registry = RiderRegistry(riders=sample_riders)

        group_a, group_b = process_stage_results(
            sample_race_results,
            registry,
            stage_number=1,
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
                stage_number=1,
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
                stage_number=1,
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
                stage_number=1,
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
                stage_number=1,
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

    def test_considers_adjusted_time(self):
        """Test best result is based on adjusted time, not raw time."""
        results = [
            # Faster raw time but with penalty = worse adjusted
            StageResult(
                rider_name="Rider 1",
                rider_id="1",
                stage_number=1,
                race_group="A",
                handicap_group="A1",
                raw_time_seconds=2300,  # 2300 + 600 + 300 = 3200
                handicap_seconds=600,
                penalty_seconds=300,
                position=1,
                raw_position=1,
            ),
            # Slower raw time but no penalty = better adjusted
            StageResult(
                rider_name="Rider 1",
                rider_id="1",
                stage_number=1,
                race_group="A",
                handicap_group="A1",
                raw_time_seconds=2400,  # 2400 + 600 + 0 = 3000
                handicap_seconds=600,
                penalty_seconds=0,
                position=1,
                raw_position=1,
            ),
        ]

        best = get_best_result_per_rider(results)

        assert len(best) == 1
        assert best[0].raw_time_seconds == 2400  # Better adjusted time

    def test_empty_list(self):
        """Test empty list returns empty list."""
        assert get_best_result_per_rider([]) == []
