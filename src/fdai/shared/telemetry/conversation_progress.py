"""Bounded process-local metrics for progressive operator conversations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from threading import Lock

PROGRESS_COUNTER_NAMES = (
    "corrections",
    "truncations",
    "terminal_completed",
    "sequence_gaps",
    "branch_retry_suppressed",
    "queue_saturation",
    "channel_update_ambiguous",
    "replays",
)
PROGRESS_LATENCY_NAMES = (
    "time_to_first_progress",
    "time_to_first_confirmed",
    "branch",
)
PROGRESS_BRANCH_KINDS = ("tool", "operational", "agent", "public_web")
PROGRESS_BRANCH_OUTCOMES = (
    "completed",
    "unavailable",
    "failed",
    "timed_out",
    "cancelled",
)


@dataclass(frozen=True, slots=True)
class LatencyAggregate:
    count: int = 0
    total_ms: int = 0
    max_ms: int = 0

    @property
    def average_ms(self) -> float:
        return self.total_ms / self.count if self.count else 0.0


@dataclass(frozen=True, slots=True)
class ConversationProgressMetricsSnapshot:
    counts: dict[str, int]
    latency_ms: dict[str, LatencyAggregate]


class ConversationProgressMetrics:
    """Keep bounded counters and aggregates without retaining request data."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter(dict.fromkeys(PROGRESS_COUNTER_NAMES, 0))
        self._latencies = dict.fromkeys(PROGRESS_LATENCY_NAMES, LatencyAggregate())
        self._lock = Lock()

    def increment(self, name: str) -> None:
        if name not in PROGRESS_COUNTER_NAMES:
            raise ValueError(f"unsupported progressive conversation counter: {name}")
        with self._lock:
            self._counts[name] += 1

    def record_branch(self, *, kind: str, outcome: str, duration_ms: int) -> None:
        if kind not in PROGRESS_BRANCH_KINDS or outcome not in PROGRESS_BRANCH_OUTCOMES:
            raise ValueError("unsupported progressive conversation branch dimensions")
        self._require_duration(duration_ms)
        key = f"branch.{kind}.{outcome}"
        with self._lock:
            self._counts[key] += 1
            self._latencies["branch"] = _add_latency(self._latencies["branch"], duration_ms)
            if outcome in {"failed", "timed_out"}:
                self._counts["branch_retry_suppressed"] += 1

    def observe_latency(self, name: str, duration_ms: int) -> None:
        if name not in PROGRESS_LATENCY_NAMES:
            raise ValueError(f"unsupported progressive conversation latency: {name}")
        self._require_duration(duration_ms)
        with self._lock:
            self._latencies[name] = _add_latency(self._latencies[name], duration_ms)

    def snapshot(self) -> ConversationProgressMetricsSnapshot:
        with self._lock:
            return ConversationProgressMetricsSnapshot(
                counts=dict(self._counts),
                latency_ms=dict(self._latencies),
            )

    @staticmethod
    def _require_duration(duration_ms: int) -> None:
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms < 0:
            raise ValueError("progressive conversation duration MUST be a non-negative integer")


def _add_latency(current: LatencyAggregate, duration_ms: int) -> LatencyAggregate:
    return LatencyAggregate(
        count=current.count + 1,
        total_ms=current.total_ms + duration_ms,
        max_ms=max(current.max_ms, duration_ms),
    )


__all__ = [
    "PROGRESS_BRANCH_KINDS",
    "PROGRESS_BRANCH_OUTCOMES",
    "PROGRESS_COUNTER_NAMES",
    "PROGRESS_LATENCY_NAMES",
    "ConversationProgressMetrics",
    "ConversationProgressMetricsSnapshot",
    "LatencyAggregate",
]
