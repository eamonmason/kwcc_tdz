"""Jinja2 template rendering for website generation."""

import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.models.result import StageResult
from src.models.standings import TourStandings
from src.models.tour import TourConfig


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
    ) -> Path:
        """
        Generate index.html (homepage).

        Args:
            tour_standings: Current tour standings
            tour_config: Tour configuration

        Returns:
            Path to generated file
        """
        # Get the next upcoming stage if any
        upcoming = tour_config.upcoming_stages
        next_stage = upcoming[0] if upcoming else None

        context = {
            "group_a": tour_standings.group_a,
            "group_b": tour_standings.group_b,
            "stages": tour_config.stages,
            "current_stage": tour_standings.current_stage,
            "is_provisional": tour_standings.is_provisional,
            "is_stage_in_progress": tour_standings.is_stage_in_progress,
            "next_stage": next_stage,
            "last_updated": tour_standings.last_updated,
        }

        content = self._render_template("index.html", context)
        return self._write_html("index.html", content)

    def generate_gc_page(
        self,
        tour_standings: TourStandings,
        tour_config: TourConfig,  # noqa: ARG002
        stage_results: dict[
            int, tuple[list[StageResult], list[StageResult], list[StageResult]]
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

        # Calculate GC for each stage (1 through max available)
        max_stage = max(stage_results.keys()) if stage_results else 1
        completed_stages = tour_standings.group_a.completed_stages

        # Build stage results dict for GC calculation
        group_a_results: dict[int, list[StageResult]] = {}
        group_b_results: dict[int, list[StageResult]] = {}

        for stage_num, (group_a, group_b, _) in stage_results.items():
            group_a_results[stage_num] = group_a
            group_b_results[stage_num] = group_b

        # Calculate GC for each stage
        gc_by_stage_a = {}
        gc_by_stage_b = {}
        gc_by_stage_women = {}

        for stage_num in range(1, max_stage + 1):
            # Only include DNS riders for current stage in progress
            include_dns_riders = (
                stage_num == tour_standings.current_stage
                and tour_standings.is_stage_in_progress
            )

            gc_by_stage_a[stage_num] = calculate_gc_standings(
                group_a_results,
                "A",
                completed_stages,
                tour_standings.is_provisional,
                include_guests=True,
                target_stage=stage_num,
                include_dns=include_dns_riders,
            )
            gc_by_stage_b[stage_num] = calculate_gc_standings(
                group_b_results,
                "B",
                completed_stages,
                tour_standings.is_provisional,
                include_guests=True,
                target_stage=stage_num,
                include_dns=include_dns_riders,
            )
            gc_by_stage_women[stage_num] = calculate_women_gc_standings(
                group_a_results,
                group_b_results,
                stage_num,
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

        # Default to current stage or final stage
        default_stage = (
            tour_standings.current_stage
            if tour_standings.is_stage_in_progress
            else max_stage
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
            "max_stage": max_stage,
            "default_stage": default_stage,
            "current_stage": tour_standings.current_stage,
            "is_stage_in_progress": tour_standings.is_stage_in_progress,
        }

        content = self._render_template("gc.html", context)
        return self._write_html("gc.html", content)

    def generate_stage_page(
        self,
        stage_number: int,
        group_a_results: list[StageResult],
        group_b_results: list[StageResult],
        tour_config: TourConfig,
        last_updated: str | None = None,
        uncategorized_results: list[StageResult] | None = None,
    ) -> Path:
        """
        Generate stage results page.

        Args:
            stage_number: Stage number
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
        }

        content = self._render_template("stage.html", context)
        return self._write_html(f"stage_{stage_number}.html", content)

    def generate_all(
        self,
        stage_results: dict[
            int, tuple[list[StageResult], list[StageResult], list[StageResult]]
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

        # Generate index page
        generated_files.append(self.generate_index(tour_standings, tour_config))

        # Generate GC page
        generated_files.append(
            self.generate_gc_page(tour_standings, tour_config, stage_results)
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
