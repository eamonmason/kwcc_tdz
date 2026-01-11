#!/usr/bin/env python3
"""Fetch results from ZwiftPower and cache locally."""

import argparse
import json
import logging
import os
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from src.config import get_tour_config, load_riders_from_csv
from src.fetcher import (
    ZwiftPowerClient,
    fetch_event_results,
    find_tdz_race_events_with_timestamps,
)
from src.models import DEFAULT_PENALTY_CONFIG, RaceResult
from src.processor import process_stage_results

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Default paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
RIDERS_CSV = PROJECT_ROOT / "KW TDZ sign on 2026 - Sheet1.csv"
EVENT_IDS_FILE = DATA_DIR / "event_ids.json"
CACHE_METADATA_FILE = CACHE_DIR / "cache_metadata.json"


def load_event_ids() -> dict[int, list[str]]:
    """Load cached event IDs from file."""
    if EVENT_IDS_FILE.exists():
        with EVENT_IDS_FILE.open() as f:
            data = json.load(f)
            # Skip non-numeric keys (like _comment, _instructions)
            return {int(k): v for k, v in data.items() if k.isdigit()}
    return {}


def load_event_timestamps() -> dict[str, str]:
    """Load cached event timestamps (event_id -> ISO timestamp string)."""
    timestamps_file = DATA_DIR / "event_timestamps.json"
    if timestamps_file.exists():
        with timestamps_file.open() as f:
            return json.load(f)
    return {}


def save_event_timestamps(timestamps: dict[str, str]) -> None:
    """Save event timestamps to file."""
    timestamps_file = DATA_DIR / "event_timestamps.json"
    timestamps_file.parent.mkdir(parents=True, exist_ok=True)
    with timestamps_file.open("w") as f:
        json.dump(timestamps, f, indent=2)
    logger.info(f"Saved {len(timestamps)} event timestamps")


def load_cache_metadata() -> dict:
    """Load cache metadata tracking finalized events."""
    if CACHE_METADATA_FILE.exists():
        with CACHE_METADATA_FILE.open() as f:
            return json.load(f)
    return {"finalized_stages": {}, "event_cache": {}}


def save_cache_metadata(metadata: dict) -> None:
    """Save cache metadata."""
    CACHE_METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_METADATA_FILE.open("w") as f:
        json.dump(metadata, f, indent=2)


def mark_stage_finalized(stage_number: int, rider_count: int) -> None:
    """Mark a stage's results as finalized (won't be re-fetched)."""
    metadata = load_cache_metadata()
    metadata["finalized_stages"][str(stage_number)] = {
        "finalized_at": datetime.now().isoformat(),
        "rider_count": rider_count,
    }
    save_cache_metadata(metadata)
    logger.info(f"Marked Stage {stage_number} as finalized ({rider_count} riders)")


def is_stage_finalized(stage_number: int) -> bool:
    """Check if a stage's results are finalized."""
    metadata = load_cache_metadata()
    return str(stage_number) in metadata.get("finalized_stages", {})


def mark_event_cached(event_id: str, stage_number: int, rider_count: int) -> None:
    """Mark an event's results as cached."""
    metadata = load_cache_metadata()
    if "event_cache" not in metadata:
        metadata["event_cache"] = {}
    metadata["event_cache"][event_id] = {
        "stage_number": stage_number,
        "cached_at": datetime.now().isoformat(),
        "rider_count": rider_count,
    }
    save_cache_metadata(metadata)


def get_cached_event_ids(stage_number: int) -> set[str]:
    """Get event IDs that have already been cached for a stage."""
    metadata = load_cache_metadata()
    event_cache = metadata.get("event_cache", {})
    return {
        eid for eid, info in event_cache.items()
        if info.get("stage_number") == stage_number
    }


def save_event_ids(event_ids: dict[int, list[str]]) -> None:
    """Save event IDs to cache file."""
    EVENT_IDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_IDS_FILE.open("w") as f:
        json.dump(event_ids, f, indent=2)
    logger.info(f"Saved event IDs to {EVENT_IDS_FILE}")


