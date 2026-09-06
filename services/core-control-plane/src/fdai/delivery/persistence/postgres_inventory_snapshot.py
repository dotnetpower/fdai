"""PostgreSQL immutable inventory candidates and active graph projection."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from fdai.core.views.architecture_graph import project_architecture_graph
from fdai.delivery.persistence.postgres_inventory_graph import load_rooted_inventory_graph
from fdai.delivery.persistence.postgres_inventory_graph_helpers import (
    _annotate_operating_scope,
    _load_operating_scope,
    _resource_payload,
    _source_priority,
    _unavailable_graph,
)
from fdai.shared.providers.inventory import (
    INVENTORY_RELATIONSHIP_RECONCILIATION_PREFIX,
    InventoryBatch,
    LinkRecord,
    ResourceRecord,
)
from fdai.shared.providers.inventory_snapshot import (
    InventoryAttemptFailure,
    InventoryCoverageManifest,
    InventoryObservationKind,
)
from fdai.shared.providers.state_evidence import LINK_OBSERVATION_METADATA_PROPERTY

_PROMOTION_LOCK: Final[int] = 732_410_991
_MAX_GRAPH_ROWS: Final[int] = 5000
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
    write_batch_size: int = 1000

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("dsn MUST NOT be empty")
        if self.freshness_budget_seconds < 1:
            raise ValueError("freshness_budget_seconds MUST be >= 1")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("database timeouts MUST be >= 1")
        if not 1 <= self.write_batch_size <= 10_000:
            raise ValueError("write_batch_size MUST be between 1 and 10000")


class PostgresInventorySnapshotStore:
    """Stage candidate rows and atomically swap the active snapshot pointer."""

    def __init__(self, *, config: PostgresInventorySnapshotStoreConfig) -> None:
        self._config = config

    async def begin(self, manifest: InventoryCoverageManifest) -> str:
        attempt_id = str(uuid4())
        started = manifest.started_at or datetime.now(tz=UTC)
        metadata_json = _canonical_json_mapping(manifest.metadata, "snapshot metadata")
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
                        metadata_json,
                        started,
                    ),
                )
        return attempt_id

    async def stage(self, attempt_id: str, batch: InventoryBatch) -> None:
        if batch.final:
            raise ValueError("terminal inventory fences are not staged")
        for resource in batch.resources:
            _canonical_json_mapping(resource.props, "snapshot resource props")
        for link in batch.links:
            _canonical_json_mapping(link.link_props, "snapshot relationship props")
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await self._require_collecting(connection, attempt_id)
                cursor = connection.cursor()
                for offset in range(0, len(batch.resources), self._config.write_batch_size):
                    resource_rows = [
                        (
                            attempt_id,
                            item.resource_id,
                            item.type,
                            _canonical_json_mapping(item.props, "snapshot resource props"),
                            item.provider_ref,
                            item.last_seen,
                        )
                        for item in batch.resources[offset : offset + self._config.write_batch_size]
                    ]
                    await self._executemany(
                        cursor,
                        "INSERT INTO inventory_snapshot_resource "
                        "(snapshot_id, resource_id, resource_type, props, provider_ref, last_seen) "
                        "VALUES (%s, %s, %s, %s::jsonb, %s, %s) "
                        "ON CONFLICT (snapshot_id, resource_id) DO UPDATE SET "
                        "resource_type = CASE WHEN inventory_snapshot_resource.resource_type = "
                        "EXCLUDED.resource_type THEN EXCLUDED.resource_type ELSE NULL END, "
                        "props = EXCLUDED.props, provider_ref = EXCLUDED.provider_ref, "
                        "last_seen = EXCLUDED.last_seen",
                        resource_rows,
                    )
                for offset in range(0, len(batch.links), self._config.write_batch_size):
                    link_rows = [
                        (
                            attempt_id,
                            item.from_id,
                            item.from_type,
                            item.link_type,
                            item.to_id,
                            item.to_type,
                            _canonical_json_mapping(
                                _snapshot_relationship_props(item),
                                "snapshot relationship props",
                            ),
                        )
                        for item in batch.links[offset : offset + self._config.write_batch_size]
                    ]
                    await self._executemany(
                        cursor,
                        "INSERT INTO inventory_snapshot_link "
                        "(snapshot_id, from_id, from_type, link_type, to_id, to_type, props) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb) "
                        "ON CONFLICT (snapshot_id, from_id, link_type, to_id) DO UPDATE SET "
                        "from_type = EXCLUDED.from_type, to_type = EXCLUDED.to_type, "
                        "props = EXCLUDED.props",
                        link_rows,
                    )

    async def _executemany(
        self,
        cursor: psycopg.AsyncCursor[Any],
        query: str,
        rows: list[tuple[Any, ...]],
    ) -> None:
        await cursor.executemany(query, rows)

    async def promote(self, attempt_id: str, manifest: InventoryCoverageManifest) -> None:
        completed = manifest.completed_at or datetime.now(tz=UTC)
        metadata_json = _canonical_json_mapping(manifest.metadata, "snapshot metadata")
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                await connection.execute("SELECT pg_advisory_xact_lock(%s)", (_PROMOTION_LOCK,))
                await self._require_collecting(connection, attempt_id)
                active_cursor = await connection.execute(
                    "SELECT a.snapshot_id, s.started_at, s.observation_kind, s.metadata "
                    "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                    "WHERE a.singleton=TRUE FOR UPDATE"
                )
                active = await active_cursor.fetchone()
                candidate_started = manifest.started_at or completed
                state_base_generation = manifest.metadata.get("state_base_generation")
                state_base_checked = "state_base_generation" in manifest.metadata
                if (
                    state_base_checked
                    and state_base_generation is not None
                    and (
                        not isinstance(state_base_generation, str)
                        or not state_base_generation.strip()
                        or len(state_base_generation) > 256
                    )
                ):
                    raise ValueError("inventory state base generation is malformed")
                if state_base_checked and (
                    (state_base_generation is None and active is not None)
                    or (
                        state_base_generation is not None
                        and (active is None or active["snapshot_id"] != state_base_generation)
                    )
                ):
                    raise ValueError("inventory state base generation changed before promotion")
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
                ambiguous_parent = await connection.execute(
                    "SELECT 1 FROM inventory_snapshot_link "
                    "WHERE snapshot_id=%s AND link_type='contains' "
                    "GROUP BY to_id HAVING COUNT(DISTINCT from_id) > 1 LIMIT 1",
                    (attempt_id,),
                )
                if await ambiguous_parent.fetchone() is not None:
                    raise ValueError("inventory candidate violates contains parent cardinality")
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
                        metadata_json,
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
                if manifest.metadata.get("coverage_scope") == "full_provider_scope":
                    await connection.execute(
                        "DELETE FROM state_kv WHERE key = ANY(%s::text[]) "
                        "AND (value->>'observed_at')::timestamptz <= %s",
                        (
                            [
                                f"{INVENTORY_RELATIONSHIP_RECONCILIATION_PREFIX}{scope}"
                                for scope in manifest.scopes
                            ],
                            candidate_started,
                        ),
                    )

    async def fail(self, attempt_id: str, failure: InventoryAttemptFailure) -> None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            await connection.execute(
                "UPDATE inventory_snapshot SET status='failed', completed_at=NOW(), "
                "failure_code=%s, failure_message=%s WHERE id=%s AND status='collecting'",
                (failure.code.value, failure.message, attempt_id),
            )

    async def active_snapshot_id(self) -> str | None:
        """Reread the durable active pointer after a promotion attempt."""
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT snapshot_id FROM inventory_active WHERE singleton=TRUE"
            )
            row = await cursor.fetchone()
        return str(row["snapshot_id"]) if row is not None else None

    async def read_active_resources(
        self,
        *,
        resource_ids: tuple[str, ...],
    ) -> tuple[str | None, Mapping[str, ResourceRecord]]:
        """Read exact prior Resources for monotonic state enrichment."""

        if resource_ids != tuple(sorted(set(resource_ids))) or len(resource_ids) > 1000:
            raise ValueError("active Resource ids MUST be unique, ordered, and bounded")
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_timeout(connection)
                active_cursor = await connection.execute(
                    "SELECT snapshot_id FROM inventory_active WHERE singleton=TRUE FOR SHARE"
                )
                active = await active_cursor.fetchone()
                if active is None:
                    return None, {}
                snapshot_id = str(active["snapshot_id"])
                if not resource_ids:
                    return snapshot_id, {}
                cursor = await connection.execute(
                    "SELECT resource_id, resource_type, props, provider_ref, last_seen "
                    "FROM inventory_snapshot_resource "
                    "WHERE snapshot_id=%s AND resource_id=ANY(%s::text[]) "
                    "ORDER BY resource_id",
                    (snapshot_id, list(resource_ids)),
                )
                rows = await cursor.fetchall()
        resources = {
            str(row["resource_id"]): ResourceRecord(
                resource_id=str(row["resource_id"]),
                type=str(row["resource_type"]),
                props=dict(row["props"]),
                provider_ref=(
                    str(row["provider_ref"]) if row["provider_ref"] is not None else None
                ),
                last_seen=(row["last_seen"].isoformat() if row["last_seen"] is not None else None),
            )
            for row in rows
        }
        return snapshot_id, resources

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


def _snapshot_relationship_props(link: LinkRecord) -> Mapping[str, object]:
    """Retain reviewed mapping or observation evidence without provider payloads."""

    properties: dict[str, object] = dict(link.link_props)
    evidence = link.mapping_evidence
    if evidence is not None:
        properties["provider_relationship_evidence"] = {
            "mapping_id": evidence.mapping_id,
            "mapping_revision": evidence.mapping_revision,
            "mapping_receipt_ref": evidence.mapping_receipt_ref,
            "source_identity": evidence.source_identity,
            "source_property_path": evidence.source_property_path,
            "source_schema_version": evidence.source_schema_version,
            "source_schema_digest": evidence.source_schema_digest,
            "evidence_method": evidence.evidence_method,
            "freshness_ceiling_seconds": evidence.freshness_ceiling_seconds,
            "observation_receipt_ref": evidence.observation_receipt_ref,
        }
    if link.observation_metadata is not None:
        properties[LINK_OBSERVATION_METADATA_PROPERTY] = link.observation_metadata.to_mapping()
    return properties


class PostgresInventoryGraphProvider:
    """Serve the active immutable inventory generation to the Operator API."""

    def __init__(self, *, config: PostgresInventorySnapshotStoreConfig) -> None:
        self._config = config

    async def coverage_summary(self, limit: int) -> Mapping[str, Any]:
        """Return active-snapshot coverage without decoding resource properties."""
        if limit < 1:
            raise ValueError("inventory coverage limit MUST be positive")
        async with await self._connect() as connection:
            await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
            await connection.set_read_only(True)
            await self._set_timeout(connection)
            await connection.execute("SELECT pg_advisory_xact_lock_shared(%s)", (_PROMOTION_LOCK,))
            cursor = await connection.execute(
                "SELECT s.id, s.source, s.observation_kind, s.completed_at, "
                "(SELECT COUNT(*) FROM inventory_snapshot_resource r "
                "WHERE r.snapshot_id=s.id) AS resource_count, "
                "(SELECT COUNT(*) FROM inventory_snapshot_link l "
                "WHERE l.snapshot_id=s.id) AS link_count "
                "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                "WHERE a.singleton=TRUE"
            )
            snapshot = await cursor.fetchone()
            if snapshot is None:
                return {
                    "source": "unavailable",
                    "freshness": "unavailable",
                    "resource_count": 0,
                    "link_count": 0,
                    "truncated": False,
                }
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
        age_seconds = max(
            0,
            int((datetime.now(tz=UTC) - snapshot["completed_at"]).total_seconds()),
        )
        stale = (
            age_seconds > self._config.freshness_budget_seconds
            or snapshot["observation_kind"] == InventoryObservationKind.EXPECTED.value
            or newer_failure is not None
        )
        pending_changes = int(overlay["pending_changes"] or 0) if overlay is not None else 0
        freshness = "unknown" if pending_changes else ("stale" if stale else "fresh")
        resource_count = int(snapshot["resource_count"])
        link_count = int(snapshot["link_count"])
        return {
            "source": snapshot["source"],
            "freshness": freshness,
            "resource_count": resource_count,
            "link_count": link_count,
            "truncated": resource_count + link_count > limit,
        }

    async def __call__(
        self,
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> Mapping[str, Any]:
        async with await self._connect() as connection:
            await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
            await connection.set_read_only(True)
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
            collection_health_cursor = await connection.execute(
                "SELECT value FROM state_kv WHERE key='inventory-collection-health'"
            )
            collection_health_row = await collection_health_cursor.fetchone()
            rows: Sequence[Mapping[str, Any]]
            if root is not None:
                rooted = await load_rooted_inventory_graph(
                    connection,
                    snapshot_id=str(snapshot["id"]),
                    root=root,
                    depth=depth,
                    link_types=link_types,
                    limit=limit,
                )
                rows = rooted.resources
                links: Sequence[Mapping[str, Any]] = rooted.links
                truncated = rooted.truncated
                truncation_reasons = list(rooted.truncation_reasons)
            else:
                resources_cursor = await connection.execute(
                    _ALL_RESOURCES_QUERY,
                    (snapshot["id"], _MAX_GRAPH_ROWS + 1),
                )
                rows = await resources_cursor.fetchall()
                truncated = len(rows) > _MAX_GRAPH_ROWS
                truncation_reasons = ["source_limit"] if truncated else []
                rows = rows[:_MAX_GRAPH_ROWS]
                links = ()
                selected_ids = [str(row["resource_id"]) for row in rows]
                if selected_ids:
                    classification_link_types = tuple(dict.fromkeys((*link_types, "contains")))
                    links_cursor = await connection.execute(
                        _SELECT_EFFECTIVE_LINKS_QUERY,
                        (
                            snapshot["id"],
                            selected_ids,
                            selected_ids,
                            list(classification_link_types),
                        ),
                    )
                    links = await links_cursor.fetchall()
            resource_ids = tuple(str(row["resource_id"]) for row in rows)
            (
                operating_objects,
                operating_links,
                operating_scope_complete,
            ) = await _load_operating_scope(connection, resource_ids)
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
        overlay_latest = overlay["latest_at"] if overlay is not None else None
        pending_changes = int(overlay["pending_changes"] or 0) if overlay is not None else 0
        if pending_changes > 0:
            freshness = "unknown"
        graph_links = [
            {"source": row["from_id"], "target": row["to_id"], "type": row["link_type"]}
            for row in links
        ]
        resources = [_resource_payload(row, include_props=True) for row in rows]
        if root is None:
            projection = project_architecture_graph(
                resources=resources,
                links=graph_links,
                requested_view=scope,
            )
        else:
            projection = {
                "active_view": scope or f"resource:{root}",
                "resources": [
                    {key: value for key, value in resource.items() if key != "props"}
                    for resource in resources
                ],
                "links": graph_links,
                "views": [],
            }
        projection_resources, operating_scope = _annotate_operating_scope(
            projection["resources"],
            source_revision=str(snapshot["id"]),
            objects=operating_objects,
            links=operating_links,
            input_complete=operating_scope_complete,
        )
        if not operating_scope_complete:
            coverage_gaps.append("operating_scope_truncated")
        elif operating_scope["unmapped_resource_count"]:
            coverage_gaps.append("operating_scope_unmapped")
        degraded = freshness != "fresh" or bool(coverage_gaps)
        collection_health = (
            collection_health_row["value"]
            if collection_health_row is not None
            and isinstance(collection_health_row["value"], Mapping)
            else None
        )
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
            "collection_health": collection_health,
            "active_view": projection["active_view"],
            "resources": projection_resources,
            "links": [link for link in projection["links"] if link["type"] in link_types],
            "views": projection["views"],
            "operating_scope": operating_scope,
            "truncated": truncated,
            "truncation_reasons": truncation_reasons,
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
                "AS resource_present, EXISTS (SELECT 1 FROM inventory_realtime_resource d "
                "WHERE d.resource_id=%s) AS realtime_pending, "
                "EXISTS (SELECT 1 FROM inventory_snapshot newer "
                "WHERE newer.id<>s.id AND newer.started_at>s.completed_at AND ("
                "newer.status='failed' OR (newer.status='collecting' AND "
                "newer.started_at < NOW() - INTERVAL '30 minutes'))) AS newer_failure "
                "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                "WHERE a.singleton=TRUE AND s.status='active'",
                (resource_ref, resource_ref, resource_ref, resource_ref),
            )
            row = await cursor.fetchone()
        if row is None or row["age_seconds"] is None:
            return None
        if not row["resource_present"] or row["realtime_pending"] or row["newer_failure"]:
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


__all__ = [
    "PostgresInventoryAgeProvider",
    "PostgresInventoryContextProvider",
    "PostgresInventoryGraphProvider",
    "PostgresInventorySnapshotStore",
    "PostgresInventorySnapshotStoreConfig",
]
