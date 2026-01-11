"""Handicap and penalty calculation and result processing."""

from src.models.penalty import DEFAULT_PENALTY_CONFIG, PenaltyConfig
from src.models.result import RaceResult, StageResult
from src.models.rider import Rider, RiderRegistry


def apply_handicap_and_penalty(
    race_result: RaceResult,
    rider: Rider,
    penalty_config: PenaltyConfig | None = None,
) -> StageResult:
    """
    Apply handicap and penalty adjustments to a race result.

    Args:
        race_result: Raw race result from ZwiftPower
        rider: Rider with handicap information
        penalty_config: Optional penalty configuration

    Returns:
        StageResult with handicap and penalty applied
    """
    penalty_seconds = 0
    penalty_reason = ""

    if penalty_config and race_result.timestamp:
        penalty_seconds = penalty_config.get_penalty(
            race_result.timestamp,
            race_result.stage_number,
        )
        if penalty_seconds > 0:
            # Determine penalty reason from event time
            event_hour = race_result.timestamp.hour
            day_name = race_result.timestamp.strftime("%A")
            penalty_reason = f"{day_name} {event_hour}:00 UTC event"

    return StageResult(
        rider_name=rider.name,
        rider_id=rider.zwiftpower_id,
        stage_number=race_result.stage_number,
        race_group=rider.race_group,
        handicap_group=rider.handicap_group,
        raw_time_seconds=race_result.raw_time_seconds,
        handicap_seconds=rider.handicap_seconds,
        penalty_seconds=penalty_seconds,
        penalty_reason=penalty_reason,
        position=0,  # Will be calculated after sorting
        raw_position=race_result.finish_position,
        gap_to_leader=0,  # Will be calculated after sorting
        is_provisional=False,
        event_id=race_result.event_id,
        timestamp=race_result.timestamp,
    )


# Keep backwards compatible alias
def apply_handicap(
    race_result: RaceResult,
    rider: Rider,
) -> StageResult:
    """Apply handicap adjustment to a race result (no penalties)."""
    return apply_handicap_and_penalty(race_result, rider, penalty_config=None)


def process_stage_results(
    race_results: list[RaceResult],
    rider_registry: RiderRegistry,
    stage_number: int,  # noqa: ARG001
    is_provisional: bool = False,
    penalty_config: PenaltyConfig | None = None,
) -> tuple[list[StageResult], list[StageResult]]:
    """
    Process race results into stage results with handicaps and penalties.

    Args:
        race_results: Raw race results from ZwiftPower
        rider_registry: Registry of all KWCC riders
        stage_number: Stage number being processed
        is_provisional: Whether results are still provisional
        penalty_config: Optional penalty configuration (defaults to standard)

    Returns:
        Tuple of (group_a_results, group_b_results), sorted by adjusted time
    """
    # Use default penalty config if not provided
    if penalty_config is None:
        penalty_config = DEFAULT_PENALTY_CONFIG

    # Filter and process only KWCC riders
    group_a_results: list[StageResult] = []
    group_b_results: list[StageResult] = []

    for race_result in race_results:
        rider = rider_registry.get_by_zwiftpower_id(race_result.rider_id)
        if not rider:
            continue

        stage_result = apply_handicap_and_penalty(race_result, rider, penalty_config)
        stage_result.is_provisional = is_provisional

        if rider.race_group == "A":
            group_a_results.append(stage_result)
        else:
            group_b_results.append(stage_result)

    # Sort by adjusted time and calculate positions/gaps
    group_a_results = _calculate_positions_and_gaps(group_a_results)
    group_b_results = _calculate_positions_and_gaps(group_b_results)

    return group_a_results, group_b_results


def _calculate_positions_and_gaps(results: list[StageResult]) -> list[StageResult]:
    """
    Sort results by adjusted time and calculate positions and gaps.

    Args:
        results: List of stage results to process

    Returns:
        Sorted list with positions and gaps calculated
    """
    if not results:
        return results

    # Sort by adjusted time (includes raw time + handicap + penalty)
    sorted_results = sorted(results, key=lambda r: r.adjusted_time_seconds)

    leader_time = sorted_results[0].adjusted_time_seconds

    for i, result in enumerate(sorted_results):
        result.position = i + 1
        result.gap_to_leader = result.adjusted_time_seconds - leader_time

    return sorted_results


def get_best_result_per_rider(
    results: list[StageResult],
) -> list[StageResult]:
    """
    For riders with multiple results in a stage, keep only their best result.

    This handles cases where a rider might have done multiple races
    during the stage week.

    Args:
        results: All stage results

    Returns:
        List with only the best result per rider
    """
    best_results: dict[str, StageResult] = {}

    for result in results:
        rider_id = result.rider_id
        if (
            rider_id not in best_results
            or result.adjusted_time_seconds
            < best_results[rider_id].adjusted_time_seconds
        ):
            best_results[rider_id] = result

    return list(best_results.values())
