"""GC standings calculation."""

from src.models.result import StageResult
from src.models.standings import GCStanding, GCStandings, TourStandings


def calculate_gc_standings(
    all_stage_results: dict[int, list[StageResult]],
    race_group: str,
    completed_stages: int,
    is_provisional: bool = True,
) -> GCStandings:
    """
    Calculate GC standings from all stage results.

    Riders must complete ALL stages to appear in GC standings.

    Args:
        all_stage_results: Dict mapping stage number to list of stage results
        race_group: Race group ("A" or "B")
        completed_stages: Number of stages that have been completed
        is_provisional: Whether the tour is still in progress

    Returns:
        GCStandings for the race group
    """
    # Collect all riders and their results
    rider_results: dict[str, dict[int, StageResult]] = {}

    for stage_num, results in all_stage_results.items():
        for result in results:
            if result.race_group != race_group:
                continue

            if result.rider_id not in rider_results:
                rider_results[result.rider_id] = {}
            rider_results[result.rider_id][stage_num] = result

    # Build GC standings - only include riders who completed ALL stages
    standings: list[GCStanding] = []

    for rider_id, stage_results in rider_results.items():
        # Check if rider completed all stages (up to completed_stages)
        required_stages = set(range(1, completed_stages + 1))
        completed = set(stage_results.keys())

        if not required_stages.issubset(completed):
            # Rider hasn't completed all required stages - exclude from GC
            continue

        # Get rider info from first result
        first_result = next(iter(stage_results.values()))

        # Calculate total time from completed stages
        total_time = sum(
            stage_results[s].adjusted_time_seconds
            for s in required_stages
            if s in stage_results
        )

        # Build stage times dict
        stage_times = {
            stage: result.adjusted_time_seconds
            for stage, result in stage_results.items()
        }

        standing = GCStanding(
            rider_name=first_result.rider_name,
            rider_id=rider_id,
            race_group=race_group,
            handicap_group=first_result.handicap_group,
            total_adjusted_time_seconds=total_time,
            stages_completed=len(stage_results),
            stage_times=stage_times,
            position=0,  # Will be set after sorting
            gap_to_leader=0,  # Will be set after sorting
            is_provisional=is_provisional,
        )
        standings.append(standing)

    # Sort by total time and calculate positions
    standings = _calculate_gc_positions_and_gaps(standings)

    return GCStandings(
        race_group=race_group,
        standings=standings,
        completed_stages=completed_stages,
        is_provisional=is_provisional,
    )


def _calculate_gc_positions_and_gaps(
    standings: list[GCStanding],
) -> list[GCStanding]:
    """
    Sort GC standings by total time and calculate positions and gaps.

    Args:
        standings: List of GC standings to process

    Returns:
        Sorted list with positions and gaps calculated
    """
    if not standings:
        return standings

    # Sort by total adjusted time
    sorted_standings = sorted(
        standings,
        key=lambda s: s.total_adjusted_time_seconds,
    )

    leader_time = sorted_standings[0].total_adjusted_time_seconds

    for i, standing in enumerate(sorted_standings):
        standing.position = i + 1
        standing.gap_to_leader = standing.total_adjusted_time_seconds - leader_time

    return sorted_standings


def build_tour_standings(
    group_a_results: dict[int, list[StageResult]],
    group_b_results: dict[int, list[StageResult]],
    completed_stages: int,
    current_stage: int = 1,
    last_updated: str | None = None,
    is_stage_in_progress: bool = False,
) -> TourStandings:
    """
    Build complete tour standings for both groups.

    Args:
        group_a_results: Stage results for Group A
        group_b_results: Stage results for Group B
        completed_stages: Number of completed stages
        current_stage: Current stage number
        last_updated: Timestamp of last update
        is_stage_in_progress: Whether a stage is currently active

    Returns:
        TourStandings with both groups
    """
    is_provisional = completed_stages < 6

    group_a = calculate_gc_standings(
        group_a_results,
        "A",
        completed_stages,
        is_provisional,
    )
    group_a.last_updated = last_updated

    group_b = calculate_gc_standings(
        group_b_results,
        "B",
        completed_stages,
        is_provisional,
    )
    group_b.last_updated = last_updated

    return TourStandings(
        group_a=group_a,
        group_b=group_b,
        last_updated=last_updated,
        current_stage=current_stage,
        is_stage_in_progress=is_stage_in_progress,
    )
