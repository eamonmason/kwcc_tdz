"""ZwiftPower data fetching."""

from src.fetcher.client import ZwiftPowerClient
from src.fetcher.events import (
    find_tdz_race_events,
    find_tdz_race_events_with_timestamps,
    get_event_details,
    search_events,
)
from src.fetcher.exceptions import (
    ZwiftPowerAuthError,
    ZwiftPowerConnectionError,
    ZwiftPowerError,
    ZwiftPowerEventNotFoundError,
    ZwiftPowerParseError,
    ZwiftPowerRateLimitError,
)
from src.fetcher.results import (
    fetch_event_results,
    fetch_stage_results,
)

__all__ = [
    "ZwiftPowerClient",
    "search_events",
    "find_tdz_race_events",
    "find_tdz_race_events_with_timestamps",
    "get_event_details",
    "fetch_event_results",
    "fetch_stage_results",
    "ZwiftPowerError",
    "ZwiftPowerAuthError",
    "ZwiftPowerRateLimitError",
    "ZwiftPowerEventNotFoundError",
    "ZwiftPowerConnectionError",
    "ZwiftPowerParseError",
]
