"""Forward inventory delta records into the canonical control-loop event topic."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
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
_RECONCILIATION_CURSOR_FIELD = "relationship_reconciliation_after"
DEFAULT_DELTA_DEADLINE_SECONDS = 300.0


async def forward_inventory_delta(
    *,
    inventory: Inventory,
    state_store: StateStore,
    event_bus: EventBus,
    topic: str,
    scope: str,
    properties_complete: bool,
    deadline_seconds: float = DEFAULT_DELTA_DEADLINE_SECONDS,
    initial_replay_after: datetime | None = None,
) -> int:
    """Publish one delta stream and advance its cursor only at the final fence.

    Sparse recovery sources set ``properties_complete`` false so replay merges
    only their property mask and leaves relationships to full reconciliation.
    One deadline bounds cursor reads, provider iteration, publication, and final persistence.
    """
    if not math.isfinite(deadline_seconds) or deadline_seconds <= 0:
        raise ValueError("inventory delta deadline_seconds MUST be finite and > 0")
    if initial_replay_after is not None and initial_replay_after.tzinfo is None:
        raise ValueError("inventory delta initial_replay_after MUST be timezone-aware")
    try:
        async with asyncio.timeout(deadline_seconds):
            return await _forward_inventory_delta(
                inventory=inventory,
                state_store=state_store,
                event_bus=event_bus,
                topic=topic,
                scope=scope,
                properties_complete=properties_complete,
                initial_replay_after=initial_replay_after,
            )
    except TimeoutError as exc:
        raise RuntimeError("inventory delta stream exceeded its deadline") from exc


async def _forward_inventory_delta(
    *,
    inventory: Inventory,
    state_store: StateStore,
    event_bus: EventBus,
    topic: str,
    scope: str,
    properties_complete: bool,
    initial_replay_after: datetime | None,
) -> int:
    """Persist a final cursor only after the bounded stream has been fully published."""

    cursor_key = f"{_CURSOR_PREFIX}{scope}"
    saved = await state_store.read_state(cursor_key)
    replay_cutoff = (
        initial_replay_after.astimezone(UTC)
        if saved is None and initial_replay_after is not None
        else None
    )
    cursor = "" if saved is None else saved.get("cursor")
    if not isinstance(cursor, str):
        raise RuntimeError("inventory delta persisted cursor MUST be text")
    reconciliation_high_watermark = _cursor_reconciliation_after(saved)
    marker_key = f"{INVENTORY_RELATIONSHIP_RECONCILIATION_PREFIX}{scope}"
    previous_marker = await state_store.read_state(marker_key)
    previous_observed_at = _marker_observed_at(previous_marker)
    if previous_observed_at is not None and (
        reconciliation_high_watermark is None
        or previous_observed_at > reconciliation_high_watermark
    ):
        reconciliation_high_watermark = previous_observed_at
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
                    links=links_by_owner.get(resource.resource_id, ())
                    if properties_complete
                    else (),
                    properties_complete=properties_complete,
                ),
            )
            for resource in batch.resources
        )
        for resource, event in events:
            if replay_cutoff is not None and event.detected_at < replay_cutoff:
                continue
            await event_bus.publish(topic, resource.resource_id, event.model_dump(mode="json"))
            published += 1
    if final_cursor is None:
        raise RuntimeError("inventory delta stream ended without a final fence")
    if relationship_reconciliation_after is not None and (
        reconciliation_high_watermark is None
        or relationship_reconciliation_after > reconciliation_high_watermark
    ):
        await state_store.write_state(
            marker_key,
            {
                "observed_at": relationship_reconciliation_after.isoformat(),
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            },
        )
        reconciliation_high_watermark = relationship_reconciliation_after
    cursor_state = {"cursor": final_cursor}
    if reconciliation_high_watermark is not None:
        cursor_state[_RECONCILIATION_CURSOR_FIELD] = reconciliation_high_watermark.isoformat()
    await state_store.write_state(cursor_key, cursor_state)
    return published


def _resource_event(
    *,
    scope: str,
    resource: ResourceRecord,
    links: Sequence[LinkRecord],
    properties_complete: bool,
) -> Event:
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
    observation_kind = "full" if properties_complete else "partial"
    try:
        identity_document = json.dumps(
            {
                "scope": scope,
                "resource": resource_payload,
                "links": link_payloads,
                "observation_kind": observation_kind,
                "properties_complete": properties_complete,
            },
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
                "observation_kind": observation_kind,
                "properties_complete": properties_complete,
                "property_mask": sorted(resource.props),
                "scope_ref": scope,
                "operation": _optional_resource_text(resource, "operation"),
                "operation_status": _optional_resource_text(resource, "operationStatus"),
                "resource": resource_payload,
                "links_complete": False,
                "links": link_payloads,
            },
        },
        detected_at=detected_at,
        ingested_at=datetime.now(tz=UTC),
        incident_correlation=IncidentCorrelation.NONE,
        mode=Mode.SHADOW,
    )


def _optional_resource_text(resource: ResourceRecord, key: str) -> str | None:
    value = resource.props.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"inventory delta resource.props.{key} MUST be non-empty text or null")
    return value


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


def _cursor_reconciliation_after(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RuntimeError("inventory delta persisted cursor is malformed")
    raw = value.get(_RECONCILIATION_CURSOR_FIELD)
    if raw is None:
        return None
    try:
        return _parse_reconciliation_timestamp(raw)
    except ValueError as exc:
        raise RuntimeError("inventory delta persisted reconciliation cursor is malformed") from exc


__all__ = ["forward_inventory_delta"]
