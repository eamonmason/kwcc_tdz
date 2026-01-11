"""Results processing and standings calculation."""

from src.processor.gc_standings import (
    build_tour_standings,
    calculate_gc_standings,
)
from src.processor.handicap import (
    apply_handicap,
    get_best_result_per_rider,
    process_stage_results,
)
from src.processor.output import (
    generate_all_output,
    generate_gc_output,
    generate_stage_output,
)
from src.processor.stage_results import StageResultsManager

__all__ = [
    "StageResultsManager",
    "apply_handicap",
    "build_tour_standings",
    "calculate_gc_standings",
    "generate_all_output",
    "generate_gc_output",
    "generate_stage_output",
    "get_best_result_per_rider",
    "process_stage_results",
]
