"""Tour de Zwift stage configuration."""

from datetime import date

from pydantic import BaseModel, Field, computed_field


class Stage(BaseModel):
    """Tour de Zwift stage configuration."""

    number: int = Field(..., ge=1, le=6)
    name: str = Field(..., description="World/location name")
    route: str = Field(..., description="Route name")
    distance_km: float = Field(..., gt=0)
    elevation_m: int = Field(..., ge=0)
    start_date: date
    end_date: date
    event_ids: list[str] = Field(
        default_factory=list, description="ZwiftPower event IDs"
    )

    @property
    def is_active(self) -> bool:
        """Check if stage is currently active."""
        today = date.today()
        return self.start_date <= today <= self.end_date

    @property
    def is_complete(self) -> bool:
        """Check if stage has ended."""
        return date.today() > self.end_date

    @property
    def is_upcoming(self) -> bool:
        """Check if stage hasn't started yet."""
        return date.today() < self.start_date


# Tour de Zwift 2026 stage configuration
TOUR_STAGES: list[Stage] = [
    Stage(
        number=1,
        name="Makuri Islands",
        route="Turf N Surf",
        distance_km=24.7,
        elevation_m=198,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 11),
        event_ids=[],
    ),
    Stage(
        number=2,
        name="France",
        route="Hell of the North",
        distance_km=20.1,
        elevation_m=241,
        start_date=date(2026, 1, 12),
        end_date=date(2026, 1, 18),
        event_ids=[],
    ),
    Stage(
        number=3,
        name="Scotland",
        route="BRAE-k Fast",
        distance_km=22.1,
        elevation_m=243,
        start_date=date(2026, 1, 19),
        end_date=date(2026, 1, 25),
        event_ids=[],
    ),
    Stage(
        number=4,
        name="London",
        route="London 8",
        distance_km=20.9,
        elevation_m=223,
        start_date=date(2026, 1, 26),
        end_date=date(2026, 2, 1),
        event_ids=[],
    ),
    Stage(
        number=5,
        name="Watopia",
        route="Ocean Lava Cliffside Loop",
        distance_km=19.3,
        elevation_m=157,
        start_date=date(2026, 2, 2),
        end_date=date(2026, 2, 8),
        event_ids=[],
    ),
    Stage(
        number=6,
        name="Richmond",
        route="Richmond Rollercoaster",
        distance_km=17.0,
        elevation_m=169,
        start_date=date(2026, 2, 9),
        end_date=date(2026, 2, 15),
        event_ids=[],
    ),
]


class TourConfig(BaseModel):
    """Tour de Zwift configuration."""

    tour_id: str = Field(default="tdz-2026", description="Unique tour identifier")
    year: int = Field(default=2026, ge=2020, description="Tour year")
    name: str = Field(default="Tour de Zwift 2026")
    stages: list[Stage] = Field(default_factory=lambda: TOUR_STAGES.copy())
    makeup_week_start: date = Field(default=date(2026, 2, 16))
    makeup_week_end: date = Field(default=date(2026, 2, 22))
    is_archived: bool = Field(default=False, description="Whether tour is archived")

    @computed_field
    @property
    def results_prefix(self) -> str:
        """S3 prefix for tour results storage."""
        return f"results/{self.tour_id}"

    @computed_field
    @property
    def config_prefix(self) -> str:
        """S3 prefix for tour config storage."""
        return f"config/{self.tour_id}"

    def get_stage(self, number: int) -> Stage | None:
        """Get stage by number."""
        for stage in self.stages:
            if stage.number == number:
                return stage
        return None

    @property
    def current_stage(self) -> Stage | None:
        """Get the currently active stage."""
        for stage in self.stages:
            if stage.is_active:
                return stage
        return None

    @property
    def completed_stages(self) -> list[Stage]:
        """Get all completed stages."""
        return [s for s in self.stages if s.is_complete]

    @property
    def upcoming_stages(self) -> list[Stage]:
        """Get all upcoming stages."""
        return [s for s in self.stages if s.is_upcoming]

    @property
    def is_makeup_week(self) -> bool:
        """Check if we're in makeup week."""
        today = date.today()
        return self.makeup_week_start <= today <= self.makeup_week_end

    @property
    def is_current(self) -> bool:
        """Check if this tour is the current one (not archived and has active/upcoming stages)."""
        if self.is_archived:
            return False
        return bool(self.current_stage or self.upcoming_stages)


class TourRegistry(BaseModel):
    """Registry of all tours (past and present)."""

    tours: list[TourConfig] = Field(default_factory=list)
    default_tour_id: str | None = Field(
        default=None, description="Default tour to display"
    )

    def get_tour(self, tour_id: str) -> TourConfig | None:
        """Get tour by ID."""
        for tour in self.tours:
            if tour.tour_id == tour_id:
                return tour
        return None

    def get_tour_by_year(self, year: int) -> TourConfig | None:
        """Get tour by year."""
        for tour in self.tours:
            if tour.year == year:
                return tour
        return None

    @property
    def current_tour(self) -> TourConfig | None:
        """Get the current active tour."""
        for tour in self.tours:
            if tour.is_current:
                return tour
        return None

    @property
    def archived_tours(self) -> list[TourConfig]:
        """Get all archived tours."""
        return [t for t in self.tours if t.is_archived]

    @property
    def available_years(self) -> list[int]:
        """Get list of available tour years."""
        return sorted([t.year for t in self.tours], reverse=True)

    def add_tour(self, tour: TourConfig) -> None:
        """Add a tour to the registry."""
        # Remove existing tour with same ID if present
        self.tours = [t for t in self.tours if t.tour_id != tour.tour_id]
        self.tours.append(tour)
        # Sort by year (newest first)
        self.tours.sort(key=lambda t: t.year, reverse=True)


# Default registry with TdZ 2026
DEFAULT_TOUR_REGISTRY = TourRegistry(
    tours=[TourConfig()],
    default_tour_id="tdz-2026",
)
