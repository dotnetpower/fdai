"""Progressive conversation metric aggregation and bounds."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from fdai.shared.telemetry.conversation_progress import ConversationProgressMetrics


def test_progress_metrics_aggregate_without_retaining_samples() -> None:
    metrics = ConversationProgressMetrics()

    metrics.observe_latency("time_to_first_progress", 12)
    metrics.observe_latency("time_to_first_progress", 18)
    metrics.record_branch(kind="tool", outcome="completed", duration_ms=30)
    metrics.record_branch(kind="public_web", outcome="timed_out", duration_ms=40)
    metrics.increment("corrections")
    snapshot = metrics.snapshot()

    assert snapshot.latency_ms["time_to_first_progress"].count == 2
    assert snapshot.latency_ms["time_to_first_progress"].average_ms == 15
    assert snapshot.latency_ms["branch"].max_ms == 40
    assert snapshot.counts["branch.tool.completed"] == 1
    assert snapshot.counts["branch.public_web.timed_out"] == 1
    assert snapshot.counts["branch_retry_suppressed"] == 1
    assert snapshot.counts["corrections"] == 1


@pytest.mark.parametrize(
    ("operation", "message"),
    (
        (lambda metrics: metrics.increment("unknown"), "unsupported"),
        (
            lambda metrics: metrics.observe_latency("time_to_first_progress", -1),
            "non-negative",
        ),
        (
            lambda metrics: metrics.record_branch(
                kind="unknown", outcome="completed", duration_ms=1
            ),
            "dimensions",
        ),
    ),
)
def test_progress_metrics_reject_unbounded_dimensions(
    operation: Callable[[ConversationProgressMetrics], None],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        operation(ConversationProgressMetrics())
