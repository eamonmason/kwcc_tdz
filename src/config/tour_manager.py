"""Tour management utilities for handling multiple tour years."""

import json
from pathlib import Path

from src.models.tour import DEFAULT_TOUR_REGISTRY, TourConfig, TourRegistry


def load_tour_registry_from_json(json_path: str | Path) -> TourRegistry:
    """
    Load tour registry from a JSON file.

    Args:
        json_path: Path to the tour registry JSON file

    Returns:
        TourRegistry containing all tours
    """
    json_path = Path(json_path)
    if not json_path.exists():
        return DEFAULT_TOUR_REGISTRY

    with json_path.open(encoding="utf-8") as f:
        data = json.load(f)

    return TourRegistry.model_validate(data)


def save_tour_registry_to_json(
    registry: TourRegistry,
    json_path: str | Path,
) -> None:
    """
    Save tour registry to a JSON file.

    Args:
        registry: TourRegistry to save
        json_path: Path to output JSON file
    """
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(registry.model_dump(mode="json"), f, indent=2, default=str)


def archive_tour(
    registry: TourRegistry,
    tour_id: str,
) -> TourRegistry:
    """
    Mark a tour as archived.

    Args:
        registry: TourRegistry containing the tour
        tour_id: ID of the tour to archive

    Returns:
        Updated TourRegistry
    """
    tour = registry.get_tour(tour_id)
    if tour:
        tour.is_archived = True
    return registry


def create_new_tour_config(
    year: int,
    stages_data: list[dict] | None = None,
) -> TourConfig:
    """
    Create a new tour configuration for a given year.

    Args:
        year: The tour year
        stages_data: Optional list of stage data dicts

    Returns:
        TourConfig for the new tour
    """
    from datetime import date

    from src.models.tour import Stage

    tour_id = f"tdz-{year}"
    name = f"Tour de Zwift {year}"

    if stages_data:  # noqa: SIM108
        stages = [Stage.model_validate(s) for s in stages_data]
    else:
        # Create placeholder stages (can be updated later)
        stages = []

    return TourConfig(
        tour_id=tour_id,
        year=year,
        name=name,
        stages=stages,
        makeup_week_start=date(year, 2, 16),  # Default makeup week
        makeup_week_end=date(year, 2, 22),
        is_archived=False,
    )


def get_tour_s3_paths(tour_id: str) -> dict[str, str]:
    """
    Get S3 paths for a tour.

    Args:
        tour_id: Tour identifier

    Returns:
        Dict with paths for results, config, riders, event_ids
    """
    return {
        "results_prefix": f"results/{tour_id}",
        "config_prefix": f"config/{tour_id}",
        "riders_key": f"config/{tour_id}/riders.json",
        "event_ids_key": f"config/{tour_id}/event_ids.json",
        "tour_config_key": f"config/{tour_id}/tour.json",
    }
