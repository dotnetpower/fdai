"""Forward inventory delta records into the canonical control-loop event topic."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.inventory import (
    INVENTORY_RELATIONSHIP_RECONCILIATION_PREFIX,
    Inventory,
    LinkRecord,
    ResourceRecord,
)
from fdai.shared.providers.state_store import StateStore

_CURSOR_PREFIX = "inventory_delta_cursor:"


async def forward_inventory_delta(
    *,
    inventory: Inventory,
    state_store: StateStore,
    event_bus: EventBus,
    topic: str,
    scope: str,
) -> int:
    """Publish one delta stream and advance its cursor only at the final fence."""
    cursor_key = f"{_CURSOR_PREFIX}{scope}"
    saved = await state_store.read_state(cursor_key) or {}
    cursor = str(saved.get("cursor") or "")
    latest_cursor = cursor
    published = 0
    final_cursor: str | None = None
    saw_final = False
    relationship_reconciliation_after: datetime | None = None
    async for batch in inventory.delta(cursor):
        if saw_final:
            raise RuntimeError("inventory delta stream emitted data after final fence")
        if batch.cursor is not None:
            latest_cursor = batch.cursor
        if batch.final:
            saw_final = True
            final_cursor = latest_cursor
        if batch.relationship_reconciliation_after is not None:
            observed_at = _parse_reconciliation_timestamp(batch.relationship_reconciliation_after)
            if (
                relationship_reconciliation_after is None
                or observed_at > relationship_reconciliation_after
            ):
                relationship_reconciliation_after = observed_at
        links_by_owner = _links_by_owner(batch.resources, batch.links)
        events = tuple(
            (
                resource,
                _resource_event(
                    scope=scope,
                    resource=resource,
                    links=links_by_owner.get(resource.resource_id, ()),
                ),
            )
            for resource in batch.resources
        )
        for resource, event in events:
            await event_bus.publish(topic, resource.resource_id, event.model_dump(mode="json"))
            published += 1
    if final_cursor is None:
        raise RuntimeError("inventory delta stream ended without a final fence")
    if relationship_reconciliation_after is not None:
        marker_key = f"{INVENTORY_RELATIONSHIP_RECONCILIATION_PREFIX}{scope}"
        previous_marker = await state_store.read_state(marker_key)
        previous_observed_at = _marker_observed_at(previous_marker)
        if previous_observed_at is None or relationship_reconciliation_after > previous_observed_at:
            await state_store.write_state(
                marker_key,
                {"observed_at": relationship_reconciliation_after.isoformat()},
            )
    await state_store.write_state(cursor_key, {"cursor": final_cursor})
    return published


def _resource_event(*, scope: str, resource: ResourceRecord, links: Sequence[LinkRecord]) -> Event:
    resource_id = resource.resource_id
    resource_type = resource.type
    last_seen = resource.last_seen
    detected_at = _parse_timestamp(last_seen)
    resource_payload = {
        "resource_id": resource_id,
        "type": resource_type,
        "props": dict(resource.props),
        "provider_ref": resource.provider_ref,
        "last_seen": resource.last_seen,
    }
    link_payloads = [
        {
            "change_kind": "upsert",
            "from_id": link.from_id,
            "from_type": link.from_type,
            "link_type": link.link_type,
            "to_id": link.to_id,
            "to_type": link.to_type,
            "props": dict(link.link_props),
        }
        for link in sorted(links, key=lambda item: (item.from_id, item.link_type, item.to_id))
    ]
    try:
        identity_document = json.dumps(
            {"scope": scope, "resource": resource_payload, "links": link_payloads},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "inventory delta resource and relationship props MUST be JSON-compatible"
        ) from exc
    identity_digest = hashlib.sha256(identity_document.encode("utf-8")).hexdigest()
    return Event(
        schema_version="1.0.0",
        event_id=uuid5(NAMESPACE_URL, f"fdai.inventory-delta://{identity_digest}"),
        idempotency_key=f"inventory-delta:{identity_digest}",
        source="fdai.delivery.inventory_delta",
        event_type="inventory.resource_changed",
        resource_ref=resource_id,
        payload={
            "signal_kind": "azure.activity_log",
            "resource": resource_payload,
            "inventory_change": {
                "kind": "upsert",
                "resource": resource_payload,
                "links": link_payloads,
            },
        },
        detected_at=detected_at,
        ingested_at=datetime.now(tz=UTC),
        incident_correlation=IncidentCorrelation.NONE,
        mode=Mode.SHADOW,
    )


def _links_by_owner(
    resources: Sequence[ResourceRecord], links: Sequence[LinkRecord]
) -> dict[str, tuple[LinkRecord, ...]]:
    resource_ids = {resource.resource_id for resource in resources}
    if len(resource_ids) != len(resources):
        raise RuntimeError("inventory delta batch contains a duplicate resource_id")
    grouped: dict[str, list[LinkRecord]] = defaultdict(list)
    for link in links:
        owner_id = link.to_id if link.link_type == "contains" else link.from_id
        if owner_id not in resource_ids:
            raise RuntimeError("inventory delta link owner resource is missing from its batch")
        grouped[owner_id].append(link)
    return {owner_id: tuple(owned) for owner_id, owned in grouped.items()}


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("inventory delta resource.last_seen MUST be an RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "inventory delta resource.last_seen MUST be a valid RFC 3339 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError("inventory delta resource.last_seen MUST include a timezone")
    return parsed.astimezone(UTC)


def _parse_reconciliation_timestamp(value: object) -> datetime:
    try:
        return _parse_timestamp(value)
    except ValueError as exc:
        raise ValueError(
            "inventory delta relationship_reconciliation_after MUST be RFC 3339"
        ) from exc


def _marker_observed_at(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RuntimeError("inventory relationship reconciliation marker is malformed")
    try:
        return _parse_reconciliation_timestamp(value.get("observed_at"))
    except ValueError as exc:
        raise RuntimeError("inventory relationship reconciliation marker is malformed") from exc


__all__ = ["forward_inventory_delta"]
