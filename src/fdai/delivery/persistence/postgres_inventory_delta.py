"""Durable latest-per-key projection for real-time inventory changes."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg

from fdai.delivery.persistence.postgres_inventory_snapshot import (
    _PROMOTION_LOCK,
    PostgresInventorySnapshotStoreConfig,
)

_CHANGE_KINDS = frozenset({"upsert", "delete"})
_LINK_TYPES = frozenset({"contains", "attached_to", "depends_on"})


@dataclass(frozen=True, slots=True)
class InventoryDeltaApplyResult:
    """Rows accepted into the real-time inventory overlay."""

    resources: int
    links: int


class PostgresInventoryDeltaProjector:
    """Apply one Huginn-normalized inventory change under the promotion lock."""

    def __init__(self, *, config: PostgresInventorySnapshotStoreConfig) -> None:
        self._config = config

    async def __call__(self, payload: Mapping[str, Any]) -> InventoryDeltaApplyResult:
        change = _inventory_change(payload)
        if change is None:
            return InventoryDeltaApplyResult(resources=0, links=0)
        change_kind = _choice(change, "kind", _CHANGE_KINDS)
        resource = _mapping(change, "resource")
        resource_id = _required_str(resource, "resource_id")
        resource_type = _required_str(resource, "type")
        observed_at = _timestamp(resource.get("last_seen"))
        event_id = _required_str(payload, "event_id")
        idempotency_key = _required_str(payload, "idempotency_key")
        props = resource.get("props", {})
        if not isinstance(props, Mapping):
            raise ValueError("inventory_change.resource.props MUST be an object")
        provider_ref = resource.get("provider_ref")
        if provider_ref is not None and not isinstance(provider_ref, str):
            raise ValueError("inventory_change.resource.provider_ref MUST be a string or null")
        links = _links(change.get("links", ()))

        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute("SELECT pg_advisory_xact_lock(%s)", (_PROMOTION_LOCK,))
                coverage_cursor = await connection.execute(
                    "SELECT 1 FROM inventory_active a "
                    "JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                    "WHERE a.singleton=TRUE AND s.status='active' "
                    "AND s.resource_types ? %s",
                    (resource_type,),
                )
                if await coverage_cursor.fetchone() is None:
                    raise ValueError(
                        "inventory change resource type is outside active snapshot coverage"
                    )
                resource_cursor = await connection.execute(
                    "INSERT INTO inventory_realtime_resource "
                    "(resource_id, change_kind, resource_type, props, provider_ref, "
                    "observed_at, event_id, idempotency_key) "
                    "VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s) "
                    "ON CONFLICT (resource_id) DO UPDATE SET "
                    "change_kind=EXCLUDED.change_kind, resource_type=EXCLUDED.resource_type, "
                    "props=EXCLUDED.props, provider_ref=EXCLUDED.provider_ref, "
                    "observed_at=EXCLUDED.observed_at, event_id=EXCLUDED.event_id, "
                    "idempotency_key=EXCLUDED.idempotency_key, applied_at=NOW() "
                    "WHERE inventory_realtime_resource.observed_at <= EXCLUDED.observed_at",
                    (
                        resource_id,
                        change_kind,
                        resource_type,
                        json.dumps(dict(props), default=str),
                        provider_ref,
                        observed_at,
                        event_id,
                        idempotency_key,
                    ),
                )
                applied_links = 0
                for link in links:
                    link_kind = _choice(link, "change_kind", _CHANGE_KINDS)
                    link_type = _choice(link, "link_type", _LINK_TYPES)
                    link_props = link.get("props", {})
                    if not isinstance(link_props, Mapping):
                        raise ValueError("inventory_change link props MUST be an object")
                    link_cursor = await connection.execute(
                        "INSERT INTO inventory_realtime_link "
                        "(from_id, from_type, link_type, to_id, to_type, change_kind, props, "
                        "observed_at, event_id, idempotency_key) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s) "
                        "ON CONFLICT (from_id, link_type, to_id) DO UPDATE SET "
                        "from_type=EXCLUDED.from_type, to_type=EXCLUDED.to_type, "
                        "change_kind=EXCLUDED.change_kind, props=EXCLUDED.props, "
                        "observed_at=EXCLUDED.observed_at, event_id=EXCLUDED.event_id, "
                        "idempotency_key=EXCLUDED.idempotency_key, applied_at=NOW() "
                        "WHERE inventory_realtime_link.observed_at <= EXCLUDED.observed_at",
                        (
                            _required_str(link, "from_id"),
                            _required_str(link, "from_type"),
                            link_type,
                            _required_str(link, "to_id"),
                            _required_str(link, "to_type"),
                            link_kind,
                            json.dumps(dict(link_props), default=str),
                            observed_at,
                            event_id,
                            idempotency_key,
                        ),
                    )
                    applied_links += max(0, link_cursor.rowcount)
        return InventoryDeltaApplyResult(
            resources=max(0, resource_cursor.rowcount),
            links=applied_links,
        )

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _inventory_change(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    direct = payload.get("inventory_change")
    if isinstance(direct, Mapping):
        return direct
    event_payload = payload.get("payload")
    if isinstance(event_payload, Mapping):
        nested = event_payload.get("inventory_change")
        if isinstance(nested, Mapping):
            return nested
    return None


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise ValueError(f"inventory_change.{key} MUST be an object")
    return item


def _required_str(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} MUST be a non-empty string")
    return item


def _choice(value: Mapping[str, Any], key: str, allowed: frozenset[str]) -> str:
    item = _required_str(value, key)
    if item not in allowed:
        raise ValueError(f"{key} MUST be one of {sorted(allowed)}")
    return item


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("inventory_change.resource.last_seen MUST be an RFC 3339 string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            "inventory_change.resource.last_seen MUST be a valid RFC 3339 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError("inventory_change.resource.last_seen MUST include a timezone")
    return parsed.astimezone(UTC)


def _links(value: object) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError("inventory_change.links MUST be an array")
    if not all(isinstance(link, Mapping) for link in value):
        raise ValueError("inventory_change.links MUST contain only objects")
    return value


__all__ = ["InventoryDeltaApplyResult", "PostgresInventoryDeltaProjector"]
