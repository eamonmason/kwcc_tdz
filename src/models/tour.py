"""Tour de Zwift stage configuration."""

from datetime import UTC, date, datetime, time

from pydantic import BaseModel, Field, computed_field

from src.models.penalty import PenaltyEvent


class Course(BaseModel):
    """A course within a Tour de Zwift stage."""

    route: str = Field(..., description="Route name")
    distance_km: float = Field(..., gt=0)
    elevation_m: int = Field(..., ge=0)
    option_letter: str = Field(
        default="C",
        pattern="^[A-E]$",
        description="Event option letter (A, B, C, D, or E)",
    )
    zwiftinsider_url: str | None = Field(
        default=None, description="Link to Zwiftinsider route description"
    )
    zwiftpower_search_url: str | None = Field(
        default=None, description="Link to ZwiftPower upcoming events for this route"
    )
    event_ids: list[str] = Field(
        default_factory=list, description="ZwiftPower event IDs for this course"
    )
    penalty_events: list[PenaltyEvent] = Field(
        default_factory=list, description="Penalty events specific to this course"
    )

    @property
    def has_penalties(self) -> bool:
        """Check if this course has any penalty events."""
        return len(self.penalty_events) > 0


class Stage(BaseModel):
    """Tour de Zwift stage configuration."""

    number: int = Field(..., ge=1, le=6)
    name: str = Field(..., description="World/location name")
    courses: list[Course] = Field(
        default_factory=list, description="List of courses for this stage"
    )
    # Use datetime for precise stage boundaries (events start/end at specific times)
    start_datetime: datetime = Field(..., description="First event start time (UTC)")
    end_datetime: datetime = Field(..., description="Last event end time (UTC)")

    # Legacy fields for backwards compatibility (single-course stages)
    route: str | None = Field(default=None, description="Route name (deprecated)")
    distance_km: float | None = Field(default=None, description="(deprecated)")
    elevation_m: int | None = Field(default=None, description="(deprecated)")
    event_ids: list[str] = Field(
        default_factory=list, description="ZwiftPower event IDs (deprecated)"
    )

    @property
    def is_active(self) -> bool:
        """Check if stage is currently active."""
        now = datetime.now(UTC)
        return self.start_datetime <= now <= self.end_datetime

    @property
    def is_complete(self) -> bool:
        """Check if stage has ended."""
        now = datetime.now(UTC)
        return now > self.end_datetime

    @property
    def is_upcoming(self) -> bool:
        """Check if stage hasn't started yet."""
        now = datetime.now(UTC)
        return now < self.start_datetime

    @property
    def start_date(self) -> date:
        """Get start date (for display/backwards compatibility)."""
        return self.start_datetime.date()

    @property
    def end_date(self) -> date:
        """Get end date (for display/backwards compatibility)."""
        return self.end_datetime.date()

    @property
    def primary_course(self) -> Course | None:
        """Get the primary (first) course for this stage."""
        if self.courses:
            return self.courses[0]
        # Legacy fallback
        if self.route:
            return Course(
                route=self.route,
                distance_km=self.distance_km or 0,
                elevation_m=self.elevation_m or 0,
                event_ids=self.event_ids,
            )
        return None

    @property
    def all_event_ids(self) -> list[str]:
        """Get all event IDs across all courses."""
        ids = []
        for course in self.courses:
            ids.extend(course.event_ids)
        # Include legacy event_ids
        ids.extend(self.event_ids)
        return ids

    @property
    def is_multi_course(self) -> bool:
        """Check if this stage has multiple courses."""
        return len(self.courses) > 1

    @property
    def display_route(self) -> str:
        """Get display route name (primary course or legacy)."""
        if self.courses:
            return self.courses[0].route
        return self.route or ""

    @property
    def display_distance_km(self) -> float:
        """Get display distance (primary course or legacy)."""
        if self.courses:
            return self.courses[0].distance_km
        return self.distance_km or 0

    @property
    def display_elevation_m(self) -> int:
        """Get display elevation (primary course or legacy)."""
        if self.courses:
            return self.courses[0].elevation_m
        return self.elevation_m or 0

    def get_course_for_event(self, event_id: str) -> Course | None:
        """Find which course an event_id belongs to."""
        for course in self.courses:
            if event_id in course.event_ids:
                return course
        return None

    def get_penalty_events_for_event(self, event_id: str) -> list[PenaltyEvent]:
        """Get penalty events for a specific event_id's course."""
        course = self.get_course_for_event(event_id)
        if course:
            return course.penalty_events
        # Fallback to primary course penalties if event not found
        if self.courses:
            return self.courses[0].penalty_events
        return []


# Default penalty events for Monday 5pm and 6pm UTC
DEFAULT_COURSE_PENALTY_EVENTS: list[PenaltyEvent] = [
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
]


