"""Stage results processing and management."""

import json
from datetime import datetime
from pathlib import Path

from src.models.result import StageResult
from src.models.standings import TourStandings
from src.processor.gc_standings import build_tour_standings


class StageResultsManager:
    """Manages stage results storage and retrieval."""

    def __init__(self, data_dir: str | Path):
        """
        Initialize the results manager.

        Args:
            data_dir: Directory for storing results data
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _results_file(self, stage: int, group: str) -> Path:
        """Get path to results file for a stage and group."""
        return self.data_dir / f"stage_{stage}_group_{group}.json"

    def save_stage_results(
        self,
        stage_number: int,
        group_a_results: list[StageResult],
        group_b_results: list[StageResult],
    ) -> None:
        """
        Save stage results to JSON files.

        Args:
            stage_number: Stage number
            group_a_results: Group A stage results
            group_b_results: Group B stage results
        """
        # Save Group A results
        a_file = self._results_file(stage_number, "A")
        with a_file.open("w", encoding="utf-8") as f:
            json.dump(
                [r.model_dump(mode="json") for r in group_a_results],
                f,
                indent=2,
                default=str,
            )

        # Save Group B results
        b_file = self._results_file(stage_number, "B")
        with b_file.open("w", encoding="utf-8") as f:
            json.dump(
                [r.model_dump(mode="json") for r in group_b_results],
                f,
                indent=2,
                default=str,
            )

    def load_stage_results(
        self,
        stage_number: int,
        group: str,
    ) -> list[StageResult]:
        """
        Load stage results from JSON file.

        Args:
            stage_number: Stage number
            group: Race group ("A" or "B")

        Returns:
            List of stage results, or empty list if not found
        """
        results_file = self._results_file(stage_number, group)
        if not results_file.exists():
            return []

        with results_file.open(encoding="utf-8") as f:
            data = json.load(f)

        return [StageResult.model_validate(r) for r in data]

    def load_all_results(
        self,
        max_stage: int = 6,
    ) -> tuple[dict[int, list[StageResult]], dict[int, list[StageResult]]]:
        """
        Load all stage results for both groups.

        Args:
            max_stage: Maximum stage number to load

        Returns:
            Tuple of (group_a_results, group_b_results) dicts
        """
        group_a_results: dict[int, list[StageResult]] = {}
        group_b_results: dict[int, list[StageResult]] = {}

        for stage in range(1, max_stage + 1):
            a_results = self.load_stage_results(stage, "A")
            if a_results:
                group_a_results[stage] = a_results

            b_results = self.load_stage_results(stage, "B")
            if b_results:
                group_b_results[stage] = b_results

        return group_a_results, group_b_results

    def get_completed_stages(self) -> list[int]:
        """
        Get list of stage numbers that have results.

        Returns:
            List of completed stage numbers
        """
        completed = []
        for stage in range(1, 7):
            a_file = self._results_file(stage, "A")
            b_file = self._results_file(stage, "B")
            if a_file.exists() or b_file.exists():
                completed.append(stage)
        return completed

    def build_current_standings(self) -> TourStandings:
        """
        Build current tour standings from all available results.

        Returns:
            Current tour standings
        """
        group_a_results, group_b_results = self.load_all_results()
        completed_stages = len(self.get_completed_stages())

        # Determine current stage (highest completed + 1, capped at 6)
        current_stage = min(completed_stages + 1, 6)

        last_updated = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

        return build_tour_standings(
            group_a_results,
            group_b_results,
            completed_stages,
            current_stage,
            last_updated,
        )
