"""Observability counters for the pantheon event-bus bridge.

Split out of :mod:`fdai.agents._framework.bus_bridge` so the transport
(publish / consume / dead-letter) and its measurement are separate
concerns (SRP): a change to what the bridge *counts* no longer edits the
file that owns *how it moves records*. :class:`EventBusBridge` holds one
:class:`BridgeMetrics` and exposes it via ``snapshot()`` so Heimdall's
health probe and the KPI collectors read per-process delivery / failure
rates without reaching into consumer internals.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

_HANDLER_WINDOW = 32
_RECENT_REJECTION_LIMIT = 32


@dataclass
class BridgeMetrics:
    """Counters for pantheon bridge observability."""

    consumers_started: int = 0
    consumers_crashed: int = 0
    consumers_restarted: int = 0
    consumers_gave_up: int = 0
    delivered: int = 0
    handler_errors: int = 0
    handler_retries: int = 0
    dead_lettered: int = 0
    dead_letter_errors: int = 0
    empty_partition_keys: int = 0
    published: int = 0
    publish_errors: int = 0
    missing_correlation_id: int = 0
    missing_resource_id: int = 0
    missing_idempotency_key: int = 0
    invalid_envelope_fields: int = 0
    producer_principal_mismatch: int = 0
    ordered_poison_halts: int = 0
    schema_violations: int = 0
    duplicate_deliveries: int = 0
    _handler_windows: dict[str, deque[bool]] = field(default_factory=dict)
    _recent_rejections: deque[dict[str, object]] = field(
        default_factory=lambda: deque(maxlen=_RECENT_REJECTION_LIMIT)
    )

    def record_handler_result(self, agent: str, *, failed: bool) -> None:
        window = self._handler_windows.setdefault(agent, deque(maxlen=_HANDLER_WINDOW))
        window.append(failed)

    def degraded_handler_agents(self) -> tuple[str, ...]:
        return tuple(
            sorted(agent for agent, window in self._handler_windows.items() if any(window))
        )

    def record_rejection(
        self,
        *,
        topic: str,
        reason: str,
        payload: dict[str, Any],
        principal: str = "",
        group_id: str = "",
        offset: int | None = None,
    ) -> None:
        self._recent_rejections.append(
            {
                "topic": topic,
                "reason": reason,
                "principal": principal,
                "consumer_group": group_id,
                "offset": offset,
                "correlation_id": str(payload.get("correlation_id") or "")[:128],
                "idempotency_key": str(payload.get("idempotency_key") or "")[:160],
                "producer_principal": str(payload.get("producer_principal") or "")[:64],
            }
        )

    def recent_rejections(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(item) for item in self._recent_rejections)

    def health_failures(self) -> tuple[str, ...]:
        """Return process-window counters that make bridge health degraded."""
        counters = self.as_dict()
        watched = (
            "consumers_crashed",
            "consumers_gave_up",
            "handler_errors",
            "dead_letter_errors",
            "publish_errors",
            "producer_principal_mismatch",
            "ordered_poison_halts",
            "schema_violations",
        )
        return tuple(name for name in watched if counters[name] > 0)

    def as_dict(self) -> dict[str, int]:
        return {
            "consumers_started": self.consumers_started,
            "consumers_crashed": self.consumers_crashed,
            "consumers_restarted": self.consumers_restarted,
            "consumers_gave_up": self.consumers_gave_up,
            "delivered": self.delivered,
            "handler_errors": self.handler_errors,
            "handler_retries": self.handler_retries,
            "dead_lettered": self.dead_lettered,
            "dead_letter_errors": self.dead_letter_errors,
            "empty_partition_keys": self.empty_partition_keys,
            "published": self.published,
            "publish_errors": self.publish_errors,
            "missing_correlation_id": self.missing_correlation_id,
            "missing_resource_id": self.missing_resource_id,
            "missing_idempotency_key": self.missing_idempotency_key,
            "invalid_envelope_fields": self.invalid_envelope_fields,
            "producer_principal_mismatch": self.producer_principal_mismatch,
            "ordered_poison_halts": self.ordered_poison_halts,
            "schema_violations": self.schema_violations,
            "duplicate_deliveries": self.duplicate_deliveries,
        }


__all__ = ["BridgeMetrics"]
