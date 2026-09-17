"""Publish promoted inventory Resources into deterministic rule evaluation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.inventory import ResourceRecord


async def publish_promoted_resource_events(
    observation: PromotedInventoryObservation,
    *,
    event_bus: EventBus,
    topic: str,
    scope_ref: str,
) -> int:
    """Publish one retry-stable configuration observation per Resource.

    Only a complete promoted generation is eligible. Broker failure propagates
    so promotion recovery can retry the same generation with identical event
    identities; downstream event ingest suppresses any already accepted rows.
    """
    if not observation.complete:
        raise ValueError("rule evaluation requires a complete promoted inventory")
    if observation.recorded_at is None or observation.recorded_at.tzinfo is None:
        raise ValueError("promoted inventory recorded_at MUST be timezone-aware")
    if not topic.strip() or not scope_ref.strip():
        raise ValueError("configuration event topic and scope_ref MUST be non-empty")

    resources = sorted(observation.resources, key=lambda item: item.resource_id)
    if len({resource.resource_id for resource in resources}) != len(resources):
        raise ValueError("promoted inventory contains duplicate Resource identities")

    generation_digest = _digest_text(observation.generation)
    for resource in resources:
        event = _resource_observation_event(
            resource,
            generation_digest=generation_digest,
            scope_ref=scope_ref,
            recorded_at=observation.recorded_at,
        )
        await event_bus.publish(
            topic,
            resource.resource_id,
            event.model_dump(mode="json"),
        )
    return len(resources)


def _resource_observation_event(
    resource: ResourceRecord,
    *,
    generation_digest: str,
    scope_ref: str,
    recorded_at: datetime,
) -> Event:
    resource_payload = {
        "resource_id": resource.resource_id,
        "type": resource.type,
        "props": dict(resource.props),
        "provider_ref": resource.provider_ref,
        "last_seen": resource.last_seen,
    }
    identity_digest = _digest_json(
        {
            "generation_digest": generation_digest,
            "resource": resource_payload,
            "scope_ref": scope_ref,
        }
    ).removeprefix("sha256:")
    detected_at = _resource_observed_at(resource, fallback=recorded_at)
    return Event(
        schema_version="1.0.0",
        event_id=uuid5(NAMESPACE_URL, f"fdai.inventory-snapshot://{identity_digest}"),
        idempotency_key=f"inventory-snapshot:{identity_digest}",
        source="fdai.delivery.inventory_configuration_events",
        event_type="inventory.resource_observed",
        resource_ref=resource.resource_id,
        payload={
            "signal_kind": "inventory.full_reconciliation",
            "resource": resource_payload,
            "inventory_observation": {
                "kind": "full",
                "properties_complete": True,
                "generation_digest": generation_digest,
                "scope_ref": scope_ref,
            },
        },
        detected_at=detected_at,
        ingested_at=datetime.now(tz=UTC),
        incident_correlation=IncidentCorrelation.NONE,
        mode=Mode.SHADOW,
    )


def _resource_observed_at(resource: ResourceRecord, *, fallback: datetime) -> datetime:
    if resource.last_seen is None:
        return fallback.astimezone(UTC)
    try:
        parsed = datetime.fromisoformat(resource.last_seen.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("promoted Resource last_seen MUST be a valid RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("promoted Resource last_seen MUST include a timezone")
    return parsed.astimezone(UTC)


def _digest_text(value: str) -> str:
    if not value:
        raise ValueError("promoted inventory generation MUST be non-empty")
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest_json(value: object) -> str:
    try:
        serialized = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("promoted Resource properties MUST be JSON-compatible") from exc
    return _digest_text(serialized)


__all__ = ["publish_promoted_resource_events"]
