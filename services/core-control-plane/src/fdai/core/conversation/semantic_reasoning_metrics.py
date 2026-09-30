"""Ground a metric lookup of one bound Resource in the reviewed metric reader's bounds.

The measure's mention grounds to reviewed metric concepts by closed choice, never by the
words of the question. A current question reads the reviewed default window; a stated
duration must lie within the reader's declared bounds. A calendar window, an ungrounded
concept, or more concepts than one read accepts returns a typed unsupported reason.
"""

from __future__ import annotations

from typing import Any

from .semantic_reasoning_form import DurationUnit, FormGoal, TimeKind
from .semantic_reasoning_nodes import (
    CompileContext,
    OperatorResult,
    concept_values,
    declared_maximum,
)

METRIC_READER = "query.resource_metric_inventory"
# The reviewed metric default the current path also reads when no window is stated.
DEFAULT_METRIC_WINDOW_SECONDS = 900
MIN_METRIC_WINDOW_SECONDS = 300
METRIC_CONCEPTS_PER_READ = 4
_CURRENT_TIMES = frozenset({TimeKind.CURRENT, TimeKind.UNSPECIFIED})
_UNIT_SECONDS = {
    DurationUnit.MINUTE: 60,
    DurationUnit.HOUR: 3_600,
    DurationUnit.DAY: 86_400,
    DurationUnit.WEEK: 604_800,
}


def metric_read(goal: FormGoal, ctx: CompileContext) -> tuple[dict[str, Any], str] | OperatorResult:
    """Return the metric reader's arguments and the window's notice kind, or why not.

    The notice kind is ``default`` for the reviewed default window and ``applied`` for a
    stated one; the caller states which window it read.
    """

    measure = goal.measure
    if measure is None or measure.mention is None:
        return OperatorResult(unsupported=("metric_concept_required",))
    concepts, failure = concept_values(measure.mention, ctx)
    if failure is not None:
        return failure
    maximum = declared_maximum(ctx, METRIC_READER, "window_seconds")
    if maximum is None:
        return OperatorResult(unsupported=(f"function_unavailable:{METRIC_READER}",))
    if not 1 <= len(concepts) <= METRIC_CONCEPTS_PER_READ:
        return OperatorResult(unsupported=("metric_concept_count_unsupported",))
    window = metric_window(goal, maximum=maximum)
    if isinstance(window, str):
        return OperatorResult(unsupported=(window,))
    seconds, kind = window
    return {"metric_concepts": sorted(concepts), "window_seconds": seconds}, kind


def metric_window(goal: FormGoal, *, maximum: int) -> tuple[int, str] | str:
    """Return the trusted metric window and its notice kind, or why it is unusable."""

    kind = goal.time.kind
    if kind in _CURRENT_TIMES:
        return DEFAULT_METRIC_WINDOW_SECONDS, "default"
    if kind is not TimeKind.WINDOW or goal.time.value is None:
        return f"time_unsupported:{kind.value}"
    duration = goal.time.value.duration
    if duration is None:
        return "time_calendar_window_unsupported"
    seconds = duration.amount * _UNIT_SECONDS[duration.unit]
    if not MIN_METRIC_WINDOW_SECONDS <= seconds <= maximum:
        return "metric_window_out_of_bounds"
    return seconds, "applied"


__all__ = [
    "DEFAULT_METRIC_WINDOW_SECONDS",
    "METRIC_CONCEPTS_PER_READ",
    "METRIC_READER",
    "MIN_METRIC_WINDOW_SECONDS",
    "metric_read",
    "metric_window",
]
