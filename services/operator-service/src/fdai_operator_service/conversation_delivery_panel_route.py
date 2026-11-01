"""Authenticated Console GET-only read route projection for ConversationDeliveryPanel.

Projects aggregate outbound delivery health from a production or in-memory
delivery snapshot reader and a shared bounded progressive-conversation latency
collector. The payload declares ``read_only=True``, ``mutations_available=False``,
and ``execution_authority="none"`` and strips every principal, scope,
conversation, delivery, attempt, provider, and response-text identifier.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelBreakerMode,
    ChannelDeliveryState,
)

_MAX_SNAPSHOT_LIMIT = 500
_MAX_PROGRESSIVE_SAMPLES = 500
_ALLOWED_READ_ROLES = frozenset({"reader", "contributor", "approver", "owner"})
_FORBIDDEN_IDENTIFIER_KEYS = frozenset(
    {
        "principal_id",
        "scope_ref",
        "conversation_id",
        "delivery_id",
        "attempt_id",
        "provider_message_id",
        "adapter_id",
        "text",
        "response",
        "idempotency_key",
        "recipient",
        "user_id",
        "channel_id",
        "webhook_url",
        "email",
    }
)


class _DeliveryRecordLike(Protocol):
    @property
    def state(self) -> Any: ...

    @property
    def created_at(self) -> datetime: ...

    @property
    def terminal_at(self) -> datetime | None: ...

    @property
    def attempt_count(self) -> int: ...

    @property
    def duplicate_risk(self) -> bool: ...


class _BreakerRecordLike(Protocol):
    @property
    def mode(self) -> Any: ...


class _DeliverySnapshotLike(Protocol):
    @property
    def deliveries(self) -> Sequence[_DeliveryRecordLike]: ...

    @property
    def attempts(self) -> Sequence[Any]: ...

    @property
    def acknowledgements(self) -> Sequence[Any]: ...

    @property
    def breakers(self) -> Sequence[_BreakerRecordLike]: ...


class DeliverySnapshotStore(Protocol):
    """Snapshot reader capability over the Operator or Core outbound delivery ledger."""

    async def snapshot(self, *, limit: int = 200) -> _DeliverySnapshotLike: ...


@dataclass(frozen=True, slots=True)
class LatencyAggregate:
    """Identifier-free latency summary with count, average, and p95 in milliseconds."""

    count: int
    average_ms: float | None
    p95_ms: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "average_ms": self.average_ms,
            "p95_ms": self.p95_ms,
        }


class BoundedProgressiveConversationCollector:
    """Shared bounded collector for progressive-conversation latency aggregates."""

    def __init__(self, *, max_samples: int = _MAX_PROGRESSIVE_SAMPLES) -> None:
        if not 1 <= max_samples <= 5_000:
            raise ValueError("max_samples MUST be between 1 and 5000")
        self._max_samples = max_samples
        self._conversation_count = 0
        self._first_progress_ms: deque[float] = deque(maxlen=max_samples)
        self._first_confirmed_ms: deque[float] = deque(maxlen=max_samples)
        self._branch_ms: deque[float] = deque(maxlen=max_samples)

    def record_turn(
        self,
        *,
        first_progress_ms: float | None = None,
        first_confirmed_ms: float | None = None,
        branch_ms: Sequence[float] = (),
    ) -> None:
        """Record latency samples from one progressive conversation turn without identifiers."""
        if first_progress_ms is not None:
            _validate_sample(first_progress_ms)
        if first_confirmed_ms is not None:
            _validate_sample(first_confirmed_ms)
        validated_branches = [_validate_sample(item) for item in branch_ms]

        self._conversation_count += 1
        if first_progress_ms is not None:
            self._first_progress_ms.append(float(first_progress_ms))
        if first_confirmed_ms is not None:
            self._first_confirmed_ms.append(float(first_confirmed_ms))
        for sample in validated_branches:
            self._branch_ms.append(sample)

    def snapshot_dict(self) -> dict[str, object]:
        """Return the aggregate progressive-conversation payload."""
        return {
            "conversation_count": self._conversation_count,
            "first_progress_latency": summarize_latency_samples(
                tuple(self._first_progress_ms)
            ).to_dict(),
            "first_confirmed_latency": summarize_latency_samples(
                tuple(self._first_confirmed_ms)
            ).to_dict(),
            "branch_latency": summarize_latency_samples(tuple(self._branch_ms)).to_dict(),
        }


class ConversationDeliveryPanelRoute:
    """Authenticated GET-only Console route bound to a delivery store and progressive collector."""

    route_path = "/operations/conversation-delivery"

    def __init__(
        self,
        *,
        store: DeliverySnapshotStore,
        progressive_collector: BoundedProgressiveConversationCollector | None = None,
        snapshot_limit: int = 200,
    ) -> None:
        if not 1 <= snapshot_limit <= _MAX_SNAPSHOT_LIMIT:
            raise ValueError(f"snapshot_limit MUST be between 1 and {_MAX_SNAPSHOT_LIMIT}")
        self._store = store
        self._progressive_collector = progressive_collector
        self._snapshot_limit = snapshot_limit

    async def get_panel(
        self,
        *,
        principal_id: str | None,
        roles: frozenset[str] | set[str],
        method: str = "GET",
    ) -> dict[str, object]:
        """Read the aggregate, identifier-free delivery panel for an authenticated caller."""
        if method.strip().upper() != "GET":
            raise PermissionError("ConversationDeliveryPanel route is strictly GET-only")
        if principal_id is None or not principal_id.strip():
            raise PermissionError(
                "ConversationDeliveryPanel route requires an authenticated principal"
            )
        normalized_roles = {role.strip().lower() for role in roles if role.strip()}
        if not (normalized_roles & _ALLOWED_READ_ROLES):
            raise PermissionError("ConversationDeliveryPanel route requires an operator read role")

        snapshot = await self._store.snapshot(limit=self._snapshot_limit)
        progressive_payload = (
            self._progressive_collector.snapshot_dict()
            if self._progressive_collector is not None
            else None
        )
        payload = project_conversation_delivery_panel_payload(
            snapshot,
            progressive=progressive_payload,
        )
        _assert_identifier_free(payload)
        return payload


def project_conversation_delivery_panel_payload(
    snapshot: _DeliverySnapshotLike,
    *,
    progressive: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the identifier-free Console payload from a delivery snapshot."""
    deliveries = snapshot.deliveries
    state_counts = {state.value: 0 for state in ChannelDeliveryState}
    for record in deliveries:
        key = str(getattr(record.state, "value", record.state))
        if key not in state_counts:
            raise ValueError(f"unknown delivery state in snapshot: {key}")
        state_counts[key] += 1

    breaker_counts = {mode.value: 0 for mode in ChannelBreakerMode}
    for breaker in snapshot.breakers:
        mode_key = str(getattr(breaker.mode, "value", breaker.mode))
        if mode_key not in breaker_counts:
            raise ValueError(f"unknown breaker mode in snapshot: {mode_key}")
        breaker_counts[mode_key] += 1

    latency_samples = [
        (record.terminal_at - record.created_at).total_seconds() * 1000.0
        for record in deliveries
        if record.terminal_at is not None
    ]
    non_negative_samples = [sample for sample in latency_samples if sample >= 0.0]

    payload: dict[str, object] = {
        "surface": "conversation-delivery-panel",
        "route": ConversationDeliveryPanelRoute.route_path,
        "read_only": True,
        "mutations_available": False,
        "execution_authority": "none",
        "delivery_count": len(deliveries),
        "delivery_latency": summarize_latency_samples(non_negative_samples).to_dict(),
        "state_counts": state_counts,
        "duplicate_risk_count": sum(1 for record in deliveries if record.duplicate_risk),
        "retry_count": sum(max(record.attempt_count - 1, 0) for record in deliveries),
        "abandoned_count": state_counts[ChannelDeliveryState.ABANDONED.value],
        "attempt_count": len(snapshot.attempts),
        "acknowledgement_count": len(snapshot.acknowledgements),
        "breaker_state_counts": breaker_counts,
        "progressive": None if progressive is None else dict(progressive),
    }
    _assert_identifier_free(payload)
    return payload


