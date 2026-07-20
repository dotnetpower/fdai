"""Forward inventory delta records into the canonical control-loop event topic."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.inventory import Inventory, ResourceRecord
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
    published = 0
    final_cursor: str | None = None
    async for batch in inventory.delta(cursor):
        if batch.final:
            final_cursor = batch.cursor if batch.cursor is not None else cursor
            continue
        for resource in batch.resources:
            event = _resource_event(scope=scope, resource=resource)
            await event_bus.publish(topic, resource.resource_id, event.model_dump(mode="json"))
            published += 1
    if final_cursor is None:
        raise RuntimeError("inventory delta stream ended without a final fence")
    await state_store.write_state(cursor_key, {"cursor": final_cursor})
    return published


def _resource_event(*, scope: str, resource: ResourceRecord) -> Event:
    resource_id = resource.resource_id
    resource_type = resource.type
    last_seen = resource.last_seen
    detected_at = _parse_timestamp(last_seen)
    identity = f"{scope}:{resource_id}:{resource_type}:{last_seen or 'unknown'}"
    resource_payload = {
        "resource_id": resource_id,
        "type": resource_type,
        "props": dict(resource.props),
        "provider_ref": resource.provider_ref,
        "last_seen": resource.last_seen,
    }
    return Event(
        schema_version="1.0.0",
        event_id=uuid5(NAMESPACE_URL, f"fdai.inventory-delta://{identity}"),
        idempotency_key=f"inventory-delta:{identity}",
        source="fdai.delivery.inventory_delta",
        event_type="inventory.resource_changed",
        resource_ref=resource_id,
        payload={
            "signal_kind": "azure.activity_log",
            "resource": resource_payload,
            "inventory_change": {
                "kind": "upsert",
                "resource": resource_payload,
                "links": [],
            },
        },
        detected_at=detected_at,
        ingested_at=datetime.now(tz=UTC),
        incident_correlation=IncidentCorrelation.NONE,
        mode=Mode.SHADOW,
    )


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed
        except ValueError:
            pass
    return datetime.now(tz=UTC)


__all__ = ["forward_inventory_delta"]
