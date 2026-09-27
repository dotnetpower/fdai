"""Read-only, generation-bound Inventory projection for the Assurance Twin."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.core.assurance_twin.projection import InMemoryProjection, build_baseline_projection
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_inventory_snapshot_providers import _PROMOTION_LOCK
from fdai.shared.providers.projection import InventoryDiff, ResourceRef


class TwinInventoryUnavailableError(ValueError):
    """The retained Inventory cannot support a trustworthy Twin projection."""


@dataclass(frozen=True, slots=True)
class TwinInventoryRevision:
    projection: InMemoryProjection
    snapshot_id: str
    source_revision: str
    completed_at: datetime
    source: str
    resource_count: int
    delta_count: int


class PostgresTwinInventorySource:
    """Build a fresh resource projection from one retained, observed Inventory generation.

    A repeatable-read transaction fences snapshot promotion and reads the bounded
    realtime overlay at the same database revision. No projection is cached across
    calls. This read does not publish a posture finding or confer action authority.
    """

    def __init__(
        self,
        *,
        config: PostgresInventorySnapshotStoreConfig,
        max_resources: int = 5_000,
        max_deltas: int = 1_000,
    ) -> None:
        if not 1 <= max_resources <= 10_000 or not 1 <= max_deltas <= 10_000:
            raise ValueError("Twin Inventory limits MUST be between 1 and 10000")
        self._config = config
        self._max_resources = max_resources
        self._max_deltas = max_deltas

    async def load(
        self,
        *,
        now: datetime,
        freshness_ttl: timedelta,
        required_scopes: tuple[str, ...],
    ) -> TwinInventoryRevision:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Twin Inventory cutoff MUST be timezone-aware")
        if freshness_ttl <= timedelta(0):
            raise ValueError("Twin Inventory freshness TTL MUST be positive")
        if not required_scopes or required_scopes != tuple(sorted(set(required_scopes))):
            raise ValueError("Twin Inventory scopes MUST be non-empty, unique, and ordered")

        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._config.statement_timeout_ms),),
                )
                await connection.execute(
                    "SELECT pg_advisory_xact_lock_shared(%s)", (_PROMOTION_LOCK,)
                )
                cursor = await connection.execute(
                    "SELECT s.id, s.source, s.status, s.observation_kind, s.scopes, "
                    "s.metadata, s.started_at, s.completed_at, "
                    "EXISTS (SELECT 1 FROM inventory_snapshot newer "
                    "WHERE newer.id<>s.id AND newer.started_at>s.completed_at AND "
                    "(newer.status='failed' OR (newer.status='collecting' AND "
                    "newer.started_at < NOW() - INTERVAL '30 minutes'))) AS newer_failure "
                    "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                    "WHERE a.singleton=TRUE"
                )
                snapshot = _require_snapshot(
                    await cursor.fetchone(), now, freshness_ttl, required_scopes
                )
                snapshot_id = str(snapshot["id"])
                cursor = await connection.execute(
                    "SELECT resource_id, resource_type, props FROM inventory_snapshot_resource "
                    "WHERE snapshot_id=%s ORDER BY resource_id LIMIT %s",
                    (snapshot_id, self._max_resources + 1),
                )
                resources = await cursor.fetchall()
                if len(resources) > self._max_resources:
                    raise TwinInventoryUnavailableError("Twin Inventory baseline exceeds its bound")
                cursor = await connection.execute(
                    "SELECT resource_id, resource_type, props, change_kind, observed_at "
                    "FROM inventory_realtime_resource ORDER BY resource_id LIMIT %s",
                    (self._max_deltas + 1,),
                )
                deltas = await cursor.fetchall()
                if len(deltas) > self._max_deltas:
                    raise TwinInventoryUnavailableError("Twin Inventory delta exceeds its bound")
                cursor = await connection.execute(
                    "SELECT EXISTS (SELECT 1 FROM inventory_realtime_link) AS pending_links"
                )
                link_state = await cursor.fetchone()
                if link_state is None or link_state["pending_links"]:
                    raise TwinInventoryUnavailableError(
                        "Twin Inventory has unprojected link changes"
                    )
            # A promotion might have committed while the first repeatable-read
            # snapshot waited for its shared lock. Recheck in a new transaction.
            cursor = await connection.execute(
                "SELECT snapshot_id FROM inventory_active WHERE singleton=TRUE"
            )
            active = await cursor.fetchone()
            if active is None or str(active["snapshot_id"]) != snapshot_id:
                raise TwinInventoryUnavailableError("Twin Inventory generation changed during read")

        try:
            baseline = [
                (
                    ResourceRef(str(row["resource_type"]), str(row["resource_id"])),
                    _props(row["props"]),
                )
                for row in sorted(resources, key=lambda item: str(item["resource_id"]))
            ]
            projection = build_baseline_projection(baseline)
            by_id = {ref.ref: ref for ref in projection.resources}
            for row in deltas:
                resource_id = str(row["resource_id"])
                observed_at = row["observed_at"]
                if (
                    not isinstance(observed_at, datetime)
                    or observed_at.tzinfo is None
                    or not snapshot["started_at"] < observed_at <= now
                ):
                    raise TwinInventoryUnavailableError(
                        "Twin Inventory delta is outside its window"
                    )
                current = by_id.get(resource_id)
                kind = row["change_kind"]
                if kind == "delete":
                    if current is not None:
                        projection = projection.apply_diff(
                            InventoryDiff(kind="delete", target=current)
                        )
                        del by_id[resource_id]
                elif kind == "upsert":
                    target = ResourceRef(str(row["resource_type"]), resource_id)
                    if current is not None and current != target:
                        raise TwinInventoryUnavailableError("Twin Inventory resource type changed")
                    if current is not None:
                        projection = projection.apply_diff(
                            InventoryDiff(kind="delete", target=current)
                        )
                    projection = projection.apply_diff(
                        InventoryDiff(
                            kind="create", target=target, properties=dict(_props(row["props"]))
                        )
                    )
                    by_id[resource_id] = target
                else:
                    raise TwinInventoryUnavailableError("Twin Inventory delta has an unknown kind")
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, TwinInventoryUnavailableError):
                raise
            raise TwinInventoryUnavailableError(
                "Twin Inventory resource data is malformed"
            ) from exc
        if len(projection.resources) > self._max_resources:
            raise TwinInventoryUnavailableError(
                "Twin Inventory projected resources exceed their bound"
            )
        try:
            revision_body = {
                "version": 1,
                "snapshot": {
                    "id": snapshot_id,
                    "source": snapshot["source"],
                    "started_at": _utc_time(snapshot["started_at"]),
                    "completed_at": _utc_time(snapshot["completed_at"]),
                    "scopes": required_scopes,
                    "coverage_scope": "full_provider_scope",
                },
                "resources": [
                    [row["resource_id"], row["resource_type"], _props(row["props"])]
                    for row in resources
                ],
                "realtime_resources": [
                    [
                        row["resource_id"],
                        row["resource_type"],
                        row["change_kind"],
                        _utc_time(row["observed_at"]),
                        _props(row["props"]),
                    ]
                    for row in sorted(deltas, key=lambda item: str(item["resource_id"]))
                ],
            }
            canonical = json.dumps(
                revision_body,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TwinInventoryUnavailableError(
                "Twin Inventory revision material is malformed"
            ) from exc
        return TwinInventoryRevision(
            projection=projection,
            snapshot_id=snapshot_id,
            source_revision=f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}",
            completed_at=snapshot["completed_at"],
            source=str(snapshot["source"]),
            resource_count=len(projection.resources),
            delta_count=len(deltas),
        )

    async def load_at_revision(
        self,
        *,
        expected_revision: str,
        now: datetime,
        freshness_ttl: timedelta,
        required_scopes: tuple[str, ...],
    ) -> TwinInventoryRevision:
        """Re-read retained content; never substitute a later overlay for a request."""

        result = await self.load(
            now=now, freshness_ttl=freshness_ttl, required_scopes=required_scopes
        )
        if result.source_revision != expected_revision:
            raise TwinInventoryUnavailableError("Twin Inventory revision changed")
        return result


def _utc_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _props(raw: object) -> Mapping[str, Any]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise TwinInventoryUnavailableError("Twin Inventory properties are malformed") from exc
    if not isinstance(value, Mapping):
        raise TwinInventoryUnavailableError("Twin Inventory resource properties are malformed")
    return dict(value)


def _require_snapshot(
    snapshot: Mapping[str, Any] | None,
    now: datetime,
    freshness_ttl: timedelta,
    required_scopes: tuple[str, ...],
) -> Mapping[str, Any]:
    if snapshot is None or snapshot["status"] != "active":
        raise TwinInventoryUnavailableError("Twin Inventory has no active generation")
    if snapshot["observation_kind"] != "observed" or snapshot["newer_failure"]:
        raise TwinInventoryUnavailableError("Twin Inventory observation is unavailable")
    completed_at = snapshot["completed_at"]
    if (
        not isinstance(completed_at, datetime)
        or completed_at.tzinfo is None
        or not timedelta(0) <= now - completed_at <= freshness_ttl
    ):
        raise TwinInventoryUnavailableError("Twin Inventory generation is stale")
    try:
        scopes = (
            json.loads(snapshot["scopes"])
            if isinstance(snapshot["scopes"], str)
            else snapshot["scopes"]
        )
        metadata = (
            json.loads(snapshot["metadata"])
            if isinstance(snapshot["metadata"], str)
            else snapshot["metadata"]
        )
    except json.JSONDecodeError as exc:
        raise TwinInventoryUnavailableError("Twin Inventory coverage is malformed") from exc
    if (
        not isinstance(scopes, list)
        or not all(isinstance(scope, str) for scope in scopes)
        or len(scopes) != len(required_scopes)
        or set(scopes) != set(required_scopes)
        or not isinstance(metadata, Mapping)
        or metadata.get("coverage_scope") != "full_provider_scope"
        or not isinstance(snapshot["started_at"], datetime)
        or snapshot["started_at"].tzinfo is None
    ):
        raise TwinInventoryUnavailableError("Twin Inventory coverage is incomplete")
    return snapshot