def summarize_latency_samples(samples: Sequence[float]) -> LatencyAggregate:
    """Summarize non-negative latency samples in milliseconds."""
    values = [_validate_sample(sample) for sample in samples]
    if not values:
        return LatencyAggregate(count=0, average_ms=None, p95_ms=None)
    ordered = sorted(values)
    p95_index = max(math.ceil(0.95 * len(ordered)) - 1, 0)
    return LatencyAggregate(
        count=len(ordered),
        average_ms=round(sum(ordered) / len(ordered), 3),
        p95_ms=round(ordered[p95_index], 3),
    )


def _validate_sample(value: float) -> float:
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0.0:
        raise ValueError("latency sample MUST be finite and non-negative")
    return numeric


def _assert_identifier_free(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).strip().casefold() in _FORBIDDEN_IDENTIFIER_KEYS:
                raise ValueError(f"delivery panel payload MUST NOT expose identifier key {key}")
            _assert_identifier_free(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _assert_identifier_free(item)


project_conversation_delivery_route_payload = project_conversation_delivery_panel_payload

__all__ = [
    "BoundedProgressiveConversationCollector",
    "ConversationDeliveryPanelRoute",
    "DeliverySnapshotStore",
    "LatencyAggregate",
    "project_conversation_delivery_panel_payload",
    "project_conversation_delivery_route_payload",
    "summarize_latency_samples",
]
