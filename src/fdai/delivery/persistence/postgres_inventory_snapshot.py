"""PostgreSQL immutable inventory candidates and active graph projection."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from fdai.shared.providers.inventory import InventoryBatch
from fdai.shared.providers.inventory_snapshot import (
    InventoryAttemptFailure,
    InventoryCoverageManifest,
    InventoryObservationKind,
)

_PROMOTION_LOCK: Final[int] = 732_410_991
_MAX_GRAPH_ROWS: Final[int] = 5000
_SCOPED_RESOURCES_QUERY = (
    "WITH RECURSIVE effective_resources AS ("
    "SELECT r.resource_id, r.resource_type, r.props, r.provider_ref, r.last_seen "
    "FROM inventory_snapshot_resource r WHERE r.snapshot_id=%s AND NOT EXISTS ("
    "SELECT 1 FROM inventory_realtime_resource d WHERE d.resource_id=r.resource_id) "
    "UNION ALL SELECT d.resource_id, d.resource_type, d.props, d.provider_ref, d.observed_at "
    "FROM inventory_realtime_resource d WHERE d.change_kind='upsert'), "
    "effective_links AS ("
    "SELECT l.from_id, l.from_type, l.link_type, l.to_id, l.to_type, l.props "
    "FROM inventory_snapshot_link l WHERE l.snapshot_id=%s AND NOT EXISTS ("
    "SELECT 1 FROM inventory_realtime_link d WHERE d.from_id=l.from_id "
    "AND d.link_type=l.link_type AND d.to_id=l.to_id) "
    "UNION ALL SELECT d.from_id, d.from_type, d.link_type, d.to_id, d.to_type, d.props "
    "FROM inventory_realtime_link d WHERE d.change_kind='upsert'), "
    "walk(resource_id, level) AS ("
    "SELECT resource_id, 0 FROM effective_resources "
    "WHERE resource_id=%s OR resource_id LIKE %s "
    "UNION SELECT CASE WHEN l.from_id=w.resource_id THEN l.to_id ELSE l.from_id END, "
    "w.level+1 FROM walk w JOIN effective_links l ON "
    "(l.from_id=w.resource_id OR l.to_id=w.resource_id) "
    "AND l.link_type=ANY(%s::text[]) WHERE w.level < %s) "
    "SELECT DISTINCT r.resource_id, r.resource_type, r.props "
    "FROM effective_resources r JOIN walk w ON w.resource_id=r.resource_id "
    "ORDER BY r.resource_id LIMIT %s"
)
_ALL_RESOURCES_QUERY = (
    "WITH effective_resources AS ("
    "SELECT r.resource_id, r.resource_type, r.props, r.provider_ref, r.last_seen "
    "FROM inventory_snapshot_resource r WHERE r.snapshot_id=%s AND NOT EXISTS ("
    "SELECT 1 FROM inventory_realtime_resource d WHERE d.resource_id=r.resource_id) "
    "UNION ALL SELECT d.resource_id, d.resource_type, d.props, d.provider_ref, d.observed_at "
    "FROM inventory_realtime_resource d WHERE d.change_kind='upsert') "
    "SELECT resource_id, resource_type, props FROM effective_resources "
    "ORDER BY resource_id LIMIT %s"
)
_SELECT_EFFECTIVE_LINKS_QUERY = (
    "WITH effective_links AS ("
    "SELECT l.from_id, l.from_type, l.link_type, l.to_id, l.to_type, l.props "
    "FROM inventory_snapshot_link l WHERE l.snapshot_id=%s AND NOT EXISTS ("
    "SELECT 1 FROM inventory_realtime_link d WHERE d.from_id=l.from_id "
    "AND d.link_type=l.link_type AND d.to_id=l.to_id) "
    "UNION ALL SELECT d.from_id, d.from_type, d.link_type, d.to_id, d.to_type, d.props "
    "FROM inventory_realtime_link d WHERE d.change_kind='upsert') "
    "SELECT from_id, to_id, link_type FROM effective_links "
    "WHERE from_id=ANY(%s::text[]) AND to_id=ANY(%s::text[]) "
    "AND link_type=ANY(%s::text[]) ORDER BY from_id, link_type, to_id"
)


@dataclass(frozen=True, slots=True)
class PostgresInventorySnapshotStoreConfig:
    """Connection and freshness settings for inventory snapshots."""

    dsn: str
    freshness_budget_seconds: int = 86_400
    statement_timeout_ms: int = 30_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("dsn MUST NOT be empty")
        if self.freshness_budget_seconds < 1:
            raise ValueError("freshness_budget_seconds MUST be >= 1")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("database timeouts MUST be >= 1")


class PostgresInventorySnapshotStore:
    """Stage candidate rows and atomically swap the active snapshot pointer."""

    def __init__(self, *, config: PostgresInventorySnapshotStoreConfig) -> None:
        self._config = config

    async def begin(self, manifest: InventoryCoverageManifest) -> str:
        attempt_id = str(uuid4())
        started = manifest.started_at or datetime.now(tz=UTC)
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute(
                    "UPDATE inventory_snapshot SET status='failed', completed_at=NOW(), "
                    "failure_code='source_unavailable', failure_message='attempt lease expired' "
                    "WHERE status='collecting' AND started_at < NOW() - INTERVAL '30 minutes'"
                )
                await connection.execute(
                    "INSERT INTO inventory_snapshot "
                    "(id, status, source, observation_kind, scopes, resource_types, "
                    "metadata, started_at) "
                    "VALUES (%s, 'collecting', %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)",
                    (
                        attempt_id,
                        manifest.source,
                        manifest.observation_kind.value,
                        json.dumps(manifest.scopes),
                        json.dumps(manifest.resource_types),
                        json.dumps(dict(manifest.metadata), default=str),
                        started,
                    ),
                )
        return attempt_id

    async def stage(self, attempt_id: str, batch: InventoryBatch) -> None:
        if batch.final:
            raise ValueError("terminal inventory fences are not staged")
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await self._require_collecting(connection, attempt_id)
                if batch.resources:
                    cursor = connection.cursor()
                    await cursor.executemany(
                        "INSERT INTO inventory_snapshot_resource "
                        "(snapshot_id, resource_id, resource_type, props, provider_ref, last_seen) "
                        "VALUES (%s, %s, %s, %s::jsonb, %s, %s) "
                        "ON CONFLICT (snapshot_id, resource_id) DO UPDATE SET "
                        "resource_type = CASE WHEN inventory_snapshot_resource.resource_type = "
                        "EXCLUDED.resource_type THEN EXCLUDED.resource_type ELSE NULL END, "
                        "props = EXCLUDED.props, provider_ref = EXCLUDED.provider_ref, "
                        "last_seen = EXCLUDED.last_seen",
                        [
                            (
                                attempt_id,
                                item.resource_id,
                                item.type,
                                json.dumps(dict(item.props), default=str),
                                item.provider_ref,
                                item.last_seen,
                            )
                            for item in batch.resources
                        ],
                    )
                if batch.links:
                    cursor = connection.cursor()
                    await cursor.executemany(
                        "INSERT INTO inventory_snapshot_link "
                        "(snapshot_id, from_id, from_type, link_type, to_id, to_type, props) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb) "
                        "ON CONFLICT (snapshot_id, from_id, link_type, to_id) DO UPDATE SET "
                        "from_type = EXCLUDED.from_type, to_type = EXCLUDED.to_type, "
                        "props = EXCLUDED.props",
                        [
                            (
                                attempt_id,
                                item.from_id,
                                item.from_type,
                                item.link_type,
                                item.to_id,
                                item.to_type,
                                json.dumps(dict(item.link_props), default=str),
                            )
                            for item in batch.links
                        ],
                    )

    async def promote(self, attempt_id: str, manifest: InventoryCoverageManifest) -> None:
        completed = manifest.completed_at or datetime.now(tz=UTC)
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute("SELECT pg_advisory_xact_lock(%s)", (_PROMOTION_LOCK,))
                await self._require_collecting(connection, attempt_id)
                active_cursor = await connection.execute(
                    "SELECT s.started_at, s.observation_kind, s.metadata "
                    "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                    "WHERE a.singleton=TRUE FOR UPDATE"
                )
                active = await active_cursor.fetchone()
                candidate_started = manifest.started_at or completed
                if active is not None:
                    if candidate_started < active["started_at"]:
                        raise ValueError("inventory candidate is older than the active snapshot")
                    if (
                        active["observation_kind"] == InventoryObservationKind.OBSERVED.value
                        and manifest.observation_kind is InventoryObservationKind.EXPECTED
                    ):
                        raise ValueError("expected inventory cannot replace observed inventory")
                    active_priority = _source_priority(active["metadata"])
                    candidate_priority = _source_priority(manifest.metadata)
                    if (
                        candidate_started == active["started_at"]
                        and candidate_priority > active_priority
                    ):
                        raise ValueError("lower-priority inventory cannot replace active inventory")
                dangling = await connection.execute(
                    "SELECT 1 FROM inventory_snapshot_link l "
                    "LEFT JOIN inventory_snapshot_resource f ON f.snapshot_id=l.snapshot_id "
                    "AND f.resource_id=l.from_id "
                    "LEFT JOIN inventory_snapshot_resource t ON t.snapshot_id=l.snapshot_id "
                    "AND t.resource_id=l.to_id "
                    "WHERE l.snapshot_id=%s AND (f.resource_id IS NULL OR t.resource_id IS NULL) "
                    "LIMIT 1",
                    (attempt_id,),
                )
                if await dangling.fetchone() is not None:
                    raise ValueError("inventory candidate contains a link with a missing endpoint")
                await connection.execute(
                    "UPDATE inventory_snapshot SET status='superseded' "
                    "WHERE status='active' AND id<>%s",
                    (attempt_id,),
                )
                await connection.execute(
                    "UPDATE inventory_snapshot SET status='active', completed_at=%s, "
                    "promoted_at=NOW(), "
                    "scopes=%s::jsonb, resource_types=%s::jsonb, metadata=%s::jsonb WHERE id=%s",
                    (
                        completed,
                        json.dumps(manifest.scopes),
                        json.dumps(manifest.resource_types),
                        json.dumps(dict(manifest.metadata), default=str),
                        attempt_id,
                    ),
                )
                await connection.execute(
                    "INSERT INTO inventory_active (singleton, snapshot_id, updated_at) "
                    "VALUES (TRUE, %s, NOW()) ON CONFLICT (singleton) DO UPDATE SET "
                    "snapshot_id=EXCLUDED.snapshot_id, updated_at=EXCLUDED.updated_at",
                    (attempt_id,),
                )
                await connection.execute(
                    "DELETE FROM inventory_realtime_link WHERE observed_at <= %s",
                    (candidate_started,),
                )
                await connection.execute(
                    "DELETE FROM inventory_realtime_resource WHERE observed_at <= %s",
                    (candidate_started,),
                )

    async def fail(self, attempt_id: str, failure: InventoryAttemptFailure) -> None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            await connection.execute(
                "UPDATE inventory_snapshot SET status='failed', completed_at=NOW(), "
                "failure_code=%s, failure_message=%s WHERE id=%s AND status='collecting'",
                (failure.code.value, failure.message, attempt_id),
            )

    async def _require_collecting(
        self, connection: psycopg.AsyncConnection[Any], attempt_id: str
    ) -> None:
        cursor = await connection.execute(
            "SELECT status FROM inventory_snapshot WHERE id=%s FOR UPDATE", (attempt_id,)
        )
        row = await cursor.fetchone()
        if row is None or row["status"] != "collecting":
            raise ValueError("inventory attempt is missing or no longer collecting")

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
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


class PostgresInventoryGraphProvider:
    """Serve the active immutable inventory generation to the read API."""

    def __init__(self, *, config: PostgresInventorySnapshotStoreConfig) -> None:
        self._config = config

    async def __call__(
        self, scope: str | None, depth: int, link_types: tuple[str, ...]
    ) -> Mapping[str, Any]:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            await connection.execute("SELECT pg_advisory_xact_lock_shared(%s)", (_PROMOTION_LOCK,))
            active = await connection.execute(
                "SELECT s.id, s.source, s.observation_kind, s.scopes, s.resource_types, "
                "s.completed_at, s.metadata FROM inventory_active a JOIN inventory_snapshot s "
                "ON s.id=a.snapshot_id WHERE a.singleton=TRUE"
            )
            snapshot = await active.fetchone()
            if snapshot is None:
                return _unavailable_graph()
            failure_cursor = await connection.execute(
                "SELECT status, failure_code, started_at FROM inventory_snapshot "
                "WHERE id<>%s AND started_at>%s AND "
                "(status='failed' OR (status='collecting' AND "
                "started_at < NOW() - INTERVAL '30 minutes')) "
                "ORDER BY started_at DESC LIMIT 1",
                (snapshot["id"], snapshot["completed_at"]),
            )
            newer_failure = await failure_cursor.fetchone()
            overlay_cursor = await connection.execute(
                "SELECT COUNT(*) AS pending_changes, MAX(observed_at) AS latest_at "
                "FROM inventory_realtime_resource"
            )
            overlay = await overlay_cursor.fetchone()
            if scope:
                resources_cursor = await connection.execute(
                    _SCOPED_RESOURCES_QUERY,
                    (
                        snapshot["id"],
                        snapshot["id"],
                        scope,
                        f"{scope}/%",
                        list(link_types),
                        depth,
                        _MAX_GRAPH_ROWS + 1,
                    ),
                )
            else:
                resources_cursor = await connection.execute(
                    _ALL_RESOURCES_QUERY,
                    (snapshot["id"], _MAX_GRAPH_ROWS + 1),
                )
            rows = await resources_cursor.fetchall()
            truncated = len(rows) > _MAX_GRAPH_ROWS
            rows = rows[:_MAX_GRAPH_ROWS]
            ids = [str(row["resource_id"]) for row in rows]
            links: Sequence[Mapping[str, Any]] = ()
            if ids:
                links_cursor = await connection.execute(
                    _SELECT_EFFECTIVE_LINKS_QUERY,
                    (snapshot["id"], ids, ids, list(link_types)),
                )
                links = await links_cursor.fetchall()
        completed = snapshot["completed_at"]
        now = datetime.now(tz=UTC)
        age = max(0, int((now - completed).total_seconds()))
        expected = snapshot["observation_kind"] == InventoryObservationKind.EXPECTED.value
        freshness = "stale" if age > self._config.freshness_budget_seconds else "fresh"
        if expected:
            freshness = "stale"
        if newer_failure is not None:
            freshness = "stale"
        coverage_gaps: list[str] = []
        metadata = snapshot["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        covered_links = (
            set(metadata.get("link_types", ())) if isinstance(metadata, Mapping) else set()
        )
        missing_links = sorted({"contains", "attached_to", "depends_on"} - covered_links)
        coverage_gaps.extend(f"link_type:{link_type}" for link_type in missing_links)
        if newer_failure is not None:
            coverage_gaps.append(str(newer_failure.get("failure_code") or "source_unavailable"))
        degraded = freshness != "fresh" or bool(coverage_gaps)
        overlay_latest = overlay["latest_at"] if overlay is not None else None
        pending_changes = int(overlay["pending_changes"] or 0) if overlay is not None else 0
        return {
            "snapshot_id": snapshot["id"],
            "snapshot_at": completed.isoformat(),
            "freshness": freshness,
            "source": snapshot["source"],
            "observation_kind": snapshot["observation_kind"],
            "age_seconds": age,
            "coverage": {
                "scopes": snapshot["scopes"],
                "resource_types": snapshot["resource_types"],
            },
            "coverage_gaps": coverage_gaps,
            "degraded": degraded,
            "realtime": {
                "pending_changes": pending_changes,
                "latest_at": overlay_latest.isoformat() if overlay_latest is not None else None,
            },
            "resources": [_resource_payload(row) for row in rows],
            "links": [
                {"source": row["from_id"], "target": row["to_id"], "type": row["link_type"]}
                for row in links
            ],
            "views": [],
            "truncated": truncated,
            "cursor": (
                f"{snapshot['id']}:{overlay_latest.isoformat()}"
                if overlay_latest is not None
                else snapshot["id"]
            ),
        }

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
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


class PostgresInventoryAgeProvider:
    """Return the active snapshot age for RiskGate freshness checks."""

    def __init__(self, *, config: PostgresInventorySnapshotStoreConfig) -> None:
        self._config = config

    async def __call__(self, resource_ref: str) -> int | None:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            await connection.execute("SELECT pg_advisory_xact_lock_shared(%s)", (_PROMOTION_LOCK,))
            cursor = await connection.execute(
                "SELECT EXTRACT(EPOCH FROM (NOW() - s.completed_at)) AS age_seconds, "
                "s.observation_kind, s.metadata, "
                "EXISTS (SELECT 1 FROM inventory_realtime_resource d "
                "WHERE d.resource_id=%s AND d.change_kind='upsert') OR ("
                "EXISTS (SELECT 1 FROM inventory_snapshot_resource r "
                "WHERE r.snapshot_id=s.id AND r.resource_id=%s) AND NOT EXISTS ("
                "SELECT 1 FROM inventory_realtime_resource d WHERE d.resource_id=%s)) "
                "AS resource_present, EXISTS (SELECT 1 FROM inventory_snapshot newer "
                "WHERE newer.id<>s.id AND newer.started_at>s.completed_at AND ("
                "newer.status='failed' OR (newer.status='collecting' AND "
                "newer.started_at < NOW() - INTERVAL '30 minutes'))) AS newer_failure "
                "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                "WHERE a.singleton=TRUE AND s.status='active'",
                (resource_ref, resource_ref, resource_ref),
            )
            row = await cursor.fetchone()
        if row is None or row["age_seconds"] is None:
            return None
        if not row["resource_present"] or row["newer_failure"]:
            return None
        if row["observation_kind"] != InventoryObservationKind.OBSERVED.value:
            return None
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        covered_links = (
            set(metadata.get("link_types", ())) if isinstance(metadata, Mapping) else set()
        )
        if not {"contains", "attached_to", "depends_on"}.issubset(covered_links):
            return None
        return max(0, int(row["age_seconds"]))


class PostgresInventoryContextProvider:
    """Return trusted properties for one resource in the active snapshot."""

    def __init__(self, *, config: PostgresInventorySnapshotStoreConfig) -> None:
        self._config = config

    async def __call__(self, resource_ref: str) -> Mapping[str, Any] | None:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            await connection.execute("SELECT pg_advisory_xact_lock_shared(%s)", (_PROMOTION_LOCK,))
            cursor = await connection.execute(
                "WITH effective AS ("
                "SELECT d.resource_id, d.resource_type, d.props, d.change_kind, 0 AS priority "
                "FROM inventory_realtime_resource d WHERE d.resource_id=%s "
                "UNION ALL SELECT r.resource_id, r.resource_type, r.props, 'upsert', 1 "
                "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                "JOIN inventory_snapshot_resource r ON r.snapshot_id=a.snapshot_id "
                "WHERE a.singleton=TRUE AND s.status='active' AND r.resource_id=%s) "
                "SELECT resource_id, resource_type, props, change_kind FROM effective "
                "ORDER BY priority LIMIT 1",
                (resource_ref, resource_ref),
            )
            row = await cursor.fetchone()
        if row is None or row["change_kind"] == "delete":
            return None
        props = row["props"]
        if isinstance(props, str):
            props = json.loads(props)
        return {
            "resource_id": str(row["resource_id"]),
            "resource_type": str(row["resource_type"]),
            "props": dict(props) if isinstance(props, Mapping) else {},
        }


def _resource_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    props = row["props"]
    if isinstance(props, str):
        props = json.loads(props)
    props = dict(props) if isinstance(props, Mapping) else {}
    return {
        "id": row["resource_id"],
        "type": row["resource_type"],
        "name": str(props.get("name") or row["resource_id"]),
        "status": str(props.get("status") or "unknown"),
        **({"parent_id": props["parent_id"]} if props.get("parent_id") else {}),
    }


def _source_priority(metadata: object) -> int:
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    if not isinstance(metadata, Mapping):
        return 2**31 - 1
    value = metadata.get("source_priority")
    return value if isinstance(value, int) and not isinstance(value, bool) else 2**31 - 1


def _unavailable_graph() -> dict[str, Any]:
    return {
        "snapshot_at": datetime.now(tz=UTC).isoformat(),
        "freshness": "unknown",
        "source": "unavailable",
        "observation_kind": "observed",
        "age_seconds": None,
        "coverage": {"scopes": [], "resource_types": []},
        "coverage_gaps": ["no active inventory snapshot"],
        "degraded": True,
        "realtime": {"pending_changes": 0, "latest_at": None},
        "resources": [],
        "links": [],
        "views": [],
        "truncated": False,
        "cursor": None,
    }


__all__ = [
    "PostgresInventoryAgeProvider",
    "PostgresInventoryContextProvider",
    "PostgresInventoryGraphProvider",
    "PostgresInventorySnapshotStore",
    "PostgresInventorySnapshotStoreConfig",
]
