"""Penalty configuration for specific events."""

from datetime import datetime, time

from pydantic import BaseModel, Field


class PenaltyEvent(BaseModel):
    """Definition of an event that carries a time penalty."""

    event_time_utc: time = Field(..., description="Event start time in UTC")
    day_of_week: int = Field(
        ..., ge=0, le=6, description="Day of week (0=Monday, 6=Sunday)"
    )
    penalty_seconds: int = Field(..., ge=0, description="Penalty time in seconds")
    description: str = Field(default="", description="Description of the penalty")


class PenaltyConfig(BaseModel):
    """Configuration for event penalties."""

    # Week numbers (1-6) where penalties are disabled
    penalty_free_weeks: list[int] = Field(
        default_factory=list,
        description="Stage numbers where penalties don't apply",
    )

    # Penalty events
    penalty_events: list[PenaltyEvent] = Field(
        default_factory=list,
        description="List of penalty events",
    )

    def get_penalty(
        self,
        event_datetime: datetime,
        stage_number: int,
    ) -> int:
        """
        Get penalty in seconds for an event.

        Args:
            event_datetime: DateTime of the event
            stage_number: Current stage number

        Returns:
            Penalty in seconds (0 if no penalty applies)
        """
        # Check if this stage has penalties disabled
        if stage_number in self.penalty_free_weeks:
            return 0

        event_day = event_datetime.weekday()
        event_time = event_datetime.time()

        for penalty_event in self.penalty_events:
            if penalty_event.day_of_week != event_day:
                continue

            # Check if event time is within 15 minutes of penalty event time
            penalty_start = datetime.combine(
                event_datetime.date(), penalty_event.event_time_utc
            )
            event_dt = datetime.combine(event_datetime.date(), event_time)

            time_diff = abs((event_dt - penalty_start).total_seconds())

            # Allow 15 minute tolerance for event start times
            if time_diff <= 900:  # 15 minutes
                return penalty_event.penalty_seconds

        return 0


# Default penalty configuration
# Monday (day 0) 5pm and 6pm UTC events have 1 minute penalty
DEFAULT_PENALTY_CONFIG = PenaltyConfig(
    penalty_free_weeks=[],  # Configure which weeks have no penalties
    penalty_events=[
        PenaltyEvent(
            event_time_utc=time(17, 0),  # 5pm UTC
            day_of_week=0,  # Monday
            penalty_seconds=60,  # 1 minute
            description="Monday 5pm UTC - 1 min penalty",
        ),
        PenaltyEvent(
            event_time_utc=time(18, 0),  # 6pm UTC
            day_of_week=0,  # Monday
            penalty_seconds=60,  # 1 minute
            description="Monday 6pm UTC - 1 min penalty",
        ),
    ],
)


def format_penalty(seconds: int) -> str:
    """Format penalty seconds for display."""
    if seconds == 0:
        return ""
    minutes = seconds // 60
    if minutes == 0:
        return f"+{seconds}s"
    return f"+{minutes}m"
