"""Tests for GC standings calculation."""

from src.models.result import StageResult
from src.processor.gc_standings import (
    build_tour_standings,
    calculate_gc_standings,
)


def create_stage_result(
    rider_name: str,
    rider_id: str,
    stage_number: int,
    race_group: str,
    handicap_group: str,
    adjusted_time: int,
    guest: bool = False,
) -> StageResult:
    """Helper to create stage results for testing."""
    # Derive raw_time and handicap from adjusted_time for simplicity
    return StageResult(
        rider_name=rider_name,
        rider_id=rider_id,
        stage_number=stage_number,
        race_group=race_group,
        handicap_group=handicap_group,
        raw_time_seconds=adjusted_time,
        handicap_seconds=0,
        position=1,
        raw_position=1,
        guest=guest,
    )


class TestCalculateGCStandings:
    """Tests for calculate_gc_standings function."""

    def test_single_rider_single_stage(self):
        """Test GC with one rider completing one stage."""
        stage_results = {
            1: [
                create_stage_result("Tom Kennett", "1", 1, "A", "A1", 3000),
            ]
        }

        gc = calculate_gc_standings(stage_results, race_group="A", completed_stages=1)

        assert len(gc.standings) == 1
        assert gc.standings[0].rider_name == "Tom Kennett"
        assert gc.standings[0].total_adjusted_time_seconds == 3000
        assert gc.standings[0].position == 1

    def test_multiple_riders_sorted_by_time(self):
        """Test riders are sorted by total adjusted time."""
        stage_results = {
            1: [
                create_stage_result("Fast Rider", "1", 1, "A", "A1", 2800),
                create_stage_result("Slow Rider", "2", 1, "A", "A2", 3200),
                create_stage_result("Mid Rider", "3", 1, "A", "A3", 3000),
            ]
        }

        gc = calculate_gc_standings(stage_results, race_group="A", completed_stages=1)

        assert len(gc.standings) == 3
        assert gc.standings[0].rider_name == "Fast Rider"
        assert gc.standings[0].position == 1
        assert gc.standings[1].rider_name == "Mid Rider"
        assert gc.standings[1].position == 2
        assert gc.standings[2].rider_name == "Slow Rider"
        assert gc.standings[2].position == 3

    def test_gaps_calculated_correctly(self):
        """Test gap to leader is calculated correctly."""
        stage_results = {
            1: [
                create_stage_result("Leader", "1", 1, "A", "A1", 3000),
                create_stage_result("Follower", "2", 1, "A", "A2", 3120),
            ]
        }

        gc = calculate_gc_standings(stage_results, race_group="A", completed_stages=1)

        assert gc.standings[0].gap_to_leader == 0
        assert gc.standings[1].gap_to_leader == 120  # 2 minutes behind

    def test_multiple_stages_summed(self):
        """Test total time is sum of all stage times."""
        stage_results = {
            1: [
                create_stage_result("Rider A", "1", 1, "A", "A1", 3000),
                create_stage_result("Rider B", "2", 1, "A", "A2", 3100),
            ],
            2: [
                create_stage_result("Rider A", "1", 2, "A", "A1", 2900),
                create_stage_result("Rider B", "2", 2, "A", "A2", 2800),
            ],
        }

        gc = calculate_gc_standings(stage_results, race_group="A", completed_stages=2)

        # Rider A: 3000 + 2900 = 5900
        # Rider B: 3100 + 2800 = 5900
        rider_a = next(s for s in gc.standings if s.rider_id == "1")
        rider_b = next(s for s in gc.standings if s.rider_id == "2")

        assert rider_a.total_adjusted_time_seconds == 5900
        assert rider_b.total_adjusted_time_seconds == 5900

    def test_rider_must_complete_all_stages(self):
        """Test rider excluded if they haven't completed all stages."""
        stage_results = {
            1: [
                create_stage_result("Complete Rider", "1", 1, "A", "A1", 3000),
                create_stage_result("Incomplete Rider", "2", 1, "A", "A2", 3100),
            ],
            2: [
                create_stage_result("Complete Rider", "1", 2, "A", "A1", 2900),
                # Rider 2 did not complete stage 2
            ],
        }

        gc = calculate_gc_standings(stage_results, race_group="A", completed_stages=2)

        # Only Complete Rider should be in GC
        assert len(gc.standings) == 1
        assert gc.standings[0].rider_name == "Complete Rider"

    def test_filters_by_race_group(self):
        """Test only riders in specified race group are included."""
        stage_results = {
            1: [
                create_stage_result("Group A Rider", "1", 1, "A", "A1", 3000),
                create_stage_result("Group B Rider", "2", 1, "B", "B1", 3100),
            ]
        }

        gc_a = calculate_gc_standings(stage_results, race_group="A", completed_stages=1)
        gc_b = calculate_gc_standings(stage_results, race_group="B", completed_stages=1)

        assert len(gc_a.standings) == 1
        assert gc_a.standings[0].rider_name == "Group A Rider"

        assert len(gc_b.standings) == 1
        assert gc_b.standings[0].rider_name == "Group B Rider"

    def test_stage_times_dict_populated(self):
        """Test stage_times dict contains all stage times."""
        stage_results = {
            1: [create_stage_result("Rider", "1", 1, "A", "A1", 3000)],
            2: [create_stage_result("Rider", "1", 2, "A", "A1", 2900)],
            3: [create_stage_result("Rider", "1", 3, "A", "A1", 3100)],
        }

        gc = calculate_gc_standings(stage_results, race_group="A", completed_stages=3)

        assert len(gc.standings) == 1
        stage_times = gc.standings[0].stage_times

        assert stage_times[1] == 3000
        assert stage_times[2] == 2900
        assert stage_times[3] == 3100

    def test_provisional_flag_set(self):
        """Test provisional flag is set correctly."""
        stage_results = {1: [create_stage_result("Rider", "1", 1, "A", "A1", 3000)]}

        gc_provisional = calculate_gc_standings(
            stage_results, race_group="A", completed_stages=1, is_provisional=True
        )
        gc_final = calculate_gc_standings(
            stage_results, race_group="A", completed_stages=1, is_provisional=False
        )

        assert gc_provisional.is_provisional is True
        assert gc_provisional.standings[0].is_provisional is True

        assert gc_final.is_provisional is False
        assert gc_final.standings[0].is_provisional is False

    def test_empty_results(self):
        """Test empty results return empty standings."""
        gc = calculate_gc_standings({}, race_group="A", completed_stages=1)

        assert len(gc.standings) == 0

    def test_stages_completed_tracked(self):
        """Test stages_completed field is set."""
        stage_results = {
            1: [create_stage_result("Rider", "1", 1, "A", "A1", 3000)],
            2: [create_stage_result("Rider", "1", 2, "A", "A1", 2900)],
        }

        gc = calculate_gc_standings(stage_results, race_group="A", completed_stages=2)

        assert gc.completed_stages == 2
        assert gc.standings[0].stages_completed == 2


