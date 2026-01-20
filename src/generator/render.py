"""Jinja2 template rendering for website generation."""

import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.models.result import StageResult
from src.models.standings import TourStandings
from src.models.tour import STAGE_ORDER, TOTAL_STAGES, TourConfig


def create_jinja_env(template_dir: str | Path | None = None) -> Environment:
    """
    Create Jinja2 environment for template rendering.

    Args:
        template_dir: Path to templates directory

    Returns:
        Configured Jinja2 Environment
    """
    if template_dir is None:
        # Default to package templates directory
        template_dir = Path(__file__).parent / "templates"

    return Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


class WebsiteGenerator:
    """Generate static HTML website from results data."""

    def __init__(
        self,
        output_dir: str | Path,
        template_dir: str | Path | None = None,
        static_dir: str | Path | None = None,
        tour_name: str | None = None,
        available_years: list[int] | None = None,
        url_prefix: str = "",
        is_mock_data: bool = False,
    ):
        """
        Initialize website generator.

        Args:
            output_dir: Directory to write generated HTML files
            template_dir: Path to Jinja2 templates (defaults to package templates)
            static_dir: Path to static assets (CSS, JS, images)
            tour_name: Name of the tour (e.g., "Tour de Zwift 2026")
            available_years: List of available tour years for archive navigation
            url_prefix: URL prefix for archived tours (e.g., "/archive/tdz-2025/")
            is_mock_data: Whether results are mock/sample data (shows warning banner)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.env = create_jinja_env(template_dir)

        if static_dir is None:
            # Default to package static directory
            self.static_dir = Path(__file__).parent.parent.parent / "static"
        else:
            self.static_dir = Path(static_dir)

        # Tour information for templates
        self.tour_name = tour_name or "Tour de Zwift 2026"
        self.available_years = available_years or []
        self.url_prefix = url_prefix
        self.is_mock_data = is_mock_data

    def _get_base_context(self) -> dict:
        """Get base context for all templates."""
        return {
            "tour_name": self.tour_name,
            "available_years": self.available_years,
            "url_prefix": self.url_prefix,
            "is_mock_data": self.is_mock_data,
            "stage_order": STAGE_ORDER,
            "total_stages": TOTAL_STAGES,
        }

    def _render_template(self, template_name: str, context: dict) -> str:
        """Render a template with context (includes base context)."""
        template = self.env.get_template(template_name)
        # Merge base context with provided context
        full_context = {**self._get_base_context(), **context}
        return template.render(**full_context)

    def _write_html(self, filename: str, content: str) -> Path:
        """Write HTML content to file."""
        output_path = self.output_dir / filename
        output_path.write_text(content, encoding="utf-8")
        return output_path

    def copy_static_assets(self) -> None:
        """Copy static assets (CSS, JS, images) to output directory."""
        if not self.static_dir.exists():
            return

        for item in ["css", "js", "images"]:
            src_dir = self.static_dir / item
            if src_dir.exists():
                dst_dir = self.output_dir / item
                if dst_dir.exists():
                    shutil.rmtree(dst_dir)
                shutil.copytree(src_dir, dst_dir)

    def generate_index(
        self,
        tour_standings: TourStandings,
        tour_config: TourConfig,
        women_gc=None,
        stage_results: dict[
            str, tuple[list[StageResult], list[StageResult], list[StageResult]]
        ]
        | None = None,
    ) -> Path:
        """
        Generate index.html (homepage).

        Args:
            tour_standings: Current tour standings
            tour_config: Tour configuration
            women_gc: Women's GC standings (optional)
            stage_results: Stage results for position change calculation (optional)

        Returns:
            Path to generated file
        """
        # Get the next upcoming stage if any
        upcoming = tour_config.upcoming_stages
        next_stage = upcoming[0] if upcoming else None

        # Calculate position changes from previous stage
        position_changes_a = {}
        position_changes_b = {}
        position_changes_women = {}

        # Get previous stage number
        prev_stage_num, _ = tour_config.get_adjacent_stages(
            tour_standings.current_stage
        )

        if stage_results and prev_stage_num:
            from src.processor.gc_standings import (
                calculate_gc_standings,
                calculate_women_gc_standings,
            )

            # Build stage results dicts for previous stage GC calculation
            group_a_results: dict[str, list[StageResult]] = {}
            group_b_results: dict[str, list[StageResult]] = {}

            for stage_num, (group_a, group_b, _) in stage_results.items():
                group_a_results[stage_num] = group_a
                group_b_results[stage_num] = group_b

            # Calculate GC for previous stage
            completed_stages = tour_standings.group_a.completed_stages
            # Get the index of prev_stage in STAGE_ORDER for completed stages count
            try:
                prev_stage_idx = STAGE_ORDER.index(prev_stage_num)
                prev_completed = prev_stage_idx + 1  # 1-indexed count
            except ValueError:
                prev_completed = completed_stages

            prev_gc_a = calculate_gc_standings(
                group_a_results,
                "A",
                prev_completed,
                tour_standings.is_provisional,
                include_guests=True,
                target_stage=prev_stage_num,
                include_dns=False,
            )
            prev_gc_b = calculate_gc_standings(
                group_b_results,
                "B",
                prev_completed,
                tour_standings.is_provisional,
                include_guests=True,
                target_stage=prev_stage_num,
                include_dns=False,
            )
            prev_gc_women = calculate_women_gc_standings(
                group_a_results,
                group_b_results,
                prev_completed,
                tour_standings.is_provisional,
                include_guests=True,
            )

            # Build position maps (rider_id -> position)
            for standing in prev_gc_a.standings:
                position_changes_a[standing.rider_id] = standing.position
            for standing in prev_gc_b.standings:
                position_changes_b[standing.rider_id] = standing.position
            for standing in prev_gc_women.standings:
                position_changes_women[standing.rider_id] = standing.position

        # Get active stage objects for display
        active_stage_objects = [
            tour_config.get_stage(s) for s in tour_standings.active_stages
        ]
        active_stage_objects = [s for s in active_stage_objects if s]  # Filter None

        context = {
            "group_a": tour_standings.group_a,
            "group_b": tour_standings.group_b,
            "women_gc": women_gc,
            "stages": tour_config.stages,
            "current_stage": tour_standings.current_stage,
            "active_stages": active_stage_objects,
            "is_provisional": tour_standings.is_provisional,
            "is_stage_in_progress": tour_standings.is_stage_in_progress,
            "next_stage": next_stage,
            "last_updated": tour_standings.last_updated,
            "position_changes_a": position_changes_a,
            "position_changes_b": position_changes_b,
            "position_changes_women": position_changes_women,
        }

        content = self._render_template("index.html", context)
        return self._write_html("index.html", content)

    def generate_gc_page(
        self,
        tour_standings: TourStandings,
        tour_config: TourConfig,  # noqa: ARG002
        stage_results: dict[
            str, tuple[list[StageResult], list[StageResult], list[StageResult]]
        ],
    ) -> Path:
        """
        Generate gc.html (GC standings page).

        Args:
            tour_standings: Current tour standings
            tour_config: Tour configuration
            stage_results: Dict mapping stage number to (group_a, group_b, uncategorized) results

        Returns:
            Path to generated file
        """
        from src.processor.gc_standings import (
            calculate_gc_standings,
            calculate_women_gc_standings,
        )

        # Determine available stages from results (using STAGE_ORDER)
        available_stages = [s for s in STAGE_ORDER if s in stage_results]
        max_stage_num = available_stages[-1] if available_stages else STAGE_ORDER[0]
        max_stage_idx = STAGE_ORDER.index(max_stage_num) if available_stages else 0
        completed_stages = tour_standings.group_a.completed_stages

        # Build stage results dict for GC calculation
        group_a_results: dict[str, list[StageResult]] = {}
        group_b_results: dict[str, list[StageResult]] = {}

        for stage_num, (group_a, group_b, _) in stage_results.items():
            group_a_results[stage_num] = group_a
            group_b_results[stage_num] = group_b

        # Calculate GC for each stage (in order)
        gc_by_stage_a = {}
        gc_by_stage_b = {}
        gc_by_stage_women = {}

        stages_to_calculate = STAGE_ORDER[: max_stage_idx + 1]
        for idx, stage_num in enumerate(stages_to_calculate):
            # completed_count is 1-indexed (how many stages completed up to this one)
            completed_count = idx + 1

            # Include DNS riders for any active stage in progress (handles concurrent stages)
            include_dns_riders = (
                stage_num in tour_standings.active_stages
                and tour_standings.is_stage_in_progress
            )

            gc_by_stage_a[stage_num] = calculate_gc_standings(
                group_a_results,
                "A",
                completed_count,
                tour_standings.is_provisional,
                include_guests=True,
                target_stage=stage_num,
                include_dns=include_dns_riders,
            )
            gc_by_stage_b[stage_num] = calculate_gc_standings(
                group_b_results,
                "B",
                completed_count,
                tour_standings.is_provisional,
                include_guests=True,
                target_stage=stage_num,
                include_dns=include_dns_riders,
            )
            gc_by_stage_women[stage_num] = calculate_women_gc_standings(
                group_a_results,
                group_b_results,
                completed_count,
                tour_standings.is_provisional,
                include_guests=True,
            )

        # Calculate overall women's GC
        women_gc = calculate_women_gc_standings(
            group_a_results,
            group_b_results,
            completed_stages,
            tour_standings.is_provisional,
            include_guests=True,
        )
        women_gc.last_updated = tour_standings.last_updated

        # Default to current stage or final available stage
        default_stage = (
            tour_standings.current_stage
            if tour_standings.is_stage_in_progress
            else max_stage_num
        )

        context = {
            "group_a": tour_standings.group_a,
            "group_b": tour_standings.group_b,
            "women_gc": women_gc,
            "completed_stages": completed_stages,
            "is_provisional": tour_standings.is_provisional,
            "last_updated": tour_standings.last_updated,
            "gc_by_stage_a": gc_by_stage_a,
            "gc_by_stage_b": gc_by_stage_b,
            "gc_by_stage_women": gc_by_stage_women,
            "available_stages": stages_to_calculate,
            "default_stage": default_stage,
            "current_stage": tour_standings.current_stage,
            "is_stage_in_progress": tour_standings.is_stage_in_progress,
        }

        content = self._render_template("gc.html", context)
        return self._write_html("gc.html", content)

    def generate_stats_page(
        self,
        stage_results: dict[
            str, tuple[list[StageResult], list[StageResult], list[StageResult]]
        ],
        last_updated: str | None = None,
    ) -> Path:
        """
        Generate stats.html (participation statistics page).

        Args:
            stage_results: Dict mapping stage number to (group_a, group_b, uncategorized) results
            last_updated: Last update timestamp

        Returns:
            Path to generated file
        """
        from collections import defaultdict

        # Extract event data from all results
        event_data = []
        event_ids_seen = set()
        all_rider_ids = set()

        day_map = {
            0: "Mon",
            1: "Tue",
            2: "Wed",
            3: "Thu",
            4: "Fri",
            5: "Sat",
            6: "Sun",
        }

        for stage_num, (group_a, group_b, uncategorized) in stage_results.items():
            all_results = group_a + group_b + uncategorized

            # Group results by event_id
            by_event: dict[str, list[StageResult]] = defaultdict(list)
            for result in all_results:
                if result.event_id and result.timestamp:
                    by_event[result.event_id].append(result)
                    all_rider_ids.add(result.rider_id)

            # Build event data
            for event_id, results in by_event.items():
                if event_id in event_ids_seen:
                    continue
                event_ids_seen.add(event_id)

                # Get timestamp from first result
                first = results[0]
                if first.timestamp:
                    day = day_map[first.timestamp.weekday()]
                    hour = first.timestamp.hour
                    time_slot = f"{hour:02d}:00"

                    event_data.append(
                        {
                            "event_id": event_id,
                            "stage": stage_num,
                            "day": day,
                            "time_slot": time_slot,
                            "count": len(results),
                        }
                    )

        # Calculate summary stats
        total_participants = sum(e["count"] for e in event_data)
        unique_riders = len(all_rider_ids)
        total_events = len(event_ids_seen)
        stages_with_data = len(stage_results)

        context = {
            "event_data": event_data,
            "total_participants": total_participants,
            "unique_riders": unique_riders,
            "total_events": total_events,
            "stages_with_data": stages_with_data,
            "last_updated": last_updated,
        }

        content = self._render_template("stats.html", context)
        return self._write_html("stats.html", content)

    def generate_stage_page(
        self,
        stage_number: str,
        group_a_results: list[StageResult],
        group_b_results: list[StageResult],
        tour_config: TourConfig,
        last_updated: str | None = None,
        uncategorized_results: list[StageResult] | None = None,
    ) -> Path:
        """
        Generate stage results page.

        Args:
            stage_number: Stage number (e.g., '1', '3.1', '3.2')
            group_a_results: Group A stage results
            group_b_results: Group B stage results
            tour_config: Tour configuration
            last_updated: Last update timestamp
            uncategorized_results: Uncategorized rider results (not in GC)

        Returns:
            Path to generated file
        """
        from src.processor.handicap import split_results_by_gender

        stage = tour_config.get_stage(stage_number)

        all_results = group_a_results + group_b_results
        if uncategorized_results:
            all_results += uncategorized_results

        is_provisional = any(r.is_provisional for r in all_results)

        # Get courses and check for penalty events
        courses = stage.courses if stage else []
        has_penalty_events = any(c.has_penalties for c in courses)

        # Split results by gender for women's sections
        women_a, _ = split_results_by_gender(group_a_results)
        women_b, _ = split_results_by_gender(group_b_results)
        all_women = women_a + women_b
        # Recalculate positions for combined women's results
        from src.processor.handicap import _calculate_positions_and_gaps

        all_women = _calculate_positions_and_gaps(all_women, use_stage_time=True)

        # Get previous and next stages for navigation
        prev_stage, next_stage = tour_config.get_adjacent_stages(stage_number)

        context = {
            "stage_number": stage_number,
            "stage_name": stage.name if stage else f"Stage {stage_number}",
            # Use display properties that handle legacy and new course formats
            "route": stage.display_route if stage else "",
            "distance_km": stage.display_distance_km if stage else 0,
            "elevation_m": stage.display_elevation_m if stage else 0,
            # Course information for multi-course stages
            "courses": courses,
            "has_penalty_events": has_penalty_events,
            "group_a_results": group_a_results,
            "group_b_results": group_b_results,
            "women_results": all_women,
            "uncategorized_results": uncategorized_results or [],
            "is_provisional": is_provisional,
            "last_updated": last_updated,
            # Navigation
            "prev_stage": prev_stage,
            "next_stage": next_stage,
        }

        content = self._render_template("stage.html", context)
        return self._write_html(f"stage_{stage_number}.html", content)

    def generate_all(
        self,
        stage_results: dict[
            str, tuple[list[StageResult], list[StageResult], list[StageResult]]
        ],
        tour_standings: TourStandings,
        tour_config: TourConfig,
    ) -> list[Path]:
        """
        Generate all website pages.

        Args:
            stage_results: Dict mapping stage number to (group_a, group_b, uncategorized) results
            tour_standings: Current tour standings
            tour_config: Tour configuration

        Returns:
            List of generated file paths
        """
        generated_files: list[Path] = []

        # Copy static assets
        self.copy_static_assets()

        # Calculate women's GC for index page
        from src.processor.gc_standings import calculate_women_gc_standings

        # Build stage results dict for GC calculation
        group_a_results: dict[str, list[StageResult]] = {}
        group_b_results: dict[str, list[StageResult]] = {}

        for stage_num, (group_a, group_b, _) in stage_results.items():
            group_a_results[stage_num] = group_a
            group_b_results[stage_num] = group_b

        women_gc = calculate_women_gc_standings(
            group_a_results,
            group_b_results,
            tour_standings.group_a.completed_stages,
            tour_standings.is_provisional,
            include_guests=True,
        )
        women_gc.last_updated = tour_standings.last_updated

        # Generate index page
        generated_files.append(
            self.generate_index(tour_standings, tour_config, women_gc, stage_results)
        )

        # Generate GC page
        generated_files.append(
            self.generate_gc_page(tour_standings, tour_config, stage_results)
        )

        # Generate stats page
        generated_files.append(
            self.generate_stats_page(stage_results, tour_standings.last_updated)
        )

        # Generate stage pages
        for stage_num, (group_a, group_b, uncategorized) in stage_results.items():
            generated_files.append(
                self.generate_stage_page(
                    stage_num,
                    group_a,
                    group_b,
                    tour_config,
                    tour_standings.last_updated,
                    uncategorized,
                )
            )

        # Generate placeholder pages for stages without results
        for stage in tour_config.stages:
            if stage.number not in stage_results:
                generated_files.append(
                    self.generate_stage_page(
                        stage.number,
                        [],
                        [],
                        tour_config,
                        tour_standings.last_updated,
                        [],
                    )
                )

        return generated_files
