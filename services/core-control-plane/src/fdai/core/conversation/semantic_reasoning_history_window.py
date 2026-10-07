"""Trusted history-window derivation for compiled conversation reads."""

from __future__ import annotations

from .semantic_reasoning_form import DurationUnit, FormGoal, TimeKind
from .semantic_reasoning_metric_selection import WINDOW_LIMITATIONS
from .semantic_reasoning_nodes import CompileContext

MIN_LOOKBACK_SECONDS = 60
MAX_LOOKBACK_SECONDS = 604_800
_CURRENT_TIMES = frozenset({TimeKind.CURRENT, TimeKind.UNSPECIFIED})
_UNIT_SECONDS = {
    DurationUnit.MINUTE: 60,
    DurationUnit.HOUR: 3_600,
    DurationUnit.DAY: 86_400,
    DurationUnit.WEEK: 604_800,
}


def stated_window(goal: FormGoal, ctx: CompileContext) -> tuple[int, str, str] | str:
    """Return the trusted lookback and the notices that disclose it."""

    lookback = history_lookback_seconds(goal, default_seconds=ctx.default_lookback_seconds)
    if isinstance(lookback, str):
        return lookback
    seconds, defaulted = lookback
    if defaulted:
        kind = "default"
    else:
        kind = "model_judged" if goal.id in ctx.admission.judged_times else "applied"
    code = WINDOW_LIMITATIONS[kind]
    return seconds, f"{code}:{seconds}", f"window.{kind}.{seconds}"


def history_lookback_seconds(
    goal: FormGoal,
    *,
    default_seconds: int,
) -> tuple[int, bool] | str:
    """Return the trusted lookback for a history goal or why it is unusable."""

    kind = goal.time.kind
    if kind in _CURRENT_TIMES:
        return default_seconds, True
    if kind is not TimeKind.WINDOW or goal.time.value is None:
        return f"time_unsupported:{kind.value}"
    duration = goal.time.value.duration
    if duration is None:
        return "time_calendar_window_unsupported"
    seconds = duration.amount * _UNIT_SECONDS[duration.unit]
    if not MIN_LOOKBACK_SECONDS <= seconds <= MAX_LOOKBACK_SECONDS:
        return "time_window_out_of_bounds"
    return seconds, False


__all__ = [
    "MAX_LOOKBACK_SECONDS",
    "MIN_LOOKBACK_SECONDS",
    "history_lookback_seconds",
    "stated_window",
]
