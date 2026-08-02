"""Pure metric reduction for successfully enqueued chat progress events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.shared.telemetry import ConversationProgressMetrics

_TERMINAL_BRANCH_STATUSES = frozenset(
    {"completed", "unavailable", "failed", "timed_out", "cancelled"}
)


def record_enqueued_progress_metrics(
    metrics: ConversationProgressMetrics,
    event: Mapping[str, Any],
    *,
    elapsed_ms: int,
    first_progress_recorded: bool,
) -> bool:
    """Record one queue-accepted event and return the first-progress state."""

    status = event.get("status")
    is_cancelled = event.get("event") == "branch" and status == "cancelled"
    if not first_progress_recorded and not is_cancelled:
        metrics.observe_latency("time_to_first_progress", elapsed_ms)
        first_progress_recorded = True

    kind = event.get("branch_kind")
    duration_ms = event.get("duration_ms")
    if (
        event.get("event") == "branch"
        and isinstance(status, str)
        and status in _TERMINAL_BRANCH_STATUSES
        and isinstance(kind, str)
        and isinstance(duration_ms, int)
        and not isinstance(duration_ms, bool)
    ):
        metrics.record_branch(kind=kind, outcome=status, duration_ms=duration_ms)

    execution = event.get("execution")
    if isinstance(execution, Mapping) and execution.get("output_truncated") is True:
        metrics.increment("truncations")
    return first_progress_recorded


__all__ = ["record_enqueued_progress_metrics"]
