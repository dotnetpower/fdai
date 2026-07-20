"""Read-only delivery reliability and adapter breaker metrics panel."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from fdai.delivery.read_api.routes.panels import PanelQueryError
from fdai.shared.providers.conversation_delivery import (
    ConversationDeliverySnapshot,
    ConversationDeliveryStore,
    OutboundDeliveryState,
)


class ConversationDeliveryPanel:
    path = "/conversation-delivery"
    name = "conversation-delivery"

    def __init__(self, *, store: ConversationDeliveryStore, source: str) -> None:
        self._store = store
        self._source = source

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        unknown = set(params) - {"limit"}
        if unknown:
            raise PanelQueryError(f"unknown delivery panel parameters: {sorted(unknown)}")
        try:
            limit = int(params.get("limit", "200"))
        except ValueError as exc:
            raise PanelQueryError("limit MUST be an integer") from exc
        if not 1 <= limit <= 500:
            raise PanelQueryError("limit MUST be in [1, 500]")
        return _metrics(await self._store.snapshot(limit=limit), source=self._source)


def _metrics(snapshot: ConversationDeliverySnapshot, *, source: str) -> dict[str, object]:
    states = Counter(record.state.value for record in snapshot.deliveries)
    breaker_modes = Counter(record.mode.value for record in snapshot.breakers)
    latencies_ms = sorted(
        int((record.terminal_at - record.created_at).total_seconds() * 1000)
        for record in snapshot.deliveries
        if record.state is OutboundDeliveryState.DELIVERED and record.terminal_at is not None
    )
    retry_count = sum(max(record.attempt_count - 1, 0) for record in snapshot.deliveries)
    return {
        "source": source,
        "read_only": True,
        "delivery_count": len(snapshot.deliveries),
        "states": dict(states),
        "delivery_latency_ms": {
            "count": len(latencies_ms),
            "average": (sum(latencies_ms) / len(latencies_ms) if latencies_ms else None),
            "p95": _percentile(latencies_ms, 0.95),
        },
        "duplicate_risk_count": sum(record.duplicate_risk for record in snapshot.deliveries),
        "retry_count": retry_count,
        "abandonment_count": states[OutboundDeliveryState.ABANDONED.value],
        "breaker_states": dict(breaker_modes),
        "attempt_count": len(snapshot.attempts),
        "acknowledgement_count": len(snapshot.acknowledgements),
        "mutations_available": False,
    }


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    index = max(0, min(len(values) - 1, int((len(values) - 1) * fraction)))
    return values[index]


__all__ = ["ConversationDeliveryPanel"]
