"""Output generation for stage results and GC standings."""

import json
from datetime import datetime
from pathlib import Path

from src.models.result import StageResult
from src.models.standings import GCStandings, TourStandings
from src.models.tour import TourConfig


def generate_stage_output(
    stage_number: int,
    group_a_results: list[StageResult],
    group_b_results: list[StageResult],
    tour_config: TourConfig,
    output_dir: str | Path,
) -> Path:
    """
    Generate JSON output file for a stage.

    Args:
        stage_number: Stage number
        group_a_results: Group A results
        group_b_results: Group B results
        tour_config: Tour configuration
        output_dir: Output directory

    Returns:
        Path to generated JSON file
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stage = tour_config.get_stage(stage_number)

    output_data = {
        "stage_number": stage_number,
        "stage_name": stage.name if stage else f"Stage {stage_number}",
        "route": stage.route if stage else "",
        "distance_km": stage.distance_km if stage else 0,
        "elevation_m": stage.elevation_m if stage else 0,
        "is_provisional": any(
            r.is_provisional for r in group_a_results + group_b_results
        ),
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        "group_a": {
            "results": [r.model_dump(mode="json") for r in group_a_results],
            "total_riders": len(group_a_results),
        },
        "group_b": {
            "results": [r.model_dump(mode="json") for r in group_b_results],
            "total_riders": len(group_b_results),
        },
    }

    output_file = output_dir / f"stage_{stage_number}.json"
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, default=str)

    return output_file


def generate_gc_output(
    tour_standings: TourStandings,
    tour_config: TourConfig,
    output_dir: str | Path,
) -> Path:
    """
    Generate JSON output file for GC standings.

    Args:
        tour_standings: Current tour standings
        tour_config: Tour configuration
        output_dir: Output directory

    Returns:
        Path to generated JSON file
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_data = {
        "tour_name": tour_config.name,
        "current_stage": tour_standings.current_stage,
        "is_provisional": tour_standings.is_provisional,
        "last_updated": tour_standings.last_updated,
        "stages": [
            {
                "number": s.number,
                "name": s.name,
                "route": s.route,
                "is_complete": s.is_complete,
                "is_active": s.is_active,
            }
            for s in tour_config.stages
        ],
        "group_a": _gc_standings_to_dict(tour_standings.group_a),
        "group_b": _gc_standings_to_dict(tour_standings.group_b),
    }

    output_file = output_dir / "gc_standings.json"
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, default=str)

    return output_file


def _gc_standings_to_dict(standings: GCStandings) -> dict:
    """Convert GC standings to dictionary for JSON output."""
    return {
        "race_group": standings.race_group,
        "total_stages": standings.total_stages,
        "completed_stages": standings.completed_stages,
        "is_provisional": standings.is_provisional,
        "standings": [
            {
                "position": s.position,
                "rider_name": s.rider_name,
                "handicap_group": s.handicap_group,
                "total_time": s.total_time_display,
                "total_time_seconds": s.total_adjusted_time_seconds,
                "gap": s.gap_display,
                "gap_seconds": s.gap_to_leader,
                "stages_completed": s.stages_completed,
                "stage_times": {
                    str(k): s.get_stage_time_display(k)
                    for k in range(1, standings.total_stages + 1)
                },
            }
            for s in standings.standings
        ],
    }


def generate_all_output(
    stage_results: dict[int, tuple[list[StageResult], list[StageResult]]],
    tour_standings: TourStandings,
    tour_config: TourConfig,
    output_dir: str | Path,
) -> list[Path]:
    """
    Generate all output files (stage results + GC).

    Args:
        stage_results: Dict mapping stage number to (group_a, group_b) results
        tour_standings: Current tour standings
        tour_config: Tour configuration
        output_dir: Output directory

    Returns:
        List of generated file paths
    """
    output_files: list[Path] = []

    # Generate stage files
    for stage_num, (group_a, group_b) in stage_results.items():
        output_file = generate_stage_output(
            stage_num,
            group_a,
            group_b,
            tour_config,
            output_dir,
        )
        output_files.append(output_file)

    # Generate GC file
    gc_file = generate_gc_output(tour_standings, tour_config, output_dir)
    output_files.append(gc_file)

    return output_files
