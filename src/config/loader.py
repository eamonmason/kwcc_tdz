"""Load rider configuration from CSV file."""

import csv
from pathlib import Path

from src.models.rider import Rider, RiderRegistry


def load_riders_from_csv(csv_path: str | Path) -> RiderRegistry:
    """
    Load riders from a CSV file.

    Expected CSV columns:
    - Name
    - ZwiftPower ID
    - Handicap Group (A1, A2, A3, B1, B2, B3, B4)
    - ZP Racing Score (optional)
    - Raced TDZ before? Y/N (optional, ignored)

    Args:
        csv_path: Path to the CSV file

    Returns:
        RiderRegistry containing all valid riders
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    riders: list[Rider] = []

    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            # Skip rows without required fields
            name = row.get("Name", "").strip()
            zp_id = row.get("ZwiftPower ID", "").strip()
            handicap_group = row.get("Handicap Group", "").strip().upper()

            # Skip if missing required fields
            if not name or not zp_id or not handicap_group:
                continue

            # Skip if handicap group is not valid
            if handicap_group not in [
                "A1",
                "A2",
                "A3",
                "B1",
                "B2",
                "B3",
                "B4",
            ]:
                continue

            # Parse racing score (optional)
            racing_score_str = row.get("ZP Racing Score", "").strip()
            racing_score: int | None = None
            if racing_score_str and racing_score_str.lower() != "tbc":
                try:  # noqa: SIM105
                    racing_score = int(racing_score_str)
                except ValueError:
                    pass

            rider = Rider(
                name=name,
                zwiftpower_id=zp_id,
                handicap_group=handicap_group,
                zp_racing_score=racing_score,
            )
            riders.append(rider)

    return RiderRegistry(riders=riders)


def load_riders_from_json(json_path: str | Path) -> RiderRegistry:
    """
    Load riders from a JSON file.

    Args:
        json_path: Path to the JSON file

    Returns:
        RiderRegistry containing all riders
    """
    import json

    json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"JSON file not found: {json_path}")

    with json_path.open(encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        riders = [Rider.model_validate(r) for r in data]
        return RiderRegistry(riders=riders)

    if isinstance(data, dict) and "riders" in data:
        return RiderRegistry.model_validate(data)

    raise ValueError("Invalid JSON format: expected list or dict with 'riders' key")


def save_riders_to_json(registry: RiderRegistry, json_path: str | Path) -> None:
    """
    Save riders to a JSON file.

    Args:
        registry: RiderRegistry to save
        json_path: Path to output JSON file
    """
    import json

    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(
            {"riders": [r.model_dump() for r in registry.riders]},
            f,
            indent=2,
        )
