"""Operator inventory graph projection built from the active authoritative snapshot.

The Console Architecture view reads the Operator projection stored under
``operator-projection:operations:inventory.graph``. Only the local development
topology materializes it. Local preparation writes it after a full authoritative
refresh. When preparation defers that refresh to the inventory reconciliation loop,
the local loop keeps the projection aligned with each promoted snapshot because the
local launcher sets ``FDAI_INVENTORY_OPERATOR_GRAPH_PROJECTION=1``. Deployed venues
never set the flag, so their Architecture view still reports the graph as not wired.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.inventory_snapshot import InventoryObservationKind

OPERATOR_INVENTORY_GRAPH_KEY = "operator-projection:operations:inventory.graph"
OPERATOR_GRAPH_PROJECTION_ENV = "FDAI_INVENTORY_OPERATOR_GRAPH_PROJECTION"
_MAX_RESOURCES = 1000
_MAX_LINKS = 8000
_GRAPH_LINK_TYPES = ["contains", "attached_to", "depends_on", "peered_with"]
_LOGGER = logging.getLogger(__name__)


async def read_operator_inventory_graph(
    dsn: str, *, now: datetime | None = None
) -> dict[str, object] | None:
    """Build the bounded Console graph from the active snapshot, or None without one."""

    normalized_dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    async with await psycopg.AsyncConnection.connect(
        normalized_dsn,
        row_factory=dict_row,
        connect_timeout=10,
    ) as connection:
        await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
        await connection.set_read_only(True)
        snapshot_cursor = await connection.execute(
            "SELECT s.id, s.completed_at, s.source, s.observation_kind FROM inventory_active a "
            "JOIN inventory_snapshot s ON s.id=a.snapshot_id WHERE a.singleton=TRUE"
        )
        snapshot = await snapshot_cursor.fetchone()
        if snapshot is None:
            return None
        failure_cursor = await connection.execute(
            "SELECT 1 FROM inventory_snapshot WHERE id<>%s AND started_at>%s AND "
            "(status='failed' OR (status='collecting' AND "
            "started_at < NOW() - INTERVAL '30 minutes')) LIMIT 1",
            (snapshot["id"], snapshot["completed_at"]),
        )
        newer_failure = await failure_cursor.fetchone()
        overlay_cursor = await connection.execute(
            "SELECT COUNT(*) AS pending_changes FROM inventory_realtime_resource"
        )
        overlay = await overlay_cursor.fetchone()
        if overlay is None:
            raise RuntimeError("inventory realtime overlay count is unavailable")
        resource_cursor = await connection.execute(
            "SELECT resource_id, resource_type, props FROM inventory_snapshot_resource "
            "WHERE snapshot_id=%s ORDER BY resource_id LIMIT 1001",
            (snapshot["id"],),
        )
        resource_rows = list(await resource_cursor.fetchall())
        link_cursor = await connection.execute(
            "SELECT from_id, link_type, to_id FROM inventory_snapshot_link "
            "WHERE snapshot_id=%s AND link_type=ANY(%s::text[]) "
            "ORDER BY from_id, link_type, to_id LIMIT 8001",
            (snapshot["id"], _GRAPH_LINK_TYPES),
        )
        link_rows = list(await link_cursor.fetchall())

    return operator_inventory_payload(
        snapshot_id=str(snapshot["id"]),
        snapshot_at=snapshot["completed_at"],
        source=snapshot["source"],
        observation_kind=InventoryObservationKind(snapshot["observation_kind"]),
        freshness_budget_seconds=PostgresInventorySnapshotStoreConfig(
            dsn=dsn
        ).freshness_budget_seconds,
        pending_changes=int(overlay["pending_changes"]),
        newer_failure=newer_failure is not None,
        resource_rows=resource_rows,
        link_rows=link_rows,
        now=now,
    )


async def write_operator_inventory_graph(*, dsn: str, state_store: PostgresStateStore) -> None:
    """Materialize the graph of the promoted snapshot; a missing snapshot is an error."""

    payload = await read_operator_inventory_graph(dsn)
    if payload is None:
        raise RuntimeError("active inventory snapshot is unavailable")
    await state_store.write_state(OPERATOR_INVENTORY_GRAPH_KEY, payload)


async def reconcile_operator_inventory_graph(*, dsn: str, state_store: PostgresStateStore) -> bool:
    """Rewrite the stored graph when its snapshot or freshness no longer matches.

    Return whether the projection was written. Without an active snapshot the stored
    projection stays as it is, so the Operator keeps reporting the graph unavailable
    instead of showing an empty inventory.
    """

    payload = await read_operator_inventory_graph(dsn)
    if payload is None:
        return False
    stored = await state_store.read_state(OPERATOR_INVENTORY_GRAPH_KEY)
    if stored is not None and _graph_identity(stored) == _graph_identity(payload):
        return False
    await state_store.write_state(OPERATOR_INVENTORY_GRAPH_KEY, payload)
    return True


async def reconcile_local_operator_graph(dsn: str, environ: Mapping[str, str] = os.environ) -> None:
    """Keep the local Console graph aligned after one reconciliation tick, when enabled.

    A failed read or write never fails the reconciliation loop; the stored projection
    stays unchanged and the next tick retries.
    """

    if environ.get(OPERATOR_GRAPH_PROJECTION_ENV, "").strip() != "1":
        return
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    try:
        written = await reconcile_operator_inventory_graph(dsn=dsn, state_store=store)
    except (psycopg.Error, OSError, RuntimeError, ValueError) as exc:
        _LOGGER.warning(
            "inventory_operator_graph_projection_failed", extra={"error": type(exc).__name__}
        )
        return
    if written:
        _LOGGER.info("inventory_operator_graph_projection_written")


def _graph_identity(payload: Mapping[str, Any]) -> tuple[object, ...]:
    realtime = payload.get("realtime")
    pending = realtime.get("pending_changes") if isinstance(realtime, Mapping) else None
    return (
        payload.get("snapshot_id"),
        payload.get("freshness"),
        pending,
        payload.get("coverage_gaps"),
        payload.get("truncated"),
    )


def operator_inventory_payload(
    *,
    snapshot_id: str,
    snapshot_at: datetime,
    source: str,
    observation_kind: InventoryObservationKind,
    freshness_budget_seconds: int,
    resource_rows: list[dict[str, object]],
    link_rows: list[dict[str, object]],
    now: datetime | None = None,
    pending_changes: int = 0,
    newer_failure: bool = False,
) -> dict[str, object]:
    """Build the bounded Console graph from one promoted authoritative snapshot."""
    if (
        not snapshot_id.strip()
        or not source.strip()
        or freshness_budget_seconds < 1
        or pending_changes < 0
    ):
        raise ValueError(
            "inventory projection requires snapshot identity, source, and freshness budget"
        )
    age_seconds = max(0, int(((now or datetime.now(UTC)) - snapshot_at).total_seconds()))
    freshness = (
        "fresh"
        if observation_kind is InventoryObservationKind.OBSERVED
        and age_seconds <= freshness_budget_seconds
        and not newer_failure
        else "stale"
    )
    if pending_changes:
        freshness = "unknown"
    truncated = len(resource_rows) > _MAX_RESOURCES or len(link_rows) > _MAX_LINKS
    resource_rows = resource_rows[:_MAX_RESOURCES]
    link_rows = link_rows[:_MAX_LINKS]
    resource_ids = {str(row["resource_id"]) for row in resource_rows}
    parents = {
        str(row["to_id"]): str(row["from_id"])
        for row in link_rows
        if row["link_type"] == "contains"
        and str(row["from_id"]) in resource_ids
        and str(row["to_id"]) in resource_ids
    }
    resources: list[dict[str, object]] = []
    for row in resource_rows:
        resource_id = str(row["resource_id"])
        raw_props = row["props"]
        props = raw_props if isinstance(raw_props, dict) else json.loads(str(raw_props))
        name = props.get("name")
        status = props.get("status")
        resources.append(
            {
                "id": resource_id,
                "type": str(row["resource_type"]),
                "name": name if isinstance(name, str) and name else resource_id.rsplit("/", 1)[-1],
                "status": status if isinstance(status, str) and status else "unknown",
                **({"parent_id": parents[resource_id]} if resource_id in parents else {}),
            }
        )
    links = [
        {
            "source": str(row["from_id"]),
            "target": str(row["to_id"]),
            "type": str(row["link_type"]),
        }
        for row in link_rows
        if str(row["from_id"]) in resource_ids and str(row["to_id"]) in resource_ids
    ]
    return {
        "snapshot_id": snapshot_id,
        "observation_kind": observation_kind.value,
        "snapshot_at": snapshot_at.astimezone(UTC).isoformat(),
        "freshness": freshness,
        "source": source,
        "scope": None,
        "root": None,
        "depth": 8,
        "limit": _MAX_RESOURCES,
        "included_link_types": [*_GRAPH_LINK_TYPES, "runtime_calls"],
        "resources": resources,
        "links": links,
        "truncated": truncated,
        "truncation_reasons": ["resource_or_link_cap"] if truncated else [],
        "coverage_gaps": ["newer_inventory_failure"] if newer_failure else [],
        "cursor": snapshot_id,
        "cache": {
            "status": "fresh" if freshness == "fresh" else "stale",
            "age_seconds": age_seconds,
            "persistent": True,
        },
        "realtime": {"pending_changes": pending_changes, "latest_at": None},
        "views": [],
    }


__all__ = [
    "OPERATOR_GRAPH_PROJECTION_ENV",
    "OPERATOR_INVENTORY_GRAPH_KEY",
    "operator_inventory_payload",
    "read_operator_inventory_graph",
    "reconcile_local_operator_graph",
    "reconcile_operator_inventory_graph",
    "write_operator_inventory_graph",
]
