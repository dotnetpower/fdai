"""Progress metrics apply only to successfully enqueued stream events."""

from __future__ import annotations

from fdai.delivery.operator_api.projections.conversation.stream_metrics import (
    record_enqueued_progress_metrics,
)
from fdai.shared.telemetry import ConversationProgressMetrics


def test_running_and_terminal_events_record_one_first_progress_and_branch() -> None:
    metrics = ConversationProgressMetrics()
    first = record_enqueued_progress_metrics(
        metrics,
        {
            "event": "branch",
            "branch_kind": "tool",
            "status": "running",
        },
        elapsed_ms=12,
        first_progress_recorded=False,
    )
    first = record_enqueued_progress_metrics(
        metrics,
        {
            "event": "branch",
            "branch_kind": "tool",
            "status": "completed",
            "duration_ms": 30,
        },
        elapsed_ms=31,
        first_progress_recorded=first,
    )

    snapshot = metrics.snapshot()
    assert first is True
    assert snapshot.latency_ms["time_to_first_progress"].count == 1
    assert snapshot.latency_ms["time_to_first_progress"].total_ms == 12
    assert snapshot.counts["branch.tool.completed"] == 1


def test_cancellation_only_event_is_not_first_evidence_progress() -> None:
    metrics = ConversationProgressMetrics()

    first = record_enqueued_progress_metrics(
        metrics,
        {
            "event": "branch",
            "branch_kind": "agent",
            "status": "cancelled",
            "duration_ms": 4,
        },
        elapsed_ms=5,
        first_progress_recorded=False,
    )

    snapshot = metrics.snapshot()
    assert first is False
    assert snapshot.latency_ms["time_to_first_progress"].count == 0
    assert snapshot.counts["branch.agent.cancelled"] == 1


def test_truncated_execution_is_counted_after_enqueue_reduction() -> None:
    metrics = ConversationProgressMetrics()

    record_enqueued_progress_metrics(
        metrics,
        {"event": "activity", "execution": {"output_truncated": True}},
        elapsed_ms=8,
        first_progress_recorded=False,
    )

    assert metrics.snapshot().counts["truncations"] == 1
