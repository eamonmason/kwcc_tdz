"""GC standings data models."""

from pydantic import BaseModel, Field, computed_field

from src.models.result import format_time


class GCStanding(BaseModel):
    """General Classification standing for a rider."""

    rider_name: str = Field(..., description="Rider display name")
    rider_id: str = Field(..., description="ZwiftPower user ID")
    race_group: str = Field(..., pattern=r"^([AB]|Women)$")
    handicap_group: str = Field(..., pattern=r"^[AB][1-4]$")
    total_adjusted_time_seconds: int = Field(..., ge=0)
    stages_completed: int = Field(..., ge=0, le=7)
    stage_times: dict[str, int] = Field(
        default_factory=dict,
        description="Stage number (str) -> stage time (raw + penalty) in seconds",
    )
    stage_event_ids: dict[str, str] = Field(
        default_factory=dict,
        description="Stage number (str) -> ZwiftPower event ID",
    )
    position: int = Field(default=0, ge=0)  # Set after sorting
    gap_to_leader: int = Field(default=0, ge=0)
    is_provisional: bool = Field(default=True)
    guest: bool = Field(
        default=False,
        description="Guest rider (non-club member)",
    )
    is_dns: bool = Field(
        default=False,
        description="DNS for current stage (completed all prior stages)",
    )

    @computed_field
    @property
    def total_time_display(self) -> str:
        """Format total time as HH:MM:SS."""
        return format_time(self.total_adjusted_time_seconds)

    @computed_field
    @property
    def gap_display(self) -> str:
        """Format gap to leader."""
        if self.gap_to_leader == 0:
            return "-"
        return f"+{format_time(self.gap_to_leader)}"

    @computed_field
    @property
    def handicap_display(self) -> str:
        """Short handicap group display."""
        return self.handicap_group

    def get_stage_time_display(self, stage: str) -> str:
        """Get formatted time for a specific stage."""
        if stage in self.stage_times:
            return format_time(self.stage_times[stage])
        return "DNS"


class GCStandings(BaseModel):
    """Collection of GC standings for a race group."""

    race_group: str = Field(..., pattern=r"^([AB]|Women)$")
    standings: list[GCStanding] = Field(default_factory=list)
    total_stages: int = Field(default=7)
    completed_stages: int = Field(default=0, ge=0, le=7)
    last_updated: str | None = Field(default=None)
    is_provisional: bool = Field(default=True)

    @property
    def leader(self) -> GCStanding | None:
        """Get the current leader."""
        if self.standings:
            return self.standings[0]
        return None

    def get_by_rider_id(self, rider_id: str) -> GCStanding | None:
        """Find standing by rider ID."""
        for standing in self.standings:
            if standing.rider_id == rider_id:
                return standing
        return None


class TourStandings(BaseModel):
    """Complete tour standings including both groups."""

    group_a: GCStandings = Field(default_factory=lambda: GCStandings(race_group="A"))
    group_b: GCStandings = Field(default_factory=lambda: GCStandings(race_group="B"))
    last_updated: str | None = Field(default=None)
    current_stage: str = Field(default="1", pattern=r"^[1-6](\.[12])?$")
    active_stages: list[str] = Field(
        default_factory=list,
        description="All currently active stage numbers (for concurrent stages)",
    )
    is_stage_in_progress: bool = Field(
        default=False,
        description="Whether a stage is currently active (based on stage dates)",
    )

    @property
    def is_provisional(self) -> bool:
        """Tour is provisional if any group is provisional."""
        return self.group_a.is_provisional or self.group_b.is_provisional
