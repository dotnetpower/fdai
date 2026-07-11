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

from dataclasses import dataclass


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
    missing_idempotency_key: int = 0
    producer_principal_mismatch: int = 0
    ordered_poison_halts: int = 0
    schema_violations: int = 0

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
            "missing_idempotency_key": self.missing_idempotency_key,
            "producer_principal_mismatch": self.producer_principal_mismatch,
            "ordered_poison_halts": self.ordered_poison_halts,
            "schema_violations": self.schema_violations,
        }


__all__ = ["BridgeMetrics"]
