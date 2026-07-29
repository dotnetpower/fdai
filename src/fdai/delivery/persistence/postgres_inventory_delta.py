"""Durable latest-per-key projection for real-time inventory changes."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres_inventory_snapshot import (
    _PROMOTION_LOCK,
    PostgresInventorySnapshotStoreConfig,
)

_CHANGE_KINDS = frozenset({"upsert", "delete"})
_LINK_TYPES = frozenset({"contains", "attached_to", "depends_on"})
_DEFAULT_MAX_LINKS = 256
_DEFAULT_MAX_RECONCILED_LINKS = 4096
_DEFAULT_MAX_FUTURE_SKEW_SECONDS = 300
_RESOURCE_LOCK_SEED = 0x46444149
_GRAPH_RECONCILIATION_LOCK = 732_410_992
_RESOURCE_LOCK_SQL = (
    "SELECT pg_advisory_xact_lock("
    "-1 - (hashtextextended(resource_id, %s) & 9223372036854775807)) "
    "FROM (SELECT resource_id FROM unnest(%s::text[]) AS item(resource_id) "
    "ORDER BY resource_id) AS ordered_resources"
)
_EFFECTIVE_LINKS_CTE = (
    "WITH effective_links AS ("
    "SELECT l.from_id, l.from_type, l.link_type, l.to_id, l.to_type, l.props "
    "FROM inventory_snapshot_link l WHERE l.snapshot_id=%s AND NOT EXISTS ("
    "SELECT 1 FROM inventory_realtime_link d WHERE d.from_id=l.from_id "
    "AND d.link_type=l.link_type AND d.to_id=l.to_id) "
    "UNION ALL SELECT d.from_id, d.from_type, d.link_type, d.to_id, d.to_type, d.props "
    "FROM inventory_realtime_link d WHERE d.change_kind='upsert') "
)
_EFFECTIVE_RESOURCE_TYPES_QUERY = (
    "WITH effective_resources AS ("
    "SELECT r.resource_id, r.resource_type FROM inventory_snapshot_resource r "
    "WHERE r.snapshot_id=%s AND NOT EXISTS ("
    "SELECT 1 FROM inventory_realtime_resource d WHERE d.resource_id=r.resource_id) "
    "UNION ALL SELECT d.resource_id, d.resource_type FROM inventory_realtime_resource d "
    "WHERE d.change_kind='upsert') "
    "SELECT resource_id, resource_type FROM effective_resources "
    "WHERE resource_id=ANY(%s::text[])"
)
_UPSERT_REALTIME_LINK = (
    "INSERT INTO inventory_realtime_link "
    "(from_id, from_type, link_type, to_id, to_type, change_kind, props, "
    "observed_at, event_id, idempotency_key) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s) "
    "ON CONFLICT (from_id, link_type, to_id) DO UPDATE SET "
    "from_type=EXCLUDED.from_type, to_type=EXCLUDED.to_type, "
    "change_kind=EXCLUDED.change_kind, props=EXCLUDED.props, "
    "observed_at=EXCLUDED.observed_at, event_id=EXCLUDED.event_id, "
    "idempotency_key=EXCLUDED.idempotency_key, applied_at=NOW() "
    "WHERE inventory_realtime_link.observed_at < EXCLUDED.observed_at "
    "OR (inventory_realtime_link.observed_at = EXCLUDED.observed_at "
    "AND ((inventory_realtime_link.change_kind <> 'delete' "
    "AND EXCLUDED.change_kind = 'delete') OR "
    "(inventory_realtime_link.change_kind = EXCLUDED.change_kind "
    "AND inventory_realtime_link.event_id < EXCLUDED.event_id)))"
)
_LOGGER = logging.getLogger(__name__)


class InventoryDeltaApplyOutcome(StrEnum):
    """Reason one inventory delta projection returned."""

    APPLIED = "applied"
    NOT_APPLICABLE = "not_applicable"
    ORDERING_REJECTED = "ordering_rejected"
    SNAPSHOT_COVERED = "snapshot_covered"


@dataclass(frozen=True, slots=True)
class InventoryDeltaApplyResult:
    """Rows accepted into the real-time inventory overlay."""

    resources: int
    links: int
    outcome: InventoryDeltaApplyOutcome = InventoryDeltaApplyOutcome.APPLIED


class PostgresInventoryDeltaProjector:
    """Apply one Huginn-normalized inventory change under the promotion lock."""

    def __init__(
        self,
        *,
        config: PostgresInventorySnapshotStoreConfig,
        clock: Callable[[], datetime] | None = None,
        max_future_skew_seconds: int = _DEFAULT_MAX_FUTURE_SKEW_SECONDS,
        max_links: int = _DEFAULT_MAX_LINKS,
        max_reconciled_links: int = _DEFAULT_MAX_RECONCILED_LINKS,
    ) -> None:
        if max_future_skew_seconds < 0:
            raise ValueError("max_future_skew_seconds MUST be non-negative")
        if max_links < 1:
            raise ValueError("max_links MUST be positive")
        if max_reconciled_links < max_links:
            raise ValueError("max_reconciled_links MUST be >= max_links")
        self._config = config
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._max_future_skew_seconds = max_future_skew_seconds
        self._max_links = max_links
        self._max_reconciled_links = max_reconciled_links

    async def __call__(self, payload: Mapping[str, Any]) -> InventoryDeltaApplyResult:
        event_type = payload.get("event_type")
        if event_type is not None and event_type != "inventory.resource_changed":
            return InventoryDeltaApplyResult(
                resources=0,
                links=0,
                outcome=InventoryDeltaApplyOutcome.NOT_APPLICABLE,
            )
        change = _inventory_change(payload)
        if change is None:
            return InventoryDeltaApplyResult(
                resources=0,
                links=0,
                outcome=InventoryDeltaApplyOutcome.NOT_APPLICABLE,
            )
        change_kind = _choice(change, "kind", _CHANGE_KINDS)
        resource = _mapping(change, "resource")
        resource_id = _required_str(resource, "resource_id")
        resource_type = _required_str(resource, "type")
        observed_at = _timestamp(resource.get("last_seen"))
        now = self._clock()
        if now.tzinfo is None:
            raise RuntimeError("inventory delta clock MUST be timezone-aware")
        if observed_at > now.astimezone(UTC) + timedelta(seconds=self._max_future_skew_seconds):
            raise ValueError("inventory change observation exceeds the allowed future skew")
        event_id = _required_str(payload, "event_id")
        idempotency_key = _required_str(payload, "idempotency_key")
        props = resource.get("props", {})
        if not isinstance(props, Mapping):
            raise ValueError("inventory_change.resource.props MUST be an object")
        resource_props_json = _canonical_json_mapping(props, "inventory_change.resource.props")
        provider_ref = resource.get("provider_ref")
        if provider_ref is not None and not isinstance(provider_ref, str):
            raise ValueError("inventory_change.resource.provider_ref MUST be a string or null")
        links = _links(change.get("links", ()))
        link_props_json = tuple(
            _canonical_json_mapping(link.get("props", {}), "inventory_change link.props")
            for link in links
        )
        links_complete = _optional_bool(change, "links_complete", default=False)
        if len(links) > self._max_links:
            raise ValueError(f"inventory_change.links exceeds cap ({self._max_links})")
        _reject_duplicate_link_keys(links)
        link_kinds = tuple(_choice(link, "change_kind", _CHANGE_KINDS) for link in links)
        if change_kind == "delete" and any(kind != "delete" for kind in link_kinds):
            raise ValueError("inventory resource delete can carry only link deletes")
        if links_complete and any(kind != "upsert" for kind in link_kinds):
            raise ValueError("complete inventory links can carry only link upserts")
        if any(not _link_owned_by(resource_id, link) for link in links):
            raise ValueError("inventory change relationships MUST be owned by the changed resource")
        covered_resource_types = _covered_resource_types(resource_type, links)
        reconcile_graph = change_kind == "delete" or links_complete

        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await _acquire_inventory_gate(connection, exclusive_graph=reconcile_graph)
                coverage_cursor = await connection.execute(
                    "SELECT s.id, s.started_at FROM inventory_active a "
                    "JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                    "WHERE a.singleton=TRUE AND s.status='active' "
                    "AND s.resource_types ?& %s",
                    (list(covered_resource_types),),
                )
                coverage = await coverage_cursor.fetchone()
                if coverage is None:
                    raise ValueError(
                        "inventory change resource or link endpoint type is outside "
                        "active snapshot coverage"
                    )
                if observed_at <= coverage["started_at"]:
                    _log_ignored_delta(event_id, InventoryDeltaApplyOutcome.SNAPSHOT_COVERED)
                    return InventoryDeltaApplyResult(
                        resources=0,
                        links=0,
                        outcome=InventoryDeltaApplyOutcome.SNAPSHOT_COVERED,
                    )
                await _acquire_resource_locks(
                    connection,
                    (resource_id,) if reconcile_graph else _lock_resource_ids(resource_id, links),
                )
                await _validate_resource_type(
                    connection,
                    snapshot_id=str(coverage["id"]),
                    resource_id=resource_id,
                    resource_type=resource_type,
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
                    "WHERE inventory_realtime_resource.observed_at < EXCLUDED.observed_at "
                    "OR (inventory_realtime_resource.observed_at = EXCLUDED.observed_at "
                    "AND ((inventory_realtime_resource.change_kind <> 'delete' "
                    "AND EXCLUDED.change_kind = 'delete') OR "
                    "(inventory_realtime_resource.change_kind = EXCLUDED.change_kind "
                    "AND inventory_realtime_resource.event_id < EXCLUDED.event_id)))",
                    (
                        resource_id,
                        change_kind,
                        resource_type,
                        resource_props_json,
                        provider_ref,
                        observed_at,
                        event_id,
                        idempotency_key,
                    ),
                )
                if resource_cursor.rowcount <= 0:
                    _log_ignored_delta(event_id, InventoryDeltaApplyOutcome.ORDERING_REJECTED)
                    return InventoryDeltaApplyResult(
                        resources=0,
                        links=0,
                        outcome=InventoryDeltaApplyOutcome.ORDERING_REJECTED,
                    )
                effective_links = await _reconcile_links(
                    connection,
                    snapshot_id=str(coverage["id"]),
                    resource_id=resource_id,
                    change_kind=change_kind,
                    links_complete=links_complete,
                    incoming=links,
                    max_reconciled_links=self._max_reconciled_links,
                )
                if reconcile_graph:
                    await _acquire_resource_locks(
                        connection, _lock_resource_ids(resource_id, effective_links)
                    )
                effective_link_kinds = tuple(
                    _choice(link, "change_kind", _CHANGE_KINDS) for link in effective_links
                )
                await _validate_upsert_link_endpoints(
                    connection,
                    snapshot_id=str(coverage["id"]),
                    links=effective_links,
                )
                incoming_props_by_key = {
                    _link_key(link): props_json
                    for link, props_json in zip(links, link_props_json, strict=True)
                }
                link_rows: list[tuple[Any, ...]] = []
                for link, link_kind in zip(effective_links, effective_link_kinds, strict=True):
                    link_type = _choice(link, "link_type", _LINK_TYPES)
                    link_props_json_value = incoming_props_by_key.get(_link_key(link))
                    if link_props_json_value is None:
                        link_props_json_value = _canonical_json_mapping(
                            link.get("props", {}), "inventory relationship props"
                        )
                    link_rows.append(
                        (
                            _required_str(link, "from_id"),
                            _required_str(link, "from_type"),
                            link_type,
                            _required_str(link, "to_id"),
                            _required_str(link, "to_type"),
                            link_kind,
                            link_props_json_value,
                            observed_at,
                            event_id,
                            idempotency_key,
                        )
                    )
                applied_links = await self._upsert_link_rows(connection, link_rows)
        return InventoryDeltaApplyResult(
            resources=max(0, resource_cursor.rowcount),
            links=applied_links,
            outcome=InventoryDeltaApplyOutcome.APPLIED,
        )

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )
        await connection.execute(
            "SELECT set_config('lock_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )

    async def _upsert_link_rows(
        self,
        connection: psycopg.AsyncConnection[Any],
        rows: Sequence[tuple[Any, ...]],
    ) -> int:
        if not rows:
            return 0
        cursor = connection.cursor()
        await cursor.executemany(_UPSERT_REALTIME_LINK, rows)
        return max(0, cursor.rowcount)


async def _acquire_inventory_locks(
    connection: psycopg.AsyncConnection[Any], resource_ids: Sequence[str]
) -> None:
    """Block promotion, then serialize graph changes that share an endpoint."""
    await _acquire_inventory_gate(connection, exclusive_graph=False)
    await _acquire_resource_locks(connection, resource_ids)


async def _acquire_inventory_gate(
    connection: psycopg.AsyncConnection[Any], *, exclusive_graph: bool
) -> None:
    await connection.execute("SELECT pg_advisory_xact_lock_shared(%s)", (_PROMOTION_LOCK,))
    graph_lock = (
        "SELECT pg_advisory_xact_lock(%s)"
        if exclusive_graph
        else "SELECT pg_advisory_xact_lock_shared(%s)"
    )
    await connection.execute(graph_lock, (_GRAPH_RECONCILIATION_LOCK,))


async def _acquire_resource_locks(
    connection: psycopg.AsyncConnection[Any], resource_ids: Sequence[str]
) -> None:
    ordered_ids = sorted(set(resource_ids))
    if ordered_ids:
        await connection.execute(_RESOURCE_LOCK_SQL, (_RESOURCE_LOCK_SEED, ordered_ids))


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


def _optional_bool(value: Mapping[str, Any], key: str, *, default: bool) -> bool:
    item = value.get(key, default)
    if not isinstance(item, bool):
        raise ValueError(f"inventory_change.{key} MUST be a boolean")
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


def _canonical_json_mapping(value: object, field: str) -> str:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} MUST be an object")
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} MUST be JSON-compatible") from exc


def _covered_resource_types(
    resource_type: str,
    links: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    types = {resource_type}
    for link in links:
        types.add(_required_str(link, "from_type"))
        types.add(_required_str(link, "to_type"))
    return tuple(sorted(types))


def _lock_resource_ids(
    resource_id: str,
    links: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    resource_ids = {resource_id}
    for link in links:
        resource_ids.add(_required_str(link, "from_id"))
        resource_ids.add(_required_str(link, "to_id"))
    return tuple(sorted(resource_ids))


def _link_key(link: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _required_str(link, "from_id"),
        _choice(link, "link_type", _LINK_TYPES),
        _required_str(link, "to_id"),
    )


def _reject_duplicate_link_keys(links: Sequence[Mapping[str, Any]]) -> None:
    seen: set[tuple[str, str, str]] = set()
    for link in links:
        key = _link_key(link)
        if key in seen:
            raise ValueError("inventory change contains a duplicate relationship key")
        seen.add(key)


def _link_owned_by(resource_id: str, link: Mapping[str, Any]) -> bool:
    if _choice(link, "link_type", _LINK_TYPES) == "contains":
        return _required_str(link, "to_id") == resource_id
    return _required_str(link, "from_id") == resource_id


def _declared_upsert_endpoint_types(
    links: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    declared: dict[str, str] = {}
    for link in links:
        if _choice(link, "change_kind", _CHANGE_KINDS) != "upsert":
            continue
        for id_key, type_key in (("from_id", "from_type"), ("to_id", "to_type")):
            resource_id = _required_str(link, id_key)
            resource_type = _required_str(link, type_key)
            previous = declared.setdefault(resource_id, resource_type)
            if previous != resource_type:
                raise ValueError("inventory relationship endpoint declares conflicting types")
    return declared


async def _validate_upsert_link_endpoints(
    connection: psycopg.AsyncConnection[Any],
    *,
    snapshot_id: str,
    links: Sequence[Mapping[str, Any]],
) -> None:
    declared = _declared_upsert_endpoint_types(links)
    if not declared:
        return
    cursor = await connection.execute(
        _EFFECTIVE_RESOURCE_TYPES_QUERY,
        (snapshot_id, list(declared)),
    )
    actual = {str(row["resource_id"]): str(row["resource_type"]) for row in await cursor.fetchall()}
    if declared.keys() - actual.keys():
        raise ValueError("inventory relationship endpoint is missing")
    if any(actual[resource_id] != resource_type for resource_id, resource_type in declared.items()):
        raise ValueError("inventory relationship endpoint type does not match resource type")


async def _validate_resource_type(
    connection: psycopg.AsyncConnection[Any],
    *,
    snapshot_id: str,
    resource_id: str,
    resource_type: str,
) -> None:
    cursor = await connection.execute(
        _EFFECTIVE_RESOURCE_TYPES_QUERY,
        (snapshot_id, [resource_id]),
    )
    row = await cursor.fetchone()
    if row is not None and str(row["resource_type"]) != resource_type:
        raise ValueError("inventory resource type does not match the effective resource type")


async def _reconcile_links(
    connection: psycopg.AsyncConnection[Any],
    *,
    snapshot_id: str,
    resource_id: str,
    change_kind: str,
    links_complete: bool,
    incoming: Sequence[Mapping[str, Any]],
    max_reconciled_links: int,
) -> tuple[Mapping[str, Any], ...]:
    if change_kind != "delete" and not links_complete:
        return tuple(incoming)
    predicate = (
        "(from_id=%s OR to_id=%s)"
        if change_kind == "delete"
        else "((link_type='contains' AND to_id=%s) OR (link_type<>'contains' AND from_id=%s))"
    )
    cursor = await connection.execute(
        _EFFECTIVE_LINKS_CTE
        + "SELECT from_id, from_type, link_type, to_id, to_type, props "
        + f"FROM effective_links WHERE {predicate} "
        + "ORDER BY from_id, link_type, to_id LIMIT %s",
        (snapshot_id, resource_id, resource_id, max_reconciled_links + 1),
    )
    current = await cursor.fetchall()
    if len(current) > max_reconciled_links:
        raise ValueError(
            f"inventory relationship reconciliation exceeds cap ({max_reconciled_links})"
        )
    merged = list(incoming)
    incoming_keys = {_link_key(link) for link in incoming}
    for row in current:
        if _link_key(row) in incoming_keys:
            continue
        merged.append({**row, "change_kind": "delete"})
    if len(merged) > max_reconciled_links:
        raise ValueError(
            f"inventory relationship reconciliation exceeds cap ({max_reconciled_links})"
        )
    return tuple(merged)


def _prefer_incoming_change(
    *,
    current_kind: str,
    current_event_id: str,
    incoming_kind: str,
    incoming_event_id: str,
) -> bool:
    """Mirror the equal-observation-time SQL ordering rule for tests and replay."""
    if current_kind != incoming_kind:
        return incoming_kind == "delete"
    return current_event_id < incoming_event_id


def _log_ignored_delta(event_id: str, outcome: InventoryDeltaApplyOutcome) -> None:
    _LOGGER.info(
        "inventory_delta_ignored",
        extra={"event_id": event_id, "reason": outcome.value},
    )


__all__ = [
    "InventoryDeltaApplyOutcome",
    "InventoryDeltaApplyResult",
    "PostgresInventoryDeltaProjector",
]
