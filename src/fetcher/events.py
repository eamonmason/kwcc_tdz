"""ZwiftPower event search and discovery."""

import logging
import re
from datetime import UTC, date, datetime

from src.fetcher.client import ZwiftPowerClient
from src.fetcher.exceptions import ZwiftPowerEventNotFoundError

logger = logging.getLogger(__name__)


def search_events_api(
    client: ZwiftPowerClient,
    search_term: str = "Tour de Zwift",
    days: int = 7,
) -> list[dict]:
    """
    Search for events using ZwiftPower API.

    Uses the client's get_events_with_results method which accesses the
    correct cache/API endpoints discovered through testing.

    Args:
        client: ZwiftPower client
        search_term: Event name to search for
        days: Number of days to look back

    Returns:
        List of event dictionaries
    """
    logger.info(f"Searching events via API for '{search_term}' (past {days} days)")
    events = []

    # Use the client's method to get events with results
    all_events = client.get_events_with_results(days=days)
    logger.info(f"Got {len(all_events)} events from API")

    # Filter for matching events
    search_lower = search_term.lower()
    for event in all_events:
        # Event name is in 't' field (title)
        event_name = (
            event.get("t", "") or event.get("name", "") or event.get("title", "")
        )
        if search_lower in event_name.lower():
            event_id = str(
                event.get("zid", "") or event.get("DT_RowId", "") or event.get("id", "")
            )
            if event_id and event_id not in [e["id"] for e in events]:
                # Convert timestamp to date string (use UTC to ensure correct day-of-week)
                timestamp = event.get("tm", 0)
                event_date = None
                if timestamp:
                    try:  # noqa: SIM105
                        event_date = datetime.fromtimestamp(timestamp, tz=UTC).strftime(
                            "%Y-%m-%d %H:%M"
                        )
                    except (ValueError, OSError):
                        pass

                events.append(
                    {
                        "id": event_id,
                        "name": event_name,
                        "date": event_date,
                        "route_id": event.get("r", ""),
                        "timestamp": timestamp,
                    }
                )

    logger.info(f"Found {len(events)} events matching '{search_term}'")
    return events


