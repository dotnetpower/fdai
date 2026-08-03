"""Huginn - Event Collector (Wave 3 behavior).

Huginn normalizes incoming raw signals into `Event` payloads, dedups
by stable key, and publishes to `object.event`. Wave 3 implements the
in-process ingestion; adapter integration for Azure Activity Log lives
behind a provider protocol added in a later wave.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import IntrospectionResult, capability_facts
from fdai.agents._framework.pantheon import _HUGINN
from fdai.core.case_history import OperationalCaseInput

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
        out[str(key)[:_MAX_FIELD_CHARS]] = _bound_json(value, depth=1)
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


def _change_projection(
    *,
    raw: Mapping[str, Any],
    canonical_payload: Mapping[str, Any],
    event_payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    declared = raw.get("change") or canonical_payload.get("change")
    change = declared if isinstance(declared, Mapping) else None
    signal_kind = canonical_payload.get("signal_kind")
    event_type = str(event_payload["event_type"])
    inferred_activity = signal_kind == "azure.activity_log"
    inferred_planned = event_type in {
        "change.requested",
        "change.planned",
        "deployment.requested",
        "iac.plan",
        "iac.pull_request",
        "release.ready",
    }
    if change is None and not inferred_activity and not inferred_planned:
        return None

    def value(name: str, *fallbacks: object) -> object | None:
        candidate: object | None = change.get(name) if change is not None else None
        if candidate is not None:
            return candidate
        return next((item for item in fallbacks if item is not None), None)

    occurred_at = str(
        value(
            "occurred_at",
            raw.get("occurred_at"),
            raw.get("detected_at"),
            raw.get("created_at"),
        )
        or ""
    )
    try:
        parsed_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("change occurred_at MUST be RFC 3339") from exc
    if parsed_at.tzinfo is None:
        raise ValueError("change occurred_at MUST be timezone-aware")

    target_ref = str(value("target_ref", event_payload.get("resource_id")) or "").strip()
    if not target_ref:
        raise ValueError("change target_ref MUST be non-empty")
    actor = canonical_payload.get("actor")
    actor_ref = value(
        "actor_ref",
        raw.get("initiator_principal"),
        actor.get("principal_id") if isinstance(actor, Mapping) else actor,
        raw.get("source"),
    )
    actor_ref = str(actor_ref or "").strip()
    if not actor_ref:
        raise ValueError("change actor_ref MUST be non-empty")

    change_id = str(value("id", event_payload.get("event_id")) or "").strip()
    if not change_id:
        raise ValueError("change id MUST be non-empty")
    default_status = "observed" if inferred_activity else "planned"
    default_intent = "detected" if inferred_activity else "planned"
    projection: dict[str, Any] = {
        "producer_principal": "Huginn",
        "correlation_id": event_payload["correlation_id"],
        "idempotency_key": f"change:{event_payload['idempotency_key']}",
        "id": change_id[:_MAX_FIELD_CHARS],
        "change_kind": str(value("change_kind", event_type) or "")[:_MAX_FIELD_CHARS],
        "source_kind": str(value("source_kind", event_payload.get("source")) or "")[
            :_MAX_FIELD_CHARS
        ],
        "intent_kind": str(value("intent_kind", default_intent) or "")[:_MAX_FIELD_CHARS],
        "target_ref": target_ref[:_MAX_FIELD_CHARS],
        "actor_ref": actor_ref[:_MAX_FIELD_CHARS],
        "status": str(value("status", default_status) or "")[:_MAX_FIELD_CHARS],
        "occurred_at": parsed_at.isoformat(),
        "evidence_ref": str(value("evidence_ref", f"event:{event_payload['event_id']}") or "")[
            :_MAX_FIELD_CHARS
        ],
    }
    for field in (
        "desired_state_digest",
        "plan_receipt_ref",
        "window_ref",
        "incident_ref",
        "process_ref",
    ):
        optional = value(field)
        if optional is not None and str(optional).strip():
            projection[field] = str(optional)[:_MAX_FIELD_CHARS]
    return projection


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
        detection_readiness = canonical_payload.get("detection_readiness")
        resource_value = (
            inventory_change.get("resource") if isinstance(inventory_change, Mapping) else None
        )
        resource: Mapping[str, Any] = resource_value if isinstance(resource_value, Mapping) else {}

        event_type = str(raw.get("event_type", "generic"))[:_MAX_FIELD_CHARS]
        attributes = _bound_attributes(raw.get("attributes", {}))
        correlation_id = str(raw.get("correlation_id", key))[:_MAX_FIELD_CHARS]
        if event_type == "case_history.operational_case.v1":
            raw_attributes = raw.get("attributes")
            if isinstance(raw_attributes, Mapping):
                try:
                    operational_case = OperationalCaseInput.from_mapping(raw_attributes)
                    attributes = operational_case.to_mapping()
                    correlation_id = operational_case.failure_fingerprint.digest
                except (TypeError, ValueError):
                    pass
        payload: dict[str, Any] = {
            "producer_principal": "Huginn",
            "correlation_id": correlation_id,
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
            "event_type": event_type,
            "attributes": attributes,
        }
        severity = raw.get("severity") or canonical_payload.get("severity")
        if isinstance(severity, str) and severity.strip():
            payload["severity"] = _bound(severity)
        if isinstance(inventory_change, Mapping):
            payload["inventory_change"] = _bound_json(inventory_change)
            signal_kind = canonical_payload.get("signal_kind")
            if isinstance(signal_kind, str):
                payload["attributes"]["signal_kind"] = _bound(signal_kind)
        if isinstance(detection_readiness, Mapping):
            for field in (
                "dimension",
                "status",
                "observed_at",
                "expires_at",
                "source",
                "evidence_digest",
                "detail_code",
                "pass_id",
            ):
                value = detection_readiness.get(field)
                if value is not None:
                    payload["attributes"][field] = _bound(value)
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
            workflow_action = raw.get("workflow_action")
            if isinstance(workflow_action, Mapping):
                payload["workflow_action"] = _bound_json(workflow_action)
        change_projection = _change_projection(
            raw=raw,
            canonical_payload=canonical_payload,
            event_payload=payload,
        )
        if change_projection is not None:
            payload["normalized_change"] = dict(change_projection)
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
            if change_projection is not None:
                await self.bus.publish("Huginn", "object.change", change_projection)
        self._seen_keys[key] = None
        if len(self._seen_keys) > self._dedup_capacity:
            self._seen_keys.popitem(last=False)
        return payload

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Ingress answers rest on signals seen; an idle collector has none."""
        return bool(self._seen_keys) or self.behavior_snapshot().get("ingested", 0) > 0

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        behavior = self.behavior_snapshot()
        facts = {
            **capability_facts(self.spec),
            "dedup_size": len(self._seen_keys),
            "dedup_capacity": self._dedup_capacity,
            "ingested_count": behavior.get("ingested", 0),
            "deduped_count": behavior.get("deduped", 0),
            # A full window has evicted its oldest keys, so a miss there is
            # uncertainty rather than proof a signal never arrived.
            "dedup_window_full": len(self._seen_keys) >= self._dedup_capacity,
        }
        answer = (
            f"Ingesting and deduplicating events; {len(self._seen_keys)} key(s) "
            f"in the dedup window (capacity {self._dedup_capacity})."
        )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Huginn"]
