"""GET-only aggregate projection for outbound conversation delivery.

The panel answers "is delivery healthy?" from the immutable delivery ledger. It
is strictly read-only: it never claims, finishes, reconciles, resumes, retries,
overrides duplicate risk, or writes a breaker record, and its payload declares
`read_only=True` and `mutations_available=False` so a console cannot render a
mutation control from it.

The payload is aggregate-only. It carries no answer text, principal, scope,
conversation, delivery, attempt, or provider identifier, so delivery health can
be observed without exposing conversation content or identities.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from fdai.shared.providers.conversation_delivery import (
    AdapterBreakerMode,
    ConversationDeliverySnapshot,
    OutboundDeliveryRecord,
    OutboundDeliveryState,
)

_MAX_SNAPSHOT_LIMIT = 1000


class DeliverySnapshotReader(Protocol):
    """The single read capability the panel needs from a delivery store."""

    async def snapshot(self, *, limit: int = 200) -> ConversationDeliverySnapshot: ...


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Bounded latency aggregate. Percentiles stay `None` without samples."""

    count: int
    average_ms: float | None
    p95_ms: float | None

    def to_dict(self) -> Mapping[str, object]:
        return {"count": self.count, "average_ms": self.average_ms, "p95_ms": self.p95_ms}


@dataclass(frozen=True, slots=True)
class ProgressiveConversationAggregate:
    """Optional aggregate counters shared by a bounded progressive collector."""

    conversation_count: int
    first_progress: LatencySummary
    first_confirmed: LatencySummary
    branch: LatencySummary

    def __post_init__(self) -> None:
        if self.conversation_count < 0:
            raise ValueError("progressive conversation_count MUST NOT be negative")

    def to_dict(self) -> Mapping[str, object]:
        return {
            "conversation_count": self.conversation_count,
            "first_progress_latency": dict(self.first_progress.to_dict()),
            "first_confirmed_latency": dict(self.first_confirmed.to_dict()),
            "branch_latency": dict(self.branch.to_dict()),
        }


@dataclass(frozen=True, slots=True)
class ConversationDeliveryPanel:
    """Read-only operations view over the delivery ledger."""

    reader: DeliverySnapshotReader
    limit: int = 200

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= _MAX_SNAPSHOT_LIMIT:
            raise ValueError(f"delivery panel limit MUST be in [1, {_MAX_SNAPSHOT_LIMIT}]")

    async def read(
        self,
        *,
        progressive: ProgressiveConversationAggregate | None = None,
    ) -> Mapping[str, object]:
        snapshot = await self.reader.snapshot(limit=self.limit)
        return project_conversation_delivery_panel(snapshot, progressive=progressive)


def project_conversation_delivery_panel(
    snapshot: ConversationDeliverySnapshot,
    *,
    progressive: ProgressiveConversationAggregate | None = None,
) -> Mapping[str, object]:
    """Return the aggregate, identifier-free delivery panel payload."""

    deliveries = snapshot.deliveries
    state_counts = {state.value: 0 for state in OutboundDeliveryState}
    for record in deliveries:
        state_counts[record.state.value] += 1
    breaker_counts = {mode.value: 0 for mode in AdapterBreakerMode}
    for breaker in snapshot.breakers:
        breaker_counts[breaker.mode.value] += 1
    return {
        "read_only": True,
        "mutations_available": False,
        "delivery_count": len(deliveries),
        "delivery_latency": dict(_latency(deliveries).to_dict()),
        "state_counts": state_counts,
        "duplicate_risk_count": sum(1 for record in deliveries if record.duplicate_risk),
        "retry_count": sum(max(record.attempt_count - 1, 0) for record in deliveries),
        "abandoned_count": state_counts[OutboundDeliveryState.ABANDONED.value],
        "attempt_count": len(snapshot.attempts),
        "acknowledgement_count": len(snapshot.acknowledgements),
        "breaker_state_counts": breaker_counts,
        "progressive": None if progressive is None else dict(progressive.to_dict()),
    }


def summarize_latency(samples: Sequence[float]) -> LatencySummary:
    """Return a bounded latency summary for externally measured samples."""

    values = [float(value) for value in samples]
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("latency samples MUST be finite and non-negative")
    if not values:
        return LatencySummary(count=0, average_ms=None, p95_ms=None)
    ordered = sorted(values)
    index = max(math.ceil(0.95 * len(ordered)) - 1, 0)
    return LatencySummary(
        count=len(ordered),
        average_ms=round(sum(ordered) / len(ordered), 3),
        p95_ms=round(ordered[index], 3),
    )


def _latency(deliveries: Sequence[OutboundDeliveryRecord]) -> LatencySummary:
    samples = [
        (record.terminal_at - record.created_at).total_seconds() * 1000.0
        for record in deliveries
        if record.terminal_at is not None
    ]
    return summarize_latency([sample for sample in samples if sample >= 0])


__all__ = [
    "ConversationDeliveryPanel",
    "DeliverySnapshotReader",
    "LatencySummary",
    "ProgressiveConversationAggregate",
    "project_conversation_delivery_panel",
    "summarize_latency",
]
