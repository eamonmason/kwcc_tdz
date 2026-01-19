#!/usr/bin/env python3
"""Run the KWCC TdZ website locally for testing."""

import http.server
import json
import socketserver
import webbrowser
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from src.config import get_tour_config, load_riders_from_csv
from src.generator import WebsiteGenerator
from src.models import DEFAULT_PENALTY_CONFIG, RaceResult, StageResult
from src.models.tour import STAGE_ORDER
from src.processor import build_tour_standings, process_stage_results

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
RIDERS_CSV = PROJECT_ROOT / "KW TDZ sign on 2026 - Sheet1.csv"


def load_cached_stage_results(stage: str, group: str) -> list[StageResult] | None:
    """Load cached processed stage results."""
    cache_file = CACHE_DIR / f"stage_{stage}_group_{group}.json"
    if not cache_file.exists():
        return None

    with cache_file.open() as f:
        data = json.load(f)

    # Migrate legacy cache with int stage_number to str
    for r in data:
        if isinstance(r.get("stage_number"), int):
            r["stage_number"] = str(r["stage_number"])

    return [StageResult.model_validate(r) for r in data]


def load_all_cached_results() -> (
    dict[str, tuple[list[StageResult], list[StageResult]]] | None
):
    """Load all cached stage results."""
    results: dict[str, tuple[list[StageResult], list[StageResult]]] = {}

    for stage in STAGE_ORDER:
        group_a = load_cached_stage_results(stage, "A")
        group_b = load_cached_stage_results(stage, "B")

        if group_a is not None or group_b is not None:
            results[stage] = (group_a or [], group_b or [])

    return results if results else None


def create_sample_race_results(rider_registry, stage_number: str) -> list[RaceResult]:
    """Create sample race results for testing."""
    import random

    results = []
    base_time = 2400  # 40 minutes base

    # Get stage index for date calculation (e.g., "1" -> 0, "3.1" -> 2, "3.2" -> 3)
    stage_idx = STAGE_ORDER.index(stage_number) if stage_number in STAGE_ORDER else 0

    for rider in rider_registry.riders:
        # Add some randomness to times
        time_variance = random.randint(-300, 600)  # -5 to +10 minutes
        raw_time = base_time + time_variance

        # Simulate some riders doing Monday 5pm event (penalty)
        is_penalty_event = random.random() < 0.2  # 20% chance

        if is_penalty_event:
            # Monday 5pm
            timestamp = datetime(2026, 1, 5 + stage_idx * 7, 17, 0, 0)
        else:
            # Tuesday 6pm (no penalty)
            timestamp = datetime(2026, 1, 6 + stage_idx * 7, 18, 0, 0)

        result = RaceResult(
            rider_id=rider.zwiftpower_id,
            rider_name=rider.name,
            stage_number=stage_number,
            event_id=f"sample_{stage_number}_{rider.zwiftpower_id}",
            raw_time_seconds=raw_time,
            finish_position=1,  # Will be recalculated
            timestamp=timestamp,
        )
        results.append(result)

    return results


def generate_website_from_cache(output_dir: Path) -> tuple[list[Path] | None, bool]:
    """Generate website from cached ZwiftPower data.

    Returns:
        Tuple of (generated_files, is_mock_data). Returns (None, True) if no cache found.
    """
    print("Checking for cached ZwiftPower data...", flush=True)

    cached_results = load_all_cached_results()
    if not cached_results:
        print(
            "No cached data found. Run 'uv run python scripts/fetch_zwiftpower.py' first.",
            flush=True,
        )
        return None, True

    print(f"Found cached data for {len(cached_results)} stages", flush=True)

    # Get tour config
    tour_config = get_tour_config()

    # Build group results dicts for GC calculation
    group_a_results: dict[str, list[StageResult]] = {}
    group_b_results: dict[str, list[StageResult]] = {}

    for stage, (group_a, group_b) in cached_results.items():
        if group_a:
            group_a_results[stage] = group_a
            print(f"  Stage {stage}: {len(group_a)} Group A riders", flush=True)
        if group_b:
            group_b_results[stage] = group_b
            print(f"  Stage {stage}: {len(group_b)} Group B riders", flush=True)

    # Determine current stage from tour config dates (not from cached results)
    active_stage = tour_config.current_stage
    if active_stage:
        current_stage = active_stage.number
        is_stage_in_progress = True
    else:
        # No active stage - use last completed
        if tour_config.completed_stages:
            current_stage = tour_config.completed_stages[-1].number
        else:
            current_stage = 1
        is_stage_in_progress = False

    # Count actual completed stages from tour config
    completed_stages = len(tour_config.completed_stages)
    last_updated = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    tour_standings = build_tour_standings(
        group_a_results,
        group_b_results,
        completed_stages,
        current_stage,
        last_updated,
        is_stage_in_progress,
    )

    print(
        f"GC standings: {len(tour_standings.group_a.standings)} Group A, "
        f"{len(tour_standings.group_b.standings)} Group B",
        flush=True,
    )

    # Generate website (not mock data - using real cached results)
    generator = WebsiteGenerator(
        output_dir=output_dir,
        tour_name=tour_config.name,
        available_years=[2026],
        is_mock_data=False,
    )

    # Transform cached_results to include empty uncategorized list
    # generate_all expects (group_a, group_b, uncategorized) tuples
    full_stage_results: dict[
        str, tuple[list[StageResult], list[StageResult], list[StageResult]]
    ] = {
        stage: (group_a, group_b, [])
        for stage, (group_a, group_b) in cached_results.items()
    }

    generated_files = generator.generate_all(
        full_stage_results,
        tour_standings,
        tour_config,
    )

    print(f"Generated {len(generated_files)} files from cached data", flush=True)
    return generated_files, False


