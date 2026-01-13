"""Tests for manual result entry and merging functionality."""

from datetime import datetime

from src.lambda_handlers.processor import merge_results
from src.models import StageResult


class TestMergeResults:
    """Tests for merge_results function."""

    def _create_stage_result(
        self,
        rider_id: str,
        rider_name: str,
        raw_time_seconds: int,
        event_id: str = "auto_event",
    ) -> StageResult:
        """Helper to create a StageResult for testing."""
        return StageResult(
            rider_name=rider_name,
            rider_id=rider_id,
            stage_number=1,
            race_group="B",
            handicap_group="B3",
            raw_time_seconds=raw_time_seconds,
            handicap_seconds=240,
            penalty_seconds=0,
            raw_position=1,
            position=1,
            event_id=event_id,
            timestamp=datetime(2026, 1, 13, 17, 0, 0),
        )

    def test_merge_adds_new_rider(self):
        """Manual result for a new rider is added to automatic results."""
        automatic = [
            self._create_stage_result("111", "Existing Rider", 2400),
        ]
        manual = [
            self._create_stage_result(
                "999", "Laura McMullen", 2850, event_id="manual:strava:123"
            ),
        ]

        merged = merge_results(automatic, manual)

        assert len(merged) == 2
        rider_ids = {r.rider_id for r in merged}
        assert "111" in rider_ids
        assert "999" in rider_ids

        # Verify the manual rider's data is correct
        laura = next(r for r in merged if r.rider_id == "999")
        assert laura.rider_name == "Laura McMullen"
        assert laura.raw_time_seconds == 2850
        assert laura.event_id == "manual:strava:123"

    def test_merge_overrides_existing_rider(self):
        """Manual result overrides automatic result for the same rider."""
        automatic = [
            self._create_stage_result("111", "Rider A", 2400, event_id="auto_event"),
            self._create_stage_result(
                "222", "Rider B (auto)", 2500, event_id="auto_event"
            ),
        ]
        manual = [
            # Override Rider B with corrected time
            self._create_stage_result(
                "222", "Rider B (manual)", 2450, event_id="manual:correction"
            ),
        ]

        merged = merge_results(automatic, manual)

        assert len(merged) == 2

        # Rider A should be unchanged
        rider_a = next(r for r in merged if r.rider_id == "111")
        assert rider_a.rider_name == "Rider A"
        assert rider_a.raw_time_seconds == 2400

        # Rider B should have manual data
        rider_b = next(r for r in merged if r.rider_id == "222")
        assert rider_b.rider_name == "Rider B (manual)"
        assert rider_b.raw_time_seconds == 2450
        assert rider_b.event_id == "manual:correction"

    def test_merge_empty_automatic(self):
        """Manual results work when automatic list is empty."""
        automatic: list[StageResult] = []
        manual = [
            self._create_stage_result("999", "Laura McMullen", 2850),
        ]

        merged = merge_results(automatic, manual)

        assert len(merged) == 1
        assert merged[0].rider_id == "999"

    def test_merge_empty_manual(self):
        """Automatic results unchanged when manual list is empty."""
        automatic = [
            self._create_stage_result("111", "Rider A", 2400),
            self._create_stage_result("222", "Rider B", 2500),
        ]
        manual: list[StageResult] = []

        merged = merge_results(automatic, manual)

        assert len(merged) == 2
        assert {r.rider_id for r in merged} == {"111", "222"}

    def test_merge_both_empty(self):
        """Empty lists return empty result."""
        automatic: list[StageResult] = []
        manual: list[StageResult] = []

        merged = merge_results(automatic, manual)

        assert merged == []

    def test_merge_multiple_manual_riders(self):
        """Multiple manual riders can be added at once."""
        automatic = [
            self._create_stage_result("111", "Rider A", 2400),
        ]
        manual = [
            self._create_stage_result("222", "Manual Rider 1", 2500),
            self._create_stage_result("333", "Manual Rider 2", 2600),
        ]

        merged = merge_results(automatic, manual)

        assert len(merged) == 3
        rider_ids = {r.rider_id for r in merged}
        assert rider_ids == {"111", "222", "333"}

    def test_merge_preserves_all_fields(self):
        """All StageResult fields are preserved in merge."""
        automatic: list[StageResult] = []
        manual = [
            StageResult(
                rider_name="Laura McMullen",
                rider_id="999",
                stage_number=1,
                race_group="B",
                handicap_group="B3",
                raw_time_seconds=2850,
                handicap_seconds=240,
                penalty_seconds=60,
                penalty_reason="Monday 17:00 UTC event",
                raw_position=5,
                position=3,
                gap_to_leader=120,
                is_provisional=False,
                event_id="manual:strava:123456",
                timestamp=datetime(2026, 1, 13, 17, 0, 0),
                guest=False,
                gender="F",
            ),
        ]

        merged = merge_results(automatic, manual)

        assert len(merged) == 1
        result = merged[0]

        # Verify all fields preserved
        assert result.rider_name == "Laura McMullen"
        assert result.rider_id == "999"
        assert result.stage_number == 1
        assert result.race_group == "B"
        assert result.handicap_group == "B3"
        assert result.raw_time_seconds == 2850
        assert result.handicap_seconds == 240
        assert result.penalty_seconds == 60
        assert result.penalty_reason == "Monday 17:00 UTC event"
        assert result.raw_position == 5
        assert result.position == 3
        assert result.gap_to_leader == 120
        assert result.is_provisional is False
        assert result.event_id == "manual:strava:123456"
        assert result.timestamp == datetime(2026, 1, 13, 17, 0, 0)
        assert result.guest is False
        assert result.gender == "F"
