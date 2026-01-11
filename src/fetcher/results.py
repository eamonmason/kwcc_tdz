"""Fetch race results from ZwiftPower."""

import logging
import re
from datetime import datetime

from src.fetcher.client import ZwiftPowerClient
from src.models.result import RaceResult, parse_time
from src.models.rider import RiderRegistry

logger = logging.getLogger(__name__)


def fetch_event_results(
    client: ZwiftPowerClient,
    event_id: str,
    stage_number: int,
    rider_registry: RiderRegistry | None = None,
    event_timestamp: datetime | None = None,
) -> list[RaceResult]:
    """
    Fetch race results for a ZwiftPower event.

    Args:
        client: ZwiftPower client
        event_id: ZwiftPower event ID
        stage_number: Stage number for the result
        rider_registry: Optional rider registry to filter results
        event_timestamp: Optional event start timestamp (for penalty calculation)

    Returns:
        List of race results
    """
    logger.info(f"Fetching results for event {event_id}")

    # Try JSON API first (more reliable if available)
    try:
        results = _fetch_results_json(client, event_id, stage_number, event_timestamp)
        if results:
            if rider_registry:
                results = _filter_to_kwcc(results, rider_registry)
            return results
    except Exception as e:
        logger.debug(f"JSON API failed: {e}, falling back to HTML")

    # Fall back to HTML scraping
    results = _fetch_results_html(client, event_id, stage_number, event_timestamp)

    if rider_registry:
        results = _filter_to_kwcc(results, rider_registry)

    return results


def _fetch_results_json(
    client: ZwiftPowerClient,
    event_id: str,
    stage_number: int,
    event_timestamp: datetime | None = None,
) -> list[RaceResult]:
    """Fetch results via ZwiftPower JSON API.

    Uses the client's get_event_results() method which fetches from
    the cached JSON endpoints (/cache3/results/{event_id}_view.json).

    Args:
        client: ZwiftPower client
        event_id: Event ID
        stage_number: Stage number
        event_timestamp: Event start timestamp (used for penalty calculation)
    """
    try:
        # Use client method which tries cache endpoint first
        entries = client.get_event_results(event_id)

        if not entries:
            logger.debug(f"No results returned for event {event_id}")
            return []

        results = []
        for entry in entries:
            try:
                rider_id = str(entry.get("zwid", ""))
                rider_name = entry.get("name", entry.get("n", ""))
                position = int(entry.get("pos", entry.get("position", 0)))

                if not rider_id:
                    continue

                # Parse time - can be array [seconds, flag] or scalar
                time_val = entry.get("time", entry.get("t", 0))
                if isinstance(time_val, list):
                    raw_time = int(time_val[0]) if time_val else 0
                elif isinstance(time_val, str) and ":" in time_val:
                    raw_time = parse_time(time_val)
                else:
                    raw_time = int(float(time_val)) if time_val else 0

                if raw_time <= 0:
                    continue

                # Use provided event timestamp (from event list)
                # Individual result entries don't have timestamps
                timestamp = event_timestamp if event_timestamp else datetime.now()

                # Parse heart rate - can be array [value, flag]
                hr_val = entry.get("avg_hr", entry.get("hr", None))
                if isinstance(hr_val, list):
                    hr_val = hr_val[0] if hr_val else None

                # Parse average power - can be array
                power_val = entry.get("avg_power", entry.get("avg", None))
                if isinstance(power_val, list):
                    power_val = power_val[0] if power_val else None

                result = RaceResult(
                    rider_id=rider_id,
                    rider_name=rider_name,
                    stage_number=stage_number,
                    event_id=event_id,
                    raw_time_seconds=raw_time,
                    finish_position=position,
                    timestamp=timestamp,
                    category=entry.get("category", "C"),
                    power_avg=power_val,
                    heart_rate_avg=hr_val,
                )
                results.append(result)

            except Exception as e:
                logger.debug(f"Error parsing result entry: {e}")
                continue

        logger.info(f"Parsed {len(results)} results from JSON API for event {event_id}")
        return results

    except Exception as e:
        logger.debug(f"JSON fetch failed for event {event_id}: {e}")
        raise


