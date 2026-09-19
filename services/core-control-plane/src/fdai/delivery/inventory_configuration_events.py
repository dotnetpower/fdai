"""Publish promoted inventory Resources into deterministic rule evaluation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.inventory import ResourceRecord

INVENTORY_CONFIGURATION_DELIVERY_KEY = "inventory-configuration:delivery"


def configuration_delivery_record(
    observation: PromotedInventoryObservation,
    *,
    completed: bool = False,
) -> dict[str, object]:
    """Bind a durable handoff marker to exact retry-stable Resource observations."""
    if not observation.complete or observation.recorded_at is None:
        raise ValueError("configuration delivery requires a complete recorded observation")
    digest = hashlib.sha256(observation.generation.encode("utf-8"))
    for resource in sorted(observation.resources, key=lambda item: item.resource_id):
        digest.update(
            _digest_json(
                {
                    "id": resource.resource_id,
                    "type": resource.type,
                    "props": dict(resource.props),
                    "provider_ref": resource.provider_ref,
                    "last_seen": resource.last_seen,
                }
            ).encode("ascii")
        )
    return {
        "schema_version": "1.0.0",
        "generation": observation.generation,
        "observation_digest": "sha256:" + digest.hexdigest(),
        "status": "completed" if completed else "pending",
        "resource_count": len(observation.resources),
        "execution_authority": False,
    }


def configuration_delivery_pending(value: Mapping[str, object], *, generation: str) -> bool:
    """Reject malformed current-generation delivery state rather than losing a retry."""
    if value.get("generation") != generation:
        return False
    resource_count = value.get("resource_count")
    if (
        value.get("schema_version") != "1.0.0"
        or value.get("status") not in {"pending", "completed"}
        or value.get("execution_authority") is not False
        or not isinstance(value.get("observation_digest"), str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("observation_digest"))) is None
        or type(resource_count) is not int
        or not 0 <= resource_count <= 50_000
        or set(value)
        != {
            "schema_version",
            "generation",
            "observation_digest",
            "status",
            "resource_count",
            "execution_authority",
        }
    ):
        raise ValueError("inventory configuration delivery marker is invalid")
    return value["status"] == "pending"


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
    if any(resource.props.get("_truncated") is True for resource in resources):
        raise ValueError("truncated inventory cannot publish complete configuration observations")
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