def cache_race_results(stage: int, results: list[RaceResult]) -> None:
    """Cache raw race results to file."""
    cache_file = CACHE_DIR / f"stage_{stage}_raw.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    data = [r.model_dump(mode="json") for r in results]
    with cache_file.open("w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info(f"Cached {len(results)} raw results to {cache_file}")


def load_cached_race_results(stage: int) -> list[RaceResult] | None:
    """Load cached raw race results."""
    cache_file = CACHE_DIR / f"stage_{stage}_raw.json"
    if not cache_file.exists():
        return None

    with cache_file.open() as f:
        data = json.load(f)

    return [RaceResult.model_validate(r) for r in data]


def save_stage_results(stage: int, group: str, results: list) -> None:
    """Save processed stage results to cache."""
    cache_file = CACHE_DIR / f"stage_{stage}_group_{group}.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    data = [r.model_dump(mode="json") for r in results]
    with cache_file.open("w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info(f"Saved {len(results)} {group} results to {cache_file}")


def discover_event_ids(
    client: ZwiftPowerClient,
    tour_config,
    force: bool = False,
) -> dict[int, list[str]]:
    """Discover TdZ event IDs from ZwiftPower."""
    existing = load_event_ids()
    existing_timestamps = load_event_timestamps()

    if existing and not force:
        logger.info(f"Using cached event IDs for {len(existing)} stages")
        return existing

    event_ids: dict[int, list[str]] = {}
    event_timestamps: dict[str, str] = existing_timestamps.copy()

    for stage in tour_config.stages:
        try:
            logger.info(f"Searching for Stage {stage.number}: {stage.route}")
            events_with_ts = find_tdz_race_events_with_timestamps(
                client,
                stage.number,
                stage.route,
                stage.start_date,
                stage.end_date,
            )
            # Extract IDs and timestamps
            ids = []
            for event_id, event_ts in events_with_ts:
                ids.append(event_id)
                if event_ts:
                    event_timestamps[event_id] = event_ts.isoformat()
            event_ids[stage.number] = ids
            logger.info(f"Found {len(ids)} events for Stage {stage.number}")
        except Exception as e:
            logger.warning(f"Failed to find events for Stage {stage.number}: {e}")
            # Use existing if available
            if stage.number in existing:
                event_ids[stage.number] = existing[stage.number]

    save_event_ids(event_ids)
    save_event_timestamps(event_timestamps)
    return event_ids


def fetch_stage_from_zwiftpower(
    client: ZwiftPowerClient,
    stage_number: int,
    event_ids: list[str],
    rider_registry,
    use_cache: bool = True,
    stage_is_complete: bool = False,
) -> list[RaceResult]:
    """Fetch results for a stage from ZwiftPower.

    Args:
        client: ZwiftPower client
        stage_number: Stage number to fetch
        event_ids: List of event IDs for this stage
        rider_registry: Registry of KWCC riders
        use_cache: Whether to use cached results
        stage_is_complete: Whether the stage has ended (past end_date)

    Returns:
        List of race results for KWCC riders
    """
    # Check if stage is already finalized - no need to fetch at all
    if is_stage_finalized(stage_number):
        cached = load_cached_race_results(stage_number)
        if cached:
            logger.info(
                f"Stage {stage_number} is finalized - using cached results "
                f"({len(cached)} riders)"
            )
            return cached

    # Check cache first for non-finalized stages
    if use_cache:
        cached = load_cached_race_results(stage_number)
        if cached:
            logger.info(f"Using cached results for Stage {stage_number}")
            return cached

    all_results: dict[str, RaceResult] = {}

    # Get events we've already cached (for incremental updates)
    already_cached = get_cached_event_ids(stage_number)
    events_to_fetch = [eid for eid in event_ids if eid not in already_cached]

    if already_cached and events_to_fetch:
        logger.info(
            f"Stage {stage_number}: {len(already_cached)} events cached, "
            f"{len(events_to_fetch)} new events to fetch"
        )

    # Load existing cached results to merge with new ones
    existing_cached = load_cached_race_results(stage_number) or []
    for result in existing_cached:
        all_results[result.rider_id] = result

    # Load event timestamps for penalty calculation
    event_timestamps = load_event_timestamps()

    for event_id in events_to_fetch:
        try:
            logger.info(f"Fetching event {event_id} for Stage {stage_number}")

            # Get event timestamp if available
            event_ts_str = event_timestamps.get(event_id)
            event_ts = datetime.fromisoformat(event_ts_str) if event_ts_str else None

            results = fetch_event_results(
                client,
                event_id,
                stage_number,
                rider_registry,
                event_timestamp=event_ts,
            )
            logger.info(f"Got {len(results)} KWCC results from event {event_id}")

            # Keep best result per rider
            for result in results:
                if result.rider_id not in all_results or result.raw_time_seconds < all_results[result.rider_id].raw_time_seconds:
                    all_results[result.rider_id] = result

            # Mark this event as cached
            mark_event_cached(event_id, stage_number, len(results))

        except Exception as e:
            logger.warning(f"Error fetching event {event_id}: {e}")

    results_list = list(all_results.values())

    # Cache the results
    if results_list:
        cache_race_results(stage_number, results_list)

    # If stage is complete, mark it as finalized so we don't re-fetch
    if stage_is_complete and results_list:
        mark_stage_finalized(stage_number, len(results_list))

    return results_list


def fetch_all_stages(
    username: str | None = None,
    password: str | None = None,
    stages: list[int] | None = None,
    force_refresh: bool = False,
    discover_events: bool = False,
) -> None:
    """Fetch results for all (or specified) stages."""
    # Load riders
    if not RIDERS_CSV.exists():
        logger.error(f"Riders CSV not found: {RIDERS_CSV}")
        return

    rider_registry = load_riders_from_csv(RIDERS_CSV)
    logger.info(f"Loaded {len(rider_registry.riders)} riders")

    # Get tour config
    tour_config = get_tour_config()

    # Determine which stages to fetch
    if stages:
        stages_to_fetch = [s for s in tour_config.stages if s.number in stages]
    else:
        # Fetch all stages up to current
        today = date.today()
        stages_to_fetch = [s for s in tour_config.stages if s.start_date <= today]

    if not stages_to_fetch:
        logger.info("No stages to fetch")
        return

    logger.info(f"Will fetch {len(stages_to_fetch)} stages")

    with ZwiftPowerClient(username, password) as client:
        # Authenticate if credentials provided
        if username and password:
            try:
                client.authenticate()
                logger.info("Authenticated with ZwiftPower")
            except Exception as e:
                logger.warning(f"Authentication failed: {e}")

        # Discover event IDs if requested
        if discover_events:
            event_ids = discover_event_ids(client, tour_config, force=force_refresh)
        else:
            event_ids = load_event_ids()

        # Fetch each stage
        for stage in stages_to_fetch:
            stage_event_ids = event_ids.get(stage.number, [])

            if not stage_event_ids:
                logger.warning(f"No event IDs for Stage {stage.number}")
                continue

            logger.info(f"Fetching Stage {stage.number}: {stage.name}")

            # Fetch raw results
            race_results = fetch_stage_from_zwiftpower(
                client,
                stage.number,
                stage_event_ids,
                rider_registry,
                use_cache=not force_refresh,
                stage_is_complete=stage.is_complete,
            )

            if not race_results:
                logger.warning(f"No results for Stage {stage.number}")
                continue

            # Process with handicaps and penalties
            is_provisional = stage.is_active
            group_a, group_b = process_stage_results(
                race_results,
                rider_registry,
                stage.number,
                is_provisional=is_provisional,
                penalty_config=DEFAULT_PENALTY_CONFIG,
            )

            # Save processed results
            save_stage_results(stage.number, "A", group_a)
            save_stage_results(stage.number, "B", group_b)

            logger.info(
                f"Stage {stage.number}: {len(group_a)} Group A, {len(group_b)} Group B"
            )


def main():
    """Main entry point."""
    # Load environment variables from .env file
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Fetch ZwiftPower results and cache locally",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Set event IDs manually (find them on ZwiftPower)
  uv run python scripts/fetch_zwiftpower.py --set-event-ids '{"1": ["4905273", "4905274"]}'

  # Fetch results for stage 1 using configured event IDs
  uv run python scripts/fetch_zwiftpower.py --stages 1

  # Force refresh cached data
  uv run python scripts/fetch_zwiftpower.py --stages 1 --force

  # Try to auto-discover events (may not work with current ZwiftPower)
  uv run python scripts/fetch_zwiftpower.py --discover-events

How to find event IDs:
  1. Go to https://zwiftpower.com
  2. Search for "Tour de Zwift" events
  3. Look at the URL: events.php?zid=<EVENT_ID>
  4. Add the ID to data/event_ids.json or use --set-event-ids
""",
    )
    parser.add_argument(
        "--username",
        "-u",
        help="ZwiftPower/Zwift username (optional for public data)",
        default=os.environ.get("ZWIFTPOWER_USERNAME"),
    )
    parser.add_argument(
        "--password",
        "-p",
        help="ZwiftPower/Zwift password",
        default=os.environ.get("ZWIFTPOWER_PASSWORD"),
    )
    parser.add_argument(
        "--stages",
        "-s",
        type=int,
        nargs="+",
        help="Specific stages to fetch (default: all available)",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force refresh (ignore cache)",
    )
    parser.add_argument(
        "--discover-events",
        "-d",
        action="store_true",
        help="Discover event IDs from ZwiftPower (may not work)",
    )
    parser.add_argument(
        "--set-event-ids",
        type=str,
        help='Manually set event IDs as JSON (e.g., \'{"1": ["123", "456"]}\')',
    )
    parser.add_argument(
        "--add-event",
        nargs=2,
        metavar=("STAGE", "EVENT_ID"),
        help="Add a single event ID to a stage (e.g., --add-event 1 4905273)",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Show current event IDs configuration",
    )

    args = parser.parse_args()

    # Show config
    if args.show_config:
        event_ids = load_event_ids()
        print("\nConfigured Event IDs:")
        print("-" * 40)
        for stage in range(1, 7):
            ids = event_ids.get(stage, [])
            if ids:
                print(f"Stage {stage}: {', '.join(ids)}")
            else:
                print(f"Stage {stage}: (not configured)")
        print("-" * 40)
        print(f"\nConfig file: {EVENT_IDS_FILE}")
        return

    # Handle manual event ID setting
    if args.set_event_ids:
        try:
            event_ids = json.loads(args.set_event_ids)
            event_ids = {int(k): v for k, v in event_ids.items()}
            save_event_ids(event_ids)
            logger.info(f"Set event IDs: {event_ids}")
            print(f"Saved event IDs for {len(event_ids)} stages")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON for event IDs: {e}")
            return

    # Add single event
    if args.add_event:
        stage = int(args.add_event[0])
        event_id = args.add_event[1]
        event_ids = load_event_ids()
        if stage not in event_ids:
            event_ids[stage] = []
        if event_id not in event_ids[stage]:
            event_ids[stage].append(event_id)
            save_event_ids(event_ids)
            print(f"Added event {event_id} to Stage {stage}")
        else:
            print(f"Event {event_id} already configured for Stage {stage}")
        return

    # Check if we have event IDs before trying to fetch
    if not args.discover_events:
        event_ids = load_event_ids()
        has_ids = any(len(v) > 0 for v in event_ids.values() if isinstance(v, list))
        if not has_ids:
            print("\n" + "=" * 60)
            print("No event IDs configured!")
            print("=" * 60)
            print("\nTo fetch results, you need to configure ZwiftPower event IDs.")
            print("\nOptions:")
            print("  1. Add event IDs manually:")
            print('     uv run python scripts/fetch_zwiftpower.py --add-event 1 <EVENT_ID>')
            print("\n  2. Edit data/event_ids.json directly")
            print("\n  3. Try auto-discovery (may not work):")
            print("     uv run python scripts/fetch_zwiftpower.py --discover-events")
            print("\nTo find event IDs, go to ZwiftPower and look for TdZ events.")
            print("The event ID is in the URL: events.php?zid=<EVENT_ID>")
            print("=" * 60 + "\n")
            return

    fetch_all_stages(
        username=args.username,
        password=args.password,
        stages=args.stages,
        force_refresh=args.force,
        discover_events=args.discover_events,
    )


if __name__ == "__main__":
    main()