class TestBuildTourStandings:
    """Tests for build_tour_standings function."""

    def test_builds_both_groups(self):
        """Test tour standings includes both Group A and B."""
        group_a_results = {1: [create_stage_result("A Rider", "1", 1, "A", "A1", 3000)]}
        group_b_results = {1: [create_stage_result("B Rider", "2", 1, "B", "B1", 3200)]}

        tour = build_tour_standings(
            group_a_results,
            group_b_results,
            completed_stages=1,
        )

        assert len(tour.group_a.standings) == 1
        assert len(tour.group_b.standings) == 1
        assert tour.group_a.standings[0].rider_name == "A Rider"
        assert tour.group_b.standings[0].rider_name == "B Rider"

    def test_provisional_based_on_stages(self):
        """Test provisional flag based on completed stages."""
        group_a_results = {1: [create_stage_result("A Rider", "1", 1, "A", "A1", 3000)]}

        # Less than 6 stages = provisional
        tour_provisional = build_tour_standings(group_a_results, {}, completed_stages=3)
        assert tour_provisional.group_a.is_provisional is True

        # All 6 stages = final
        tour_final = build_tour_standings(group_a_results, {}, completed_stages=6)
        assert tour_final.group_a.is_provisional is False

    def test_last_updated_set(self):
        """Test last_updated is set on standings."""
        tour = build_tour_standings(
            {},
            {},
            completed_stages=1,
            last_updated="2026-01-06 18:00 UTC",
        )

        assert tour.last_updated == "2026-01-06 18:00 UTC"
        assert tour.group_a.last_updated == "2026-01-06 18:00 UTC"
        assert tour.group_b.last_updated == "2026-01-06 18:00 UTC"

    def test_current_stage_set(self):
        """Test current_stage is set."""
        tour = build_tour_standings(
            {},
            {},
            completed_stages=2,
            current_stage=3,
        )

        assert tour.current_stage == 3


class TestGCEdgeCases:
    """Edge case tests for GC calculation."""

    def test_rider_completes_extra_stages(self):
        """Test rider who completes more than required stages."""
        # Rider has results for stages 1, 2, 3, but only 2 are completed
        stage_results = {
            1: [create_stage_result("Eager Rider", "1", 1, "A", "A1", 3000)],
            2: [create_stage_result("Eager Rider", "1", 2, "A", "A1", 2900)],
            3: [
                create_stage_result("Eager Rider", "1", 3, "A", "A1", 3100)
            ],  # Future stage
        }

        gc = calculate_gc_standings(stage_results, race_group="A", completed_stages=2)

        # Should only count stages 1 and 2
        assert gc.standings[0].total_adjusted_time_seconds == 5900  # 3000 + 2900

    def test_tie_in_time(self):
        """Test riders with identical times."""
        stage_results = {
            1: [
                create_stage_result("Rider A", "1", 1, "A", "A1", 3000),
                create_stage_result("Rider B", "2", 1, "A", "A2", 3000),
            ]
        }

        gc = calculate_gc_standings(stage_results, race_group="A", completed_stages=1)

        # Both should be in standings with same time
        assert len(gc.standings) == 2
        assert gc.standings[0].total_adjusted_time_seconds == 3000
        assert gc.standings[1].total_adjusted_time_seconds == 3000

        # Positions should be 1 and 2 (stable sort)
        assert gc.standings[0].position == 1
        assert gc.standings[1].position == 2

    def test_rider_skips_stage_in_middle(self):
        """Test rider who skips a stage in the middle is excluded."""
        stage_results = {
            1: [create_stage_result("Skipper", "1", 1, "A", "A1", 3000)],
            # Stage 2 missing for rider
            3: [create_stage_result("Skipper", "1", 3, "A", "A1", 3100)],
        }

        gc = calculate_gc_standings(stage_results, race_group="A", completed_stages=3)

        # Rider should be excluded (missing stage 2)
        assert len(gc.standings) == 0


