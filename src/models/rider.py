"""Rider data model with handicap calculations."""

from pydantic import BaseModel, Field, computed_field

# Handicap times in seconds
HANDICAPS = {
    "A": {"A1": 600, "A2": 300, "A3": 0},  # 10 min, 5 min, 0 min
    "B": {"B1": 900, "B2": 600, "B3": 240, "B4": 0},  # 15 min, 10 min, 4 min, 0 min
}


class Rider(BaseModel):
    """A KWCC rider participating in Tour de Zwift."""

    name: str = Field(..., description="Rider's display name")
    zwiftpower_id: str = Field(..., description="ZwiftPower user ID")
    handicap_group: str | None = Field(
        default=None,
        description="Handicap group (A1-A3 or B1-B4, or None for uncategorized riders)",
    )
    zp_racing_score: int | None = Field(
        default=None, description="ZwiftPower Racing Score"
    )
    guest: bool = Field(
        default=False,
        description="Guest rider (non-club member, excluded from GC by default)",
    )

    @computed_field
    @property
    def race_group(self) -> str | None:
        """Extract race group (A or B) from handicap group."""
        if self.handicap_group is None:
            return None
        return self.handicap_group[0]

    @computed_field
    @property
    def handicap_seconds(self) -> int:
        """Get handicap time in seconds based on group."""
        if self.handicap_group is None:
            return 0
        group = self.race_group
        return HANDICAPS[group].get(self.handicap_group, 0)

    @computed_field
    @property
    def handicap_display(self) -> str:
        """Human-readable handicap time."""
        if self.handicap_group is None:
            return "uncategorized"
        minutes = self.handicap_seconds // 60
        if minutes == 0:
            return "scratch"
        return f"+{minutes} min"


class RiderRegistry(BaseModel):
    """Collection of all registered riders."""

    riders: list[Rider] = Field(default_factory=list)

    def get_by_zwiftpower_id(self, zp_id: str) -> Rider | None:
        """Find a rider by their ZwiftPower ID."""
        for rider in self.riders:
            if rider.zwiftpower_id == zp_id:
                return rider
        return None

    def get_by_name(self, name: str) -> Rider | None:
        """Find a rider by name (case-insensitive partial match)."""
        name_lower = name.lower()
        for rider in self.riders:
            if name_lower in rider.name.lower():
                return rider
        return None

    def get_group_riders(self, race_group: str) -> list[Rider]:
        """Get all riders in a race group (A or B)."""
        return [r for r in self.riders if r.race_group == race_group.upper()]

    @property
    def group_a_riders(self) -> list[Rider]:
        """All Group A riders."""
        return self.get_group_riders("A")

    @property
    def group_b_riders(self) -> list[Rider]:
        """All Group B riders."""
        return self.get_group_riders("B")

    def get_non_guest_riders(self) -> list[Rider]:
        """Get all non-guest (club member) riders."""
        return [r for r in self.riders if not r.guest]

    def get_guest_riders(self) -> list[Rider]:
        """Get all guest riders."""
        return [r for r in self.riders if r.guest]
