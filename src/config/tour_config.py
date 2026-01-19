"""Tour configuration and event ID management."""

import json
from pathlib import Path

from src.models.tour import TOUR_STAGES, Stage, TourConfig


def load_event_ids(json_path: str | Path) -> dict[str, list[str]]:
    """
    Load ZwiftPower event IDs from JSON file.

    Args:
        json_path: Path to event IDs JSON file

    Returns:
        Dict mapping stage number (as string) to list of event IDs
    """
    json_path = Path(json_path)
    if not json_path.exists():
        return {}

    with json_path.open(encoding="utf-8") as f:
        data = json.load(f)

    # Keep keys as strings (stage numbers like "1", "3.1", "3.2")
    return {str(k): v for k, v in data.items()}


def save_event_ids(event_ids: dict[str, list[str]], json_path: str | Path) -> None:
    """
    Save ZwiftPower event IDs to JSON file.

    Args:
        event_ids: Dict mapping stage number (as string) to list of event IDs
        json_path: Path to output JSON file
    """
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(event_ids, f, indent=2)


def get_tour_config(event_ids_path: str | Path | None = None) -> TourConfig:
    """
    Get tour configuration with event IDs populated.

    Args:
        event_ids_path: Optional path to event IDs JSON

    Returns:
        TourConfig with populated event IDs
    """
    # Create stages with event IDs if available
    stages: list[Stage] = []
    event_ids: dict[str, list[str]] = {}

    if event_ids_path:
        event_ids = load_event_ids(event_ids_path)

    for base_stage in TOUR_STAGES:
        stage_event_ids = event_ids.get(base_stage.number, [])
        stage = Stage(
            number=base_stage.number,
            name=base_stage.name,
            courses=base_stage.courses,
            start_datetime=base_stage.start_datetime,
            end_datetime=base_stage.end_datetime,
            event_search_patterns=base_stage.event_search_patterns,
            # Legacy fields for backwards compatibility
            route=base_stage.route,
            distance_km=base_stage.distance_km,
            elevation_m=base_stage.elevation_m,
            event_ids=stage_event_ids,
        )
        stages.append(stage)

    return TourConfig(stages=stages)


def add_event_id(
    stage_number: str,
    event_id: str,
    event_ids_path: str | Path,
) -> None:
    """
    Add an event ID for a stage.

    Args:
        stage_number: Stage number (e.g., "1", "3.1", "3.2")
        event_id: ZwiftPower event ID
        event_ids_path: Path to event IDs JSON file
    """
    event_ids = load_event_ids(event_ids_path)

    if stage_number not in event_ids:
        event_ids[stage_number] = []

    if event_id not in event_ids[stage_number]:
        event_ids[stage_number].append(event_id)

    save_event_ids(event_ids, event_ids_path)