class TestGuestRiderGCFiltering:
    """Tests for guest rider filtering in GC standings."""

    def test_guest_rider_excluded_from_gc_by_default(self):
        """Test guest riders are excluded from GC standings by default."""
        stage_results = {
            1: [
                create_stage_result("Club Rider", "1", 1, "A", "A1", 3000, guest=False),
                create_stage_result("Guest Rider", "2", 1, "A", "A2", 2900, guest=True),
            ]
        }

        gc = calculate_gc_standings(
            stage_results, race_group="A", completed_stages=1, include_guests=False
        )

        # Only club rider should be in GC
        assert len(gc.standings) == 1
        assert gc.standings[0].rider_name == "Club Rider"

    def test_guest_rider_included_when_flag_set(self):
        """Test guest riders are included when include_guests=True."""
        stage_results = {
            1: [
                create_stage_result("Club Rider", "1", 1, "A", "A1", 3000, guest=False),
                create_stage_result("Guest Rider", "2", 1, "A", "A2", 2900, guest=True),
            ]
        }

        gc = calculate_gc_standings(
            stage_results, race_group="A", completed_stages=1, include_guests=True
        )

        # Both riders should be in GC
        assert len(gc.standings) == 2
        assert gc.standings[0].rider_name == "Guest Rider"  # Faster time
        assert gc.standings[1].rider_name == "Club Rider"

    def test_guest_flag_propagated_to_gc_standing(self):
        """Test guest flag is carried through to GC standing."""
        stage_results = {
            1: [
                create_stage_result("Guest Rider", "1", 1, "A", "A1", 3000, guest=True),
            ]
        }

        gc = calculate_gc_standings(
            stage_results, race_group="A", completed_stages=1, include_guests=True
        )

        assert len(gc.standings) == 1
        assert gc.standings[0].guest is True

    def test_multiple_guest_riders_excluded(self):
        """Test multiple guest riders are all excluded by default."""
        stage_results = {
            1: [
                create_stage_result("Club Rider", "1", 1, "A", "A1", 3000, guest=False),
                create_stage_result("Guest 1", "2", 1, "A", "A2", 2900, guest=True),
                create_stage_result("Guest 2", "3", 1, "A", "A3", 2950, guest=True),
            ]
        }

        gc = calculate_gc_standings(
            stage_results, race_group="A", completed_stages=1, include_guests=False
        )

        # Only club rider should be in GC
        assert len(gc.standings) == 1
        assert gc.standings[0].rider_name == "Club Rider"

    def test_guest_rider_must_complete_all_stages_when_included(self):
        """Test guest riders must complete all stages when included in GC."""
        stage_results = {
            1: [
                create_stage_result("Guest Rider", "1", 1, "A", "A1", 3000, guest=True),
            ],
            2: [
                # Guest rider did not complete stage 2
            ],
        }

        gc = calculate_gc_standings(
            stage_results, race_group="A", completed_stages=2, include_guests=True
        )

        # Guest rider should be excluded (didn't complete all stages)
        assert len(gc.standings) == 0

    def test_build_tour_standings_respects_guest_flag(self):
        """Test build_tour_standings passes include_guests parameter."""
        group_a_results = {
            1: [
                create_stage_result("Club A", "1", 1, "A", "A1", 3000, guest=False),
                create_stage_result("Guest A", "2", 1, "A", "A2", 2900, guest=True),
            ]
        }
        group_b_results = {
            1: [
                create_stage_result("Club B", "3", 1, "B", "B1", 3200, guest=False),
                create_stage_result("Guest B", "4", 1, "B", "B2", 3100, guest=True),
            ]
        }

        # Test with guests excluded (default)
        tour_excluded = build_tour_standings(
            group_a_results,
            group_b_results,
            completed_stages=1,
            include_guests=False,
        )

        assert len(tour_excluded.group_a.standings) == 1
        assert tour_excluded.group_a.standings[0].rider_name == "Club A"
        assert len(tour_excluded.group_b.standings) == 1
        assert tour_excluded.group_b.standings[0].rider_name == "Club B"

        # Test with guests included
        tour_included = build_tour_standings(
            group_a_results,
            group_b_results,
            completed_stages=1,
            include_guests=True,
        )

        assert len(tour_included.group_a.standings) == 2
        assert len(tour_included.group_b.standings) == 2
