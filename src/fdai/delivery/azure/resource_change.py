"""Normalize Azure resource change events for Huginn discovery ingress."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final
from uuid import NAMESPACE_URL, UUID, uuid5

from fdai.delivery.azure.arg_projection import (
    arm_id_to_type,
    build_arm_to_neutral_map,
    extract_rg_contains_links,
    to_neutral_id,
    truncate_props,
)
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.inventory import ResourceRecord

_SOURCE: Final[str] = "azure_event_grid.resource_change"
_WRITE_EVENT: Final[str] = "Microsoft.Resources.ResourceWriteSuccess"
_DELETE_EVENT: Final[str] = "Microsoft.Resources.ResourceDeleteSuccess"
_CHANGE_KIND: Final[dict[str, str]] = {
    _WRITE_EVENT: "upsert",
    _DELETE_EVENT: "delete",
}
_MAX_PROPS_BYTES: Final[int] = 16 * 1024


def normalize_resource_change_events(
    envelope: Any,
    *,
    resource_types: ResourceTypeRegistry,
    ingested_at: datetime | None = None,
) -> tuple[Event, ...]:
    """Return canonical inventory events from an Event Grid envelope.

    Unsupported event types and resource types are ignored. Malformed records
    raise at the envelope boundary so the Kafka consumer can dead-letter the
    batch instead of silently advancing past an unparseable resource change.
    """

    records = _records(envelope)
    arm_to_neutral = build_arm_to_neutral_map(resource_types)
    received = ingested_at or datetime.now(tz=UTC)
    events: list[Event] = []
    for index, record in enumerate(records):
        try:
            normalized = _normalize_one(
                record,
                arm_to_neutral=arm_to_neutral,
                ingested_at=received,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"resource change record {index} is invalid: {exc}") from exc
        if normalized is not None:
            events.append(normalized)
    return tuple(events)


def _records(envelope: Any) -> Sequence[Mapping[str, Any]]:
    if isinstance(envelope, list):
        if not all(isinstance(record, Mapping) for record in envelope):
            raise ValueError("resource change envelope contains a non-object record")
        return envelope
    if isinstance(envelope, Mapping):
        return (envelope,)
    raise ValueError("resource change envelope MUST be an object or array")


def _normalize_one(
    record: Mapping[str, Any],
    *,
    arm_to_neutral: Mapping[str, str],
    ingested_at: datetime,
) -> Event | None:
    event_type = record.get("eventType")
    if not isinstance(event_type, str):
        raise ValueError("eventType MUST be a string")
    change_kind = _CHANGE_KIND.get(event_type)
    if change_kind is None:
        return None

    data = record.get("data")
    if not isinstance(data, Mapping):
        raise ValueError("data MUST be an object")
    provider_ref = data.get("resourceUri") or record.get("subject")
    if not isinstance(provider_ref, str) or not provider_ref.startswith("/"):
        raise ValueError("data.resourceUri or subject MUST be an ARM resource id")

    arm_type = _resource_arm_type(provider_ref)
    if arm_type is None:
        raise ValueError("resource ARM type cannot be resolved")
    resource_type = arm_to_neutral.get(arm_type.lower())
    if resource_type is None:
        raise ValueError("resource ARM type is not registered in the canonical vocabulary")

    observed_at = _parse_timestamp(record.get("eventTime"))
    resource_id = to_neutral_id(provider_ref)
    props = truncate_props(
        {
            "operation": data.get("operationName"),
            "status": data.get("status"),
            "resourceProvider": data.get("resourceProvider"),
        },
        max_bytes=_MAX_PROPS_BYTES,
    )
    resource = ResourceRecord(
        resource_id=resource_id,
        type=resource_type,
        props=props,
        provider_ref=provider_ref,
        last_seen=observed_at.isoformat(),
    )
    links = extract_rg_contains_links((resource,))
    raw_event_id = str(record.get("id") or "").strip()
    if not raw_event_id:
        raise ValueError("id MUST be a non-empty string")
    event_id = _event_id(raw_event_id)
    idempotency_key = f"azure-resource-change:{raw_event_id}"
    inventory_change = {
        "kind": change_kind,
        "resource": {
            "resource_id": resource.resource_id,
            "type": resource.type,
            "props": dict(resource.props),
            "provider_ref": resource.provider_ref,
            "last_seen": resource.last_seen,
        },
        "links": [
            {
                "change_kind": change_kind,
                "from_id": link.from_id,
                "from_type": link.from_type,
                "link_type": link.link_type,
                "to_id": link.to_id,
                "to_type": link.to_type,
                "props": dict(link.link_props),
            }
            for link in links
        ],
    }
    return Event(
        schema_version="1.0.0",
        event_id=event_id,
        idempotency_key=idempotency_key,
        correlation_id=f"inventory:{resource_id}",
        source=_SOURCE,
        event_type="inventory.resource_changed",
        resource_ref=resource_id,
        payload={
            "signal_kind": "azure.activity_log",
            "inventory_change": inventory_change,
        },
        detected_at=observed_at,
        ingested_at=ingested_at,
        mode=Mode.SHADOW,
    )


def _resource_arm_type(provider_ref: str) -> str | None:
    arm_type = arm_id_to_type(provider_ref)
    if arm_type is not None:
        return arm_type
    lowered = provider_ref.lower().rstrip("/")
    if "/resourcegroups/" in lowered and "/providers/" not in lowered:
        return "Microsoft.Resources/resourceGroups"
    return None


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("eventTime MUST be a non-empty RFC 3339 string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("eventTime MUST be a valid RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("eventTime MUST include a timezone")
    return parsed.astimezone(UTC)


def _event_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        return uuid5(NAMESPACE_URL, f"fdai.azure-resource-change://{value}")


__all__ = ["normalize_resource_change_events"]
