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
from fdai.shared.providers.state_store import StateStore

INVENTORY_CONFIGURATION_DELIVERY_KEY = "inventory-configuration:delivery"
INVENTORY_CONFIGURATION_DELIVERY_PREFIX = "inventory-configuration:generations:"


def configuration_delivery_key(generation: str) -> str:
    if not generation or generation != generation.strip() or len(generation) > 256:
        raise ValueError("inventory delivery generation MUST be canonical bounded text")
    return (
        INVENTORY_CONFIGURATION_DELIVERY_PREFIX
        + hashlib.sha256(generation.encode("utf-8")).hexdigest()
    )


async def prepare_configuration_delivery(
    store: StateStore, observation: PromotedInventoryObservation
) -> None:
    """Retain independent generation identity without reopening completed delivery."""
    key = configuration_delivery_key(observation.generation)
    pending = configuration_delivery_record(observation)
    completed = configuration_delivery_record(observation, completed=True)
    await store.write_state_if_absent(key, pending)
    retained = await store.read_state(key)
    if retained is None:
        raise ValueError("inventory configuration delivery record is unavailable")
    configuration_delivery_pending(retained, generation=observation.generation)
    if retained != pending and retained != completed:
        raise ValueError("inventory configuration delivery content changed")
    await store.write_state(INVENTORY_CONFIGURATION_DELIVERY_KEY, retained)


def configuration_projection_record(
    observation: PromotedInventoryObservation,
    *,
    ontology_release_digest: str,
    manifest_digest: str,
) -> dict[str, object]:
    for digest in (ontology_release_digest, manifest_digest):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            raise ValueError("inventory publication requires exact canonical digests")
    return {
        **configuration_delivery_record(observation),
        "status": "projected",
        "ontology_release_digest": ontology_release_digest,
        "manifest_digest": manifest_digest,
        "recorded_at": observation.recorded_at.isoformat() if observation.recorded_at else None,
    }


async def retained_configuration_delivery(
    store: StateStore, observation: PromotedInventoryObservation
) -> Mapping[str, object]:
    """Adopt only an exact legacy record; a newer generation is never a fallback."""
    key = configuration_delivery_key(observation.generation)
    retained = await store.read_state(key)
    if retained is None:
        legacy = await store.read_state(INVENTORY_CONFIGURATION_DELIVERY_KEY)
        if legacy not in (
            configuration_delivery_record(observation),
            configuration_delivery_record(observation, completed=True),
        ):
            raise ValueError("inventory configuration delivery content changed")
        if legacy is None:
            raise ValueError("inventory configuration delivery record is unavailable")
        configuration_delivery_pending(legacy, generation=observation.generation)
        await store.write_state_if_absent(key, legacy)
        retained = await store.read_state(key)
    if retained is None:
        raise ValueError("inventory configuration delivery record is unavailable")
    configuration_delivery_pending(retained, generation=observation.generation)
    return retained


async def complete_configuration_delivery(
    store: StateStore, observation: PromotedInventoryObservation
) -> None:
    retained = await retained_configuration_delivery(store, observation)
    pending = configuration_delivery_record(observation)
    completed = configuration_delivery_record(observation, completed=True)
    if retained != pending and retained != completed:
        raise ValueError("inventory configuration delivery content changed")
    await store.write_state(configuration_delivery_key(observation.generation), completed)
    legacy = await store.read_state(INVENTORY_CONFIGURATION_DELIVERY_KEY)
    if legacy is not None and legacy.get("generation") == observation.generation:
        await store.write_state(INVENTORY_CONFIGURATION_DELIVERY_KEY, completed)


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