# Tour de Zwift 2026 stage configuration
# Each stage starts at 5pm UTC on start day and ends at 4:59pm UTC on transition day
# (last events finish around 4pm, next stage starts at 5pm same day)
TOUR_STAGES: list[Stage] = [
    Stage(
        number=1,
        name="Makuri Islands",
        courses=[
            Course(
                route="Turf N Surf",
                distance_km=24.7,
                elevation_m=198,
                option_letter="C",
                zwiftinsider_url="https://zwiftinsider.com/route/turf-n-surf/",
                zwiftpower_search_url="https://zwiftpower.com/events.php?search=tour+de+zwift+stage+1",
                penalty_events=DEFAULT_COURSE_PENALTY_EVENTS,
            ),
        ],
        start_datetime=datetime(2026, 1, 5, 17, 0, tzinfo=UTC),  # 5pm UTC
        end_datetime=datetime(2026, 1, 12, 16, 59, tzinfo=UTC),  # 4:59pm UTC
    ),
    Stage(
        number=2,
        name="France",
        courses=[
            Course(
                route="Hell of the North",
                distance_km=20.1,
                elevation_m=241,
                option_letter="C",
                zwiftinsider_url="https://zwiftinsider.com/route/hell-of-the-north/",
                zwiftpower_search_url="https://zwiftpower.com/events.php?search=tour+de+zwift+stage+2",
                penalty_events=DEFAULT_COURSE_PENALTY_EVENTS,
            ),
        ],
        start_datetime=datetime(2026, 1, 12, 17, 0, tzinfo=UTC),
        end_datetime=datetime(2026, 1, 19, 16, 59, tzinfo=UTC),
    ),
    Stage(
        number=3,
        name="Scotland/Yorkshire",
        courses=[
            Course(
                route="Yorkshire Double Loop",
                distance_km=0,
                elevation_m=0,
                option_letter="B",
                zwiftinsider_url="https://zwiftinsider.com/route/yorkshire-double-loop/",
                zwiftpower_search_url="https://zwiftpower.com/events.php?search=tour+de+zwift+stage+3",
                penalty_events=[],  # No penalties for this course
            ),
            Course(
                route="BRAE-k Fast",
                distance_km=22.1,
                elevation_m=243,
                option_letter="C",
                zwiftinsider_url="https://zwiftinsider.com/route/brae-k-fast/",
                zwiftpower_search_url="https://zwiftpower.com/events.php?search=tour+de+zwift+stage+3",
                penalty_events=[],
            ),
        ],
        start_datetime=datetime(2026, 1, 19, 17, 0, tzinfo=UTC),
        end_datetime=datetime(2026, 1, 26, 16, 59, tzinfo=UTC),
    ),
    Stage(
        number=4,
        name="London",
        courses=[
            Course(
                route="Triple Loops",
                distance_km=20.9,
                elevation_m=223,
                option_letter="A",
                zwiftinsider_url="https://zwiftinsider.com/route/triple-loops/",
                zwiftpower_search_url="https://zwiftpower.com/events.php?search=tour+de+zwift+stage+4",
                penalty_events=DEFAULT_COURSE_PENALTY_EVENTS,
            ),
        ],
        start_datetime=datetime(2026, 1, 26, 17, 0, tzinfo=UTC),
        end_datetime=datetime(2026, 2, 2, 16, 59, tzinfo=UTC),
    ),
    Stage(
        number=5,
        name="Watopia",
        courses=[
            Course(
                route="Glyph Heights",
                distance_km=19.3,
                elevation_m=157,
                option_letter="C",
                zwiftinsider_url="https://zwiftinsider.com/route/glyph-heights/",
                zwiftpower_search_url="https://zwiftpower.com/events.php?search=tour+de+zwift+stage+5",
                penalty_events=DEFAULT_COURSE_PENALTY_EVENTS,
            ),
        ],
        start_datetime=datetime(2026, 2, 2, 17, 0, tzinfo=UTC),
        end_datetime=datetime(2026, 2, 9, 16, 59, tzinfo=UTC),
    ),
    Stage(
        number=6,
        name="New York",
        courses=[
            Course(
                route="The Greenway",
                distance_km=36.2,
                elevation_m=290,
                option_letter="A",
                zwiftinsider_url="https://zwiftinsider.com/route/the-greenway/",
                zwiftpower_search_url="https://zwiftpower.com/events.php?search=tour+de+zwift+stage+6",
                penalty_events=DEFAULT_COURSE_PENALTY_EVENTS,
            ),
        ],
        start_datetime=datetime(2026, 2, 9, 17, 0, tzinfo=UTC),
        end_datetime=datetime(2026, 2, 16, 16, 59, tzinfo=UTC),
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
