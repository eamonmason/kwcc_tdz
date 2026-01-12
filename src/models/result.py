"""Race and stage result data models."""

from datetime import datetime

from pydantic import BaseModel, Field, computed_field


class RaceResult(BaseModel):
    """Raw race result from ZwiftPower."""

    rider_id: str = Field(..., description="ZwiftPower user ID")
    rider_name: str = Field(..., description="Rider name from ZwiftPower")
    stage_number: int = Field(..., ge=1, le=6, description="Stage number (1-6)")
    event_id: str = Field(..., description="ZwiftPower event ID")
    raw_time_seconds: int = Field(..., ge=0, description="Finish time in seconds")
    finish_position: int = Field(..., ge=1, description="Position in race")
    timestamp: datetime = Field(..., description="Race completion timestamp")
    category: str = Field(default="C", description="Race category")
    power_avg: float | None = Field(default=None, description="Average power (watts)")
    power_20min: float | None = Field(default=None, description="20-min power (watts)")
    heart_rate_avg: int | None = Field(default=None, description="Average heart rate")

    @computed_field
    @property
    def raw_time_display(self) -> str:
        """Format raw time as HH:MM:SS."""
        return format_time(self.raw_time_seconds)


class StageResult(BaseModel):
    """Processed stage result with handicap and penalty applied."""

    rider_name: str = Field(..., description="Rider display name")
    rider_id: str = Field(..., description="ZwiftPower user ID")
    stage_number: int = Field(..., ge=1, le=6)
    race_group: str | None = Field(default=None, pattern=r"^[AB]$")
    handicap_group: str | None = Field(default=None, pattern=r"^[AB][1-4]$")
    raw_time_seconds: int = Field(..., ge=0)
    handicap_seconds: int = Field(..., ge=0)
    penalty_seconds: int = Field(default=0, ge=0, description="Event penalty time")
    penalty_reason: str = Field(default="", description="Reason for penalty")
    position: int = Field(default=0, ge=0, description="Position after adjustments")
    raw_position: int = Field(..., ge=1, description="Raw finish position")
    gap_to_leader: int = Field(default=0, ge=0, description="Gap in seconds")
    is_provisional: bool = Field(default=False)
    event_id: str = Field(default="")
    timestamp: datetime | None = Field(default=None)
    guest: bool = Field(
        default=False,
        description="Guest rider (non-club member, excluded from GC by default)",
    )

    @computed_field
    @property
    def adjusted_time_seconds(self) -> int:
        """Total time with handicap and penalty added."""
        return self.raw_time_seconds + self.handicap_seconds + self.penalty_seconds

    @computed_field
    @property
    def raw_time_display(self) -> str:
        """Format raw time as HH:MM:SS."""
        return format_time(self.raw_time_seconds)

    @computed_field
    @property
    def adjusted_time_display(self) -> str:
        """Format adjusted time as HH:MM:SS."""
        return format_time(self.adjusted_time_seconds)

    @computed_field
    @property
    def handicap_display(self) -> str:
        """Format handicap time."""
        if self.handicap_group is None:
            return "uncat"
        minutes = self.handicap_seconds // 60
        if minutes == 0:
            return "scratch"
        return f"+{minutes}m"

    @computed_field
    @property
    def penalty_display(self) -> str:
        """Format penalty time."""
        if self.penalty_seconds == 0:
            return ""
        minutes = self.penalty_seconds // 60
        if minutes == 0:
            return f"+{self.penalty_seconds}s"
        return f"+{minutes}m"

    @computed_field
    @property
    def has_penalty(self) -> bool:
        """Check if result has a penalty."""
        return self.penalty_seconds > 0

    @computed_field
    @property
    def gap_display(self) -> str:
        """Format gap to leader."""
        if self.gap_to_leader == 0:
            return "-"
        return f"+{format_time(self.gap_to_leader)}"


def format_time(seconds: int) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def parse_time(time_str: str) -> int:
    """Parse time string (HH:MM:SS or MM:SS) to seconds."""
    parts = time_str.strip().split(":")
    if len(parts) == 3:
        hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    if len(parts) == 2:
        minutes, seconds = int(parts[0]), int(parts[1])
        return minutes * 60 + seconds
    raise ValueError(f"Invalid time format: {time_str}")