def _fetch_results_html(
    client: ZwiftPowerClient,
    event_id: str,
    stage_number: int,
    event_timestamp: datetime | None = None,
) -> list[RaceResult]:
    """Fetch results via HTML scraping."""
    soup = client.get_html("/events.php", params={"zid": event_id})

    results = []

    # Find the results table
    results_table = soup.find("table", {"id": "table_event_results"})
    if not results_table:
        # Try alternative table ID
        results_table = soup.find("table", class_="table-striped")

    if not results_table:
        logger.warning(f"Could not find results table for event {event_id}")
        return results

    rows = results_table.find_all("tr")
    header_row = rows[0] if rows else None
    headers = []

    if header_row:
        headers = [th.get_text(strip=True).lower() for th in header_row.find_all("th")]

    for row in rows[1:]:
        try:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            # Extract rider info from link
            rider_link = row.find("a", href=re.compile(r"profile\.php\?z="))
            if not rider_link:
                continue

            rider_id_match = re.search(r"z=(\d+)", rider_link["href"])
            if not rider_id_match:
                continue

            rider_id = rider_id_match.group(1)
            rider_name = rider_link.get_text(strip=True)

            # Find position and time columns
            position = 0
            raw_time = 0

            for i, col in enumerate(cols):
                text = col.get_text(strip=True)
                header = headers[i] if i < len(headers) else ""

                if header in ("pos", "position", "#") or (i == 0 and text.isdigit()):
                    try:  # noqa: SIM105
                        position = int(text)
                    except ValueError:
                        pass

                if header == "time" or ":" in text:
                    try:  # noqa: SIM105
                        raw_time = parse_time(text)
                    except ValueError:
                        pass

            if raw_time == 0:
                continue

            result = RaceResult(
                rider_id=rider_id,
                rider_name=rider_name,
                stage_number=stage_number,
                event_id=event_id,
                raw_time_seconds=raw_time,
                finish_position=position or len(results) + 1,
                timestamp=event_timestamp if event_timestamp else datetime.now(),
                category="C",
            )
            results.append(result)

        except Exception as e:
            logger.debug(f"Error parsing result row: {e}")
            continue

    logger.info(f"Parsed {len(results)} results from HTML")
    return results


def _filter_to_kwcc(
    results: list[RaceResult],
    rider_registry: RiderRegistry,
) -> list[RaceResult]:
    """Filter results to only include KWCC riders."""
    kwcc_results = []

    for result in results:
        rider = rider_registry.get_by_zwiftpower_id(result.rider_id)
        if rider:
            kwcc_results.append(result)

    logger.info(
        f"Filtered to {len(kwcc_results)} KWCC riders from {len(results)} total"
    )
    return kwcc_results


def fetch_stage_results(
    client: ZwiftPowerClient,
    event_ids: list[str],
    stage_number: int,
    rider_registry: RiderRegistry,
    event_timestamps: dict[str, datetime] | None = None,
) -> list[RaceResult]:
    """
    Fetch results from multiple events for a stage.

    Args:
        client: ZwiftPower client
        event_ids: List of event IDs for the stage
        stage_number: Stage number
        rider_registry: Rider registry for filtering
        event_timestamps: Optional dict mapping event_id to event start datetime

    Returns:
        Combined list of all race results (may include multiple per rider).
        Best result selection should happen after penalties are applied.
    """
    all_results: list[RaceResult] = []

    for event_id in event_ids:
        try:
            # Get event timestamp for penalty calculation
            event_timestamp = None
            if event_timestamps:
                event_timestamp = event_timestamps.get(event_id)

            results = fetch_event_results(
                client, event_id, stage_number, rider_registry, event_timestamp
            )

            # Keep all results - best selection happens after penalties are applied
            all_results.extend(results)

        except Exception as e:
            logger.warning(f"Error fetching event {event_id}: {e}")
            continue

    logger.info(
        f"Fetched {len(all_results)} total results across {len(event_ids)} events"
    )
    return all_results
