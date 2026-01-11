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
    "ZwiftPowerAuthError",
    "ZwiftPowerClient",
    "ZwiftPowerConnectionError",
    "ZwiftPowerError",
    "ZwiftPowerEventNotFoundError",
    "ZwiftPowerParseError",
    "ZwiftPowerRateLimitError",
    "fetch_event_results",
    "fetch_stage_results",
    "find_tdz_race_events",
    "find_tdz_race_events_with_timestamps",
    "get_event_details",
    "search_events",
]