def search_events_html(
    client: ZwiftPowerClient,
    search_term: str = "Tour de Zwift",
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    """
    Search for events on ZwiftPower via HTML scraping.

    Args:
        client: ZwiftPower client
        search_term: Event name to search for
        start_date: Optional start date filter
        end_date: Optional end date filter

    Returns:
        List of event dictionaries with id, name, date, route
    """
    logger.info(f"Searching for events matching '{search_term}' via HTML")

    soup = client.get_html("/events.php")
    events = []

    # Try multiple table selectors
    table_selectors = [
        {"id": "events_list"},
        {"id": "table_event_list"},
        {"class_": "table-striped"},
        {"class_": "events-table"},
    ]

    event_table = None
    for selector in table_selectors:
        event_table = soup.find("table", selector)
        if event_table:
            logger.debug(f"Found table with selector: {selector}")
            break

    if not event_table:
        # Try finding any table with event links
        all_tables = soup.find_all("table")
        for table in all_tables:
            if table.find("a", href=re.compile(r"events\.php\?zid=")):
                event_table = table
                logger.debug("Found table with event links")
                break

    if not event_table:
        logger.warning("Could not find events table in HTML")
        return events

    rows = event_table.find_all("tr")
    for row in rows[1:]:  # Skip header row
        try:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue

            # Extract event link and ID
            link = row.find("a", href=re.compile(r"events\.php\?zid="))
            if not link:
                continue

            event_id = re.search(r"zid=(\d+)", link["href"])
            if not event_id:
                continue

            event_name = link.get_text(strip=True)

            # Check if event matches search term
            if search_term.lower() not in event_name.lower():
                continue

            # Extract date from the row
            date_text = cols[0].get_text(strip=True) if cols else ""
            event_date = _parse_date(date_text)

            # Apply date filters
            if start_date and event_date and event_date < start_date:
                continue
            if end_date and event_date and event_date > end_date:
                continue

            events.append(
                {
                    "id": event_id.group(1),
                    "name": event_name,
                    "date": event_date.isoformat() if event_date else None,
                    "raw_date": date_text,
                }
            )

        except Exception as e:
            logger.debug(f"Error parsing event row: {e}")
            continue

    logger.info(f"Found {len(events)} events matching '{search_term}'")
    return events


def search_events(
    client: ZwiftPowerClient,
    search_term: str = "Tour de Zwift",
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    """
    Search for events on ZwiftPower.

    Tries API first, falls back to HTML scraping.

    Args:
        client: ZwiftPower client
        search_term: Event name to search for
        start_date: Optional start date filter
        end_date: Optional end date filter

    Returns:
        List of event dictionaries with id, name, date, route
    """
    # Try API first
    events = search_events_api(client, search_term)

    # Fall back to HTML if API didn't work
    if not events:
        events = search_events_html(client, search_term, start_date, end_date)

    return events


def search_recent_events_html(
    client: ZwiftPowerClient,
    search_term: str = "Tour de Zwift",
) -> list[dict]:
    """
    Search ZwiftPower's recent events page.

    Args:
        client: ZwiftPower client
        search_term: Event name to search for

    Returns:
        List of event dictionaries
    """
    logger.info(f"Searching recent events page for '{search_term}'")

    # Try different event listing pages
    pages_to_try = [
        "/events.php",
        "/events.php?p=1",
        "/events.php?p=2",
    ]

    all_events = []

    for page in pages_to_try:
        try:
            soup = client.get_html(page)

            # Find all links that look like event links
            event_links = soup.find_all("a", href=re.compile(r"events\.php\?zid=\d+"))

            for link in event_links:
                event_name = link.get_text(strip=True)
                if search_term.lower() not in event_name.lower():
                    continue

                href = link.get("href", "")
                event_id_match = re.search(r"zid=(\d+)", href)
                if not event_id_match:
                    continue

                event_id = event_id_match.group(1)

                # Avoid duplicates
                if event_id not in [e["id"] for e in all_events]:
                    all_events.append(
                        {
                            "id": event_id,
                            "name": event_name,
                            "date": None,
                            "route": "",
                        }
                    )

        except Exception as e:
            logger.debug(f"Failed to search {page}: {e}")
            continue

    logger.info(f"Found {len(all_events)} events from recent pages")
    return all_events


def find_tdz_race_events(
    client: ZwiftPowerClient,
    stage_number: int,
    route_name: str,
    start_date: date,
    end_date: date,
) -> list[str]:
    """
    Find Tour de Zwift race event IDs for a specific stage.

    Args:
        client: ZwiftPower client
        stage_number: Stage number (1-6)
        route_name: Expected route name
        start_date: Stage start date
        end_date: Stage end date

    Returns:
        List of event IDs

    Raises:
        ZwiftPowerEventNotFoundError: If no events found
    """
    events_with_ts = find_tdz_race_events_with_timestamps(
        client, stage_number, route_name, start_date, end_date
    )
    return [eid for eid, _ in events_with_ts]


def find_tdz_race_events_with_timestamps(
    client: ZwiftPowerClient,
    stage_number: int,
    route_name: str,
    start_date: date,
    end_date: date,
    preloaded_events: list[dict] | None = None,
) -> list[tuple[str, datetime | None]]:
    """
    Find Tour de Zwift event IDs for a specific stage with timestamps.

    Fetches ALL event types (both races and rides) that match the stage.
    Route option filtering (A/B/C/D/E) is handled by result-level category
    filtering, not event filtering.

    Args:
        client: ZwiftPower client
        stage_number: Stage number (1-6)
        route_name: Expected route name
        start_date: Stage start date
        end_date: Stage end date
        preloaded_events: Optional list of pre-loaded events to use instead of
            fetching from API. This enables the ELT pattern where events are
            accumulated in S3 and passed in rather than always re-fetched.

    Returns:
        List of tuples (event_id, event_timestamp)

    Raises:
        ZwiftPowerEventNotFoundError: If no events found
    """
    logger.info(
        f"Searching for TdZ Stage {stage_number} ({route_name}) "
        f"events between {start_date} and {end_date}"
    )

    # Use pre-loaded events if provided (ELT pattern)
    if preloaded_events is not None:
        logger.info(f"Using {len(preloaded_events)} pre-loaded events")
        events = preloaded_events
    else:
        # Calculate days to look back
        days_since_start = (date.today() - start_date).days + 1
        days_to_search = min(max(days_since_start, 7), 14)

        # Search using the API (uses cached events list)
        events = search_events_api(client, "Tour de Zwift", days=days_to_search)

        # Also search for "Stage X" specifically
        if not events:
            events = search_events_api(
                client, f"Stage {stage_number}", days=days_to_search
            )

        if not events:
            # Fall back to HTML search
            logger.info("API search found no events, trying HTML search")
            events = search_events_html(client, "Tour de Zwift", start_date, end_date)

    # Filter for events matching this stage
    events_with_timestamps: list[tuple[str, datetime | None]] = []
    scored_events = []

    stage_pattern = f"stage {stage_number}"
    start_ts = datetime.combine(start_date, datetime.min.time()).timestamp()
    end_ts = datetime.combine(end_date, datetime.max.time()).timestamp()

    for event in events:
        event_name = event.get("name", "").lower()
        event_ts = event.get("timestamp", 0)
        score = 0

        # Must match stage number
        if stage_pattern not in event_name:
            continue

        # Score based on various criteria
        if "tour de zwift" in event_name:
            score += 2
        if route_name and route_name.lower() in event_name:
            score += 5
        # Include ALL event types (races and rides)
        # Race filtering happens later in the processor based on stage config
        # Penalize "Advanced" events (different route/distance)
        if "advanced" in event_name:
            score -= 2
        # Penalize run events
        if "run" in event_name:
            score -= 10

        # Check timestamp if available
        if event_ts:
            if start_ts <= event_ts <= end_ts:
                score += 3  # In date range
            elif event_ts < start_ts or event_ts > end_ts:
                score -= 5  # Outside date range

        if score > 0:
            scored_events.append((event, score))
            logger.debug(
                f"Candidate event (score={score}): {event['name']} ({event['id']})"
            )

    # Sort by score descending
    scored_events.sort(key=lambda x: x[1], reverse=True)

    # Get unique event IDs with timestamps
    seen_ids = set()
    for event, _score in scored_events:
        event_id = event["id"]
        if event_id not in seen_ids:
            # Convert timestamp to datetime
            event_ts = event.get("timestamp", 0)
            event_datetime = (
                datetime.fromtimestamp(event_ts, tz=UTC) if event_ts else None
            )
            events_with_timestamps.append((event_id, event_datetime))
            seen_ids.add(event_id)

    if not events_with_timestamps:
        # Include any Stage X TdZ events as fallback
        for event in events:
            event_name = event.get("name", "").lower()

            # Include ALL event types (races and rides), exclude only run events
            if (
                stage_pattern in event_name
                and "run" not in event_name
                and event["id"] not in seen_ids
            ):
                event_ts = event.get("timestamp", 0)
                event_datetime = (
                    datetime.fromtimestamp(event_ts, tz=UTC) if event_ts else None
                )
                events_with_timestamps.append((event["id"], event_datetime))
                seen_ids.add(event["id"])

    if not events_with_timestamps:
        raise ZwiftPowerEventNotFoundError(
            f"No TdZ events found for Stage {stage_number}"
        )

    logger.info(
        f"Found {len(events_with_timestamps)} event IDs for Stage {stage_number}"
    )
    return events_with_timestamps


def get_event_details(
    client: ZwiftPowerClient,
    event_id: str,
) -> dict:
    """
    Get detailed information about an event.

    Args:
        client: ZwiftPower client
        event_id: ZwiftPower event ID

    Returns:
        Event details dictionary
    """
    logger.info(f"Fetching details for event {event_id}")

    soup = client.get_html("/events.php", params={"zid": event_id})

    # Parse event header info
    # Try multiple methods to find the event title
    title = None

    # Method 1: Look for h2 tag
    title_elem = soup.find("h2")
    if title_elem:
        title = title_elem.get_text(strip=True)

    # Method 2: Parse from page title tag (format: "ZwiftPower - Event Name")
    if not title or title.startswith("Event "):
        page_title = soup.find("title")
        if page_title:
            page_title_text = page_title.get_text(strip=True)
            # Remove "ZwiftPower" prefix if present
            # Format can be: "ZwiftPower - Event Name" or "ZwiftPower -  Event Name" (extra space)
            if page_title_text.lower().startswith("zwiftpower"):
                # Remove "ZwiftPower" and any following " - " or " -  "
                title_without_prefix = page_title_text[len("zwiftpower") :].strip()
                if title_without_prefix.startswith("-"):
                    title_without_prefix = title_without_prefix[1:].strip()
                if title_without_prefix and not title_without_prefix.lower().startswith(
                    "login"
                ):
                    title = title_without_prefix

    # Fallback to generic title
    if not title:
        title = f"Event {event_id}"

    # Look for route and distance info
    route = ""
    distance = ""
    details = soup.find("div", class_="event-details")
    if details:
        text = details.get_text()
        route_match = re.search(r"Route:\s*(.+?)(?:\n|$)", text)
        if route_match:
            route = route_match.group(1).strip()
        dist_match = re.search(r"(\d+\.?\d*)\s*km", text)
        if dist_match:
            distance = dist_match.group(0)

    return {
        "id": event_id,
        "title": title,
        "route": route,
        "distance": distance,
    }


def _parse_date(date_str: str) -> date | None:
    """Parse date string from ZwiftPower."""
    date_str = date_str.strip()

    # Try various date formats
    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d %b %Y",
        "%b %d, %Y",
        "%Y-%m-%dT%H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    return None
