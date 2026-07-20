"""Huginn - Event Collector (Wave 3 behavior).

Huginn normalizes incoming raw signals into `Event` payloads, dedups
by stable key, and publishes to `object.event`. Wave 3 implements the
in-process ingestion; adapter integration for Azure Activity Log lives
behind a provider protocol added in a later wave.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import IntrospectionResult, capability_facts
from fdai.agents._framework.pantheon import _HUGINN

# Bound the dedup memory so a long-lived process cannot leak: the most
# recent N idempotency keys are retained; older keys age out (a re-arrival
# after eviction is re-published, which the downstream idempotency key
# still makes safe - at-least-once is the bus contract).
_DEDUP_CAPACITY = 100_000

#: Bound each ingress string field so a single pathological signal cannot bloat
#: the pipeline / audit or become a huge bus partition key. Applies to every
#: ingested event, not just operator proposals.
_MAX_FIELD_CHARS = 512

#: Bound the free-form ``attributes`` map at ingress: cap the key count and
#: truncate string values, so a pathological or forged signal cannot smuggle a
#: giant nested payload past the top-level field caps (same bloat / audit /
#: partition-key concern, one level down). Shallow by design - the common
#: bloat vectors are too many keys and oversized string values.
_MAX_ATTR_KEYS = 64

DiscoveryProjector = Callable[[Mapping[str, Any]], Awaitable[object]]
"""Injected durable inventory projector; cloud and database I/O stay outside Huginn."""


def _bound(value: Any) -> Any:
    """Truncate a string value to the ingress field cap; pass non-strings."""
    return value[:_MAX_FIELD_CHARS] if isinstance(value, str) else value


def _bound_attributes(attrs: Any) -> dict[str, Any]:
    """Cap the attribute key count and truncate string values at ingress."""
    if not isinstance(attrs, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if len(out) >= _MAX_ATTR_KEYS:
            break
        out[str(key)[:_MAX_FIELD_CHARS]] = _bound(value)
    return out


def _bound_json(value: Any, *, depth: int = 0) -> Any:
    """Bound a canonical inventory change without changing its typed shape."""
    if isinstance(value, str):
        return value[:_MAX_FIELD_CHARS]
    if value is None or isinstance(value, int | float | bool):
        return value
    if depth >= 4:
        return str(value)[:_MAX_FIELD_CHARS]
    if isinstance(value, Mapping):
        return {
            str(key)[:_MAX_FIELD_CHARS]: _bound_json(item, depth=depth + 1)
            for key, item in list(value.items())[:_MAX_ATTR_KEYS]
        }
    if isinstance(value, list | tuple):
        return [_bound_json(item, depth=depth + 1) for item in value[:_MAX_ATTR_KEYS]]
    return str(value)[:_MAX_FIELD_CHARS]


class Huginn(Agent):
    """Wave-3 Huginn: normalize + dedup + publish."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        dedup_capacity: int = _DEDUP_CAPACITY,
        discovery_projector: DiscoveryProjector | None = None,
    ) -> None:
        super().__init__(spec=_HUGINN)
        self.bus = bus
        if dedup_capacity < 1:
            raise ValueError("dedup_capacity MUST be >= 1")
        self._dedup_capacity = dedup_capacity
        self._discovery_projector = discovery_projector
        # OrderedDict as an LRU set: key -> None, oldest first.
        self._seen_keys: OrderedDict[str, None] = OrderedDict()

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    def health(self) -> dict[str, Any]:
        """Expose ingress / dedup state for Heimdall's probe."""
        return {
            "agent": "Huginn",
            "status": "ok",
            "dedup_size": len(self._seen_keys),
            "dedup_capacity": self._dedup_capacity,
            "behavior": self.behavior_snapshot(),
        }

    async def ingest(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize a raw source signal into an Event payload.

        Returns the normalized payload (also publishes it on the bus if
        one is bound). Duplicates by ``idempotency_key`` are dropped
        and return ``None``.
        """
        key = str(raw.get("idempotency_key") or raw.get("id") or raw.get("event_id", ""))
        if not key:
            raise ValueError("event missing idempotency_key / id / event_id")
        key = key[:_MAX_FIELD_CHARS]
        if key in self._seen_keys:
            self._seen_keys.move_to_end(key)
            self.record_behavior("deduped")
            return None
        event_payload = raw.get("payload")
        canonical_payload = event_payload if isinstance(event_payload, Mapping) else {}
        inventory_change = canonical_payload.get("inventory_change")
        resource_value = (
            inventory_change.get("resource") if isinstance(inventory_change, Mapping) else None
        )
        resource: Mapping[str, Any] = resource_value if isinstance(resource_value, Mapping) else {}

        payload: dict[str, Any] = {
            "producer_principal": "Huginn",
            "correlation_id": str(raw.get("correlation_id", key))[:_MAX_FIELD_CHARS],
            "incident_correlation": (
                "none"
                if str(raw.get("event_type", "")).startswith("inventory.")
                else str(raw.get("incident_correlation", "correlate"))[:_MAX_FIELD_CHARS]
            ),
            "idempotency_key": key,
            "event_id": _bound(raw.get("event_id") or key),
            "source": _bound(raw.get("source") or "unknown"),
            "resource_id": _bound(
                raw.get("resource_id") or raw.get("resource_ref") or resource.get("resource_id")
            ),
            "resource_type": _bound(raw.get("resource_type") or resource.get("type")),
            "event_type": str(raw.get("event_type", "generic"))[:_MAX_FIELD_CHARS],
            "attributes": _bound_attributes(raw.get("attributes", {})),
        }
        if isinstance(inventory_change, Mapping):
            payload["inventory_change"] = _bound_json(inventory_change)
            signal_kind = canonical_payload.get("signal_kind")
            if isinstance(signal_kind, str):
                payload["attributes"]["signal_kind"] = _bound(signal_kind)
        # Operator-proposal fields (`initiator_principal`, `action_type`,
        # `params`) are honored ONLY for an explicit operator request
        # (``event_type == "operator_request"``). This is the trust gate: a
        # rule-fired or external signal (Activity Log, anomaly) on the same
        # ingress topic can never carry operator-proposal semantics even if a
        # forged payload includes these keys - so an external producer cannot
        # spoof an initiator / a direct ActionType / the operator flag into the
        # judge pipeline. ``operator_initiated`` is coerced to a strict bool so
        # a truthy string ("false", "0") cannot flip the fail-closed RBAC logic.
        if payload["event_type"] == "operator_request":
            for passthrough in ("initiator_principal", "action_type", "params"):
                value = raw.get(passthrough)
                if value is not None:
                    payload[passthrough] = _bound(value)
            payload["operator_initiated"] = raw.get("operator_initiated") is True
        # Measurable behaviour: the sensing layer's ingest / dedup rates, so a
        # scenario can see an ingress flood (the flooding concern one layer up
        # from the judge). Recorded on the decision to emit, before publish.
        self.record_behavior("ingested")
        if "inventory_change" in payload and self._discovery_projector is not None:
            try:
                await self._discovery_projector(payload)
                self.record_behavior("discovery_projected")
            except Exception:
                self.record_behavior("discovery_projection_failed")
                raise
        if self.bus is not None:
            await self.bus.publish("Huginn", "object.event", payload)
        self._seen_keys[key] = None
        if len(self._seen_keys) > self._dedup_capacity:
            self._seen_keys.popitem(last=False)
        return payload

    # ---- conversational port -------------------------------------------

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "dedup_size": len(self._seen_keys),
            "dedup_capacity": self._dedup_capacity,
        }
        answer = (
            f"Ingesting and deduplicating events; {len(self._seen_keys)} key(s) "
            f"in the dedup window (capacity {self._dedup_capacity})."
        )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Huginn"]
