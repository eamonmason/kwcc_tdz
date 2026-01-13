"""GC standings calculation."""

from src.models.result import StageResult
from src.models.standings import GCStanding, GCStandings, TourStandings


def calculate_gc_standings(
    all_stage_results: dict[int, list[StageResult]],
    race_group: str,
    completed_stages: int,
    is_provisional: bool = True,
    include_guests: bool = False,
    target_stage: int | None = None,
    include_dns: bool = False,
) -> GCStandings:
    """
    Calculate GC standings from all stage results.

    Riders must complete ALL stages to appear in GC standings.

    Args:
        all_stage_results: Dict mapping stage number to list of stage results
        race_group: Race group ("A" or "B")
        completed_stages: Number of stages that have been completed
        is_provisional: Whether the tour is still in progress
        include_guests: Whether to include guest riders in standings (default: False)
        target_stage: Calculate GC up to this stage (defaults to completed_stages)
        include_dns: Include DNS riders who completed all prior stages (default: False)

    Returns:
        GCStandings for the race group
    """
    # Default target_stage to completed_stages
    if target_stage is None:
        target_stage = completed_stages

    # Collect all riders and their results
    rider_results: dict[str, dict[int, StageResult]] = {}

    for stage_num, results in all_stage_results.items():
        # Only consider stages up to target_stage
        if stage_num > target_stage:
            continue

        for result in results:
            # Skip race_group filter for Women's GC (women can be in A or B groups)
            if race_group != "Women" and result.race_group != race_group:
                continue

            # Exclude uncategorized riders from GC standings
            if result.handicap_group is None:
                continue

            # Exclude guest riders from GC standings (unless explicitly included)
            if result.guest and not include_guests:
                continue

            if result.rider_id not in rider_results:
                rider_results[result.rider_id] = {}
            rider_results[result.rider_id][stage_num] = result

    # Build GC standings - include riders who completed ALL stages up to target_stage
    standings: list[GCStanding] = []
    dns_standings: list[
        GCStanding
    ] = []  # Riders who completed prior stages but not target

    for rider_id, stage_results in rider_results.items():
        # Check if rider completed all stages (up to target_stage)
        required_stages = set(range(1, target_stage + 1))
        completed = set(stage_results.keys())

        # Get rider info from first result
        first_result = next(iter(stage_results.values()))

        if not required_stages.issubset(completed):
            # Check if rider completed all PRIOR stages but not target stage
            # Only include DNS riders if explicitly requested
            if include_dns:
                prior_stages = set(range(1, target_stage))
                if (
                    prior_stages
                    and prior_stages.issubset(completed)
                    and target_stage not in completed
                ):
                    # DNS for target stage - include at bottom
                    # Sum stage_time_seconds (raw + penalty), add handicap ONCE
                    total_stage_time = sum(
                        stage_results[s].stage_time_seconds
                        for s in prior_stages
                        if s in stage_results
                    )
                    handicap_seconds = first_result.handicap_seconds
                    total_time = total_stage_time + handicap_seconds

                    # Build stage times dict (store stage_time, not adjusted_time)
                    stage_times = {
                        stage: result.stage_time_seconds
                        for stage, result in stage_results.items()
                    }

                    # Build stage event IDs dict for ZwiftPower links
                    stage_event_ids = {
                        stage: result.event_id
                        for stage, result in stage_results.items()
                        if result.event_id
                    }

                    standing = GCStanding(
                        rider_name=first_result.rider_name,
                        rider_id=rider_id,
                        race_group=race_group,
                        handicap_group=first_result.handicap_group,
                        total_adjusted_time_seconds=total_time,
                        stages_completed=len(stage_results),
                        stage_times=stage_times,
                        stage_event_ids=stage_event_ids,
                        position=0,  # Will be set after sorting
                        gap_to_leader=0,  # Will be set after sorting
                        is_provisional=is_provisional,
                        guest=first_result.guest,
                        is_dns=True,
                    )
                    dns_standings.append(standing)
            continue

        # Calculate total time from completed stages
        # IMPORTANT: Sum stage_time_seconds (raw + penalty), NOT adjusted_time_seconds
        # Handicap is applied ONCE to the GC total, not per-stage
        total_stage_time = sum(
            stage_results[s].stage_time_seconds
            for s in required_stages
            if s in stage_results
        )

        # Add handicap ONCE to the total GC time
        handicap_seconds = first_result.handicap_seconds
        total_time = total_stage_time + handicap_seconds

        # Build stage times dict (store stage_time, not adjusted_time)
        stage_times = {
            stage: result.stage_time_seconds for stage, result in stage_results.items()
        }

        # Build stage event IDs dict for ZwiftPower links
        stage_event_ids = {
            stage: result.event_id
            for stage, result in stage_results.items()
            if result.event_id
        }

        standing = GCStanding(
            rider_name=first_result.rider_name,
            rider_id=rider_id,
            race_group=race_group,
            handicap_group=first_result.handicap_group,
            total_adjusted_time_seconds=total_time,
            stages_completed=len(stage_results),
            stage_times=stage_times,
            stage_event_ids=stage_event_ids,
            position=0,  # Will be set after sorting
            gap_to_leader=0,  # Will be set after sorting
            is_provisional=is_provisional,
            guest=first_result.guest,
        )
        standings.append(standing)

    # Sort by total time and calculate positions
    standings = _calculate_gc_positions_and_gaps(standings)

    # Add DNS riders at the bottom (no positions/gaps calculated)
    standings.extend(dns_standings)

    return GCStandings(
        race_group=race_group,
        standings=standings,
        completed_stages=target_stage,
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


def calculate_women_gc_standings(
    group_a_results: dict[int, list[StageResult]],
    group_b_results: dict[int, list[StageResult]],
    completed_stages: int,
    is_provisional: bool = True,
    include_guests: bool = False,
) -> GCStandings:
    """
    Calculate women's GC standings from all groups combined.

    Args:
        group_a_results: Stage results for Group A
        group_b_results: Stage results for Group B
        completed_stages: Number of completed stages
        is_provisional: Whether the tour is still in progress
        include_guests: Whether to include guest riders in standings (default: False)

    Returns:
        GCStandings for all women combined
    """
    # Combine all results and filter for women
    all_results: dict[int, list[StageResult]] = {}
    for stage_num in range(1, completed_stages + 1):
        stage_results = []
        if stage_num in group_a_results:
            stage_results.extend(group_a_results[stage_num])
        if stage_num in group_b_results:
            stage_results.extend(group_b_results[stage_num])

        # Filter for women only
        women_results = [r for r in stage_results if r.gender == "F"]
        if women_results:
            all_results[stage_num] = women_results

    # Calculate standings for women (use "Women" as race_group label)
    return calculate_gc_standings(
        all_results,
        "Women",
        completed_stages,
        is_provisional,
        include_guests,
    )


def build_tour_standings(
    group_a_results: dict[int, list[StageResult]],
    group_b_results: dict[int, list[StageResult]],
    completed_stages: int,
    current_stage: int = 1,
    last_updated: str | None = None,
    is_stage_in_progress: bool = False,
    include_guests: bool = False,
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
        include_guests: Whether to include guest riders in standings (default: False)

    Returns:
        TourStandings with both groups
    """
    is_provisional = completed_stages < 6

    group_a = calculate_gc_standings(
        group_a_results,
        "A",
        completed_stages,
        is_provisional,
        include_guests,
    )
    group_a.last_updated = last_updated

    group_b = calculate_gc_standings(
        group_b_results,
        "B",
        completed_stages,
        is_provisional,
        include_guests,
    )
    group_b.last_updated = last_updated

    return TourStandings(
        group_a=group_a,
        group_b=group_b,
        last_updated=last_updated,
        current_stage=current_stage,
        is_stage_in_progress=is_stage_in_progress,
    )
