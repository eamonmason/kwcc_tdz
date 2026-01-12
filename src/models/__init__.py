"""Data models for KWCC Tour de Zwift."""

from src.models.penalty import (
    DEFAULT_PENALTY_CONFIG,
    PenaltyConfig,
    PenaltyEvent,
    calculate_penalty_from_events,
    format_penalty,
)
from src.models.result import RaceResult, StageResult, format_time, parse_time
from src.models.rider import HANDICAPS, Rider, RiderRegistry
from src.models.standings import GCStanding, GCStandings, TourStandings
from src.models.tour import (
    DEFAULT_COURSE_PENALTY_EVENTS,
    DEFAULT_TOUR_REGISTRY,
    TOUR_STAGES,
    Course,
    Stage,
    TourConfig,
    TourRegistry,
)

__all__ = [  # noqa: RUF022
    # Rider models
    "Rider",
    "RiderRegistry",
    "HANDICAPS",
    # Result models
    "RaceResult",
    "StageResult",
    "format_time",
    "parse_time",
    # Penalty models
    "PenaltyConfig",
    "PenaltyEvent",
    "DEFAULT_PENALTY_CONFIG",
    "format_penalty",
    "calculate_penalty_from_events",
    # Standings models
    "GCStanding",
    "GCStandings",
    "TourStandings",
    # Tour models
    "Course",
    "Stage",
    "TourConfig",
    "TourRegistry",
    "TOUR_STAGES",
    "DEFAULT_TOUR_REGISTRY",
    "DEFAULT_COURSE_PENALTY_EVENTS",
]