def generate_sample_website(output_dir: Path, num_stages: int = 3):
    """Generate website with sample data."""
    print(f"Generating sample website with {num_stages} stages...", flush=True)

    # Load real riders from CSV if available
    if RIDERS_CSV.exists():
        print(f"Loading riders from {RIDERS_CSV}", flush=True)
        rider_registry = load_riders_from_csv(RIDERS_CSV)
    else:
        # Use built-in sample riders
        from src.models import Rider, RiderRegistry

        print("Using sample test riders (CSV not found)", flush=True)
        sample_riders = [
            Rider(
                name="Tom Kennett",
                zwiftpower_id="997635",
                handicap_group="A1",
                zp_racing_score=750,
            ),
            Rider(
                name="Chris Jenkins",
                zwiftpower_id="2456208",
                handicap_group="A2",
                zp_racing_score=742,
            ),
            Rider(
                name="Eamon Mason",
                zwiftpower_id="1231961",
                handicap_group="A3",
                zp_racing_score=542,
            ),
            Rider(
                name="Adam Currie",
                zwiftpower_id="4037257",
                handicap_group="B1",
                zp_racing_score=234,
            ),
            Rider(
                name="Gareth Edwards",
                zwiftpower_id="1746490",
                handicap_group="B2",
                zp_racing_score=263,
            ),
            Rider(
                name="Tom Bagley",
                zwiftpower_id="783382",
                handicap_group="B3",
                zp_racing_score=226,
            ),
            Rider(
                name="James Turner",
                zwiftpower_id="1098357",
                handicap_group="B4",
                zp_racing_score=216,
            ),
        ]
        rider_registry = RiderRegistry(riders=sample_riders)

    print(f"Loaded {len(rider_registry.riders)} riders", flush=True)

    # Get tour config
    tour_config = get_tour_config()

    # Generate sample results for specified stages
    group_a_results: dict[str, list[StageResult]] = {}
    group_b_results: dict[str, list[StageResult]] = {}
    stage_results_dict: dict[str, tuple[list[StageResult], list[StageResult]]] = {}

    # Use first num_stages from STAGE_ORDER
    stages_to_generate = STAGE_ORDER[:num_stages]

    for stage in stages_to_generate:
        print(f"Generating Stage {stage} results...", flush=True)
        race_results = create_sample_race_results(rider_registry, stage)
        print(f"  Created {len(race_results)} race results", flush=True)

        group_a, group_b = process_stage_results(
            race_results,
            rider_registry,
            stage,
            is_provisional=(
                stage == stages_to_generate[-1]
            ),  # Last stage is provisional
            penalty_config=DEFAULT_PENALTY_CONFIG,
        )

        group_a_results[stage] = group_a
        group_b_results[stage] = group_b
        stage_results_dict[stage] = (group_a, group_b)

        print(
            f"  Group A: {len(group_a)} riders, Group B: {len(group_b)} riders",
            flush=True,
        )

    # Build tour standings
    last_updated = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    current_stage = stages_to_generate[-1] if stages_to_generate else "1"
    tour_standings = build_tour_standings(
        group_a_results,
        group_b_results,
        completed_stages=num_stages,
        current_stage=current_stage,
        last_updated=last_updated,
        is_stage_in_progress=False,  # Mock data shows final results
    )

    print(
        f"GC standings: {len(tour_standings.group_a.standings)} Group A, "
        f"{len(tour_standings.group_b.standings)} Group B"
    )

    # Generate website (is_mock_data=True since this is sample data)
    generator = WebsiteGenerator(
        output_dir=output_dir,
        tour_name=tour_config.name,
        available_years=[2026],  # Just 2026 for now
        is_mock_data=True,
    )

    generated_files = generator.generate_all(
        stage_results_dict,
        tour_standings,
        tour_config,
    )

    print(f"Generated {len(generated_files)} files")
    return generated_files


def serve_website(directory: Path, port: int = 8000):
    """Serve the website locally."""
    import os

    os.chdir(directory)

    handler = http.server.SimpleHTTPRequestHandler

    with socketserver.TCPServer(("", port), handler) as httpd:
        url = f"http://localhost:{port}"
        print(f"\n{'=' * 50}")
        print(f"Serving website at: {url}")
        print("Press Ctrl+C to stop")
        print(f"{'=' * 50}\n")

        # Open in browser
        webbrowser.open(url)

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Run KWCC TdZ website locally")
    parser.add_argument(
        "--stages",
        type=int,
        default=3,
        help="Number of stages to generate for mock data (1-7, default: 3)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to serve on (default: 8000)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: temp directory)",
    )
    parser.add_argument(
        "--no-serve",
        action="store_true",
        help="Generate only, don't start web server",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force use of mock data instead of cached ZwiftPower data",
    )

    args = parser.parse_args()

    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Try cached data first, unless --mock specified
        if not args.mock:
            generated, _ = generate_website_from_cache(output_dir)
            if generated is None:
                print("\nFalling back to mock data...\n", flush=True)
                generate_sample_website(output_dir, args.stages)
        else:
            generate_sample_website(output_dir, args.stages)

        if not args.no_serve:
            serve_website(output_dir, args.port)
    else:
        # Use temporary directory
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            # Try cached data first, unless --mock specified
            if not args.mock:
                generated, _ = generate_website_from_cache(output_dir)
                if generated is None:
                    print("\nFalling back to mock data...\n", flush=True)
                    generate_sample_website(output_dir, args.stages)
            else:
                generate_sample_website(output_dir, args.stages)

            if args.no_serve:
                print(f"\nGenerated files in: {output_dir}")
                input("Press Enter to clean up...")
            else:
                serve_website(output_dir, args.port)


if __name__ == "__main__":
    main()
