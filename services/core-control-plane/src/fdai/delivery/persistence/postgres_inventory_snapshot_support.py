"""Shared encoding and context-read helpers for PostgreSQL inventory snapshots."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime
from typing import Any, Final, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.delivery.inventory_json_budget import inventory_json_exceeds_budget
from fdai.shared.providers.inventory import InventoryBatch, LinkRecord, ResourceRecord
from fdai.shared.providers.inventory_snapshot import InventoryCoverageManifest
from fdai.shared.providers.state_evidence import LINK_OBSERVATION_METADATA_PROPERTY

MAX_STAGE_JSON_BYTES: Final[int] = 1024 * 1024
MAX_STAGE_BATCH_BYTES: Final[int] = 4 * 1024 * 1024


class InventorySnapshotConnectionConfig(Protocol):
    """Connection fields required by focused inventory snapshot readers."""

    @property
    def dsn(self) -> str:
        """Return the PostgreSQL connection string."""
        ...

    @property
    def statement_timeout_ms(self) -> int:
        """Return the per-statement timeout."""
        ...

    @property
    def connect_timeout_s(self) -> int:
        """Return the connection timeout."""
        ...


async def read_inventory_context(
    config: InventorySnapshotConnectionConfig,
    resource_ref: str,
    *,
    promotion_lock: int,
) -> Mapping[str, Any] | None:
    """Return trusted properties for one resource in the active snapshot."""

    async with await psycopg.AsyncConnection.connect(
        config.dsn,
        row_factory=dict_row,
        connect_timeout=config.connect_timeout_s,
    ) as connection:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(config.statement_timeout_ms),),
        )
        await connection.execute("SELECT pg_advisory_xact_lock_shared(%s)", (promotion_lock,))
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


async def stage_snapshot_batch(
    connection: psycopg.AsyncConnection[Any],
    *,
    attempt_id: str,
    batch: InventoryBatch,
    write_batch_size: int,
    immutable_resources: bool = False,
) -> None:
    """Write candidate rows under the caller's collecting-attempt lock and transaction."""
    for rows in snapshot_write_batches(
        (_resource_stage_row(attempt_id, item) for item in batch.resources),
        max_rows=write_batch_size,
    ):
        cursor = await connection.execute(
            "INSERT INTO inventory_snapshot_resource "
            "(snapshot_id, resource_id, resource_type, props, provider_ref, last_seen) "
            "SELECT item.snapshot_id, item.resource_id, item.resource_type, "
            "item.props, item.provider_ref, item.last_seen "
            "FROM jsonb_to_recordset(%s::jsonb) AS item("
            "snapshot_id text, resource_id text, resource_type text, props jsonb, "
            "provider_ref text, last_seen timestamptz) "
            "ON CONFLICT (snapshot_id, resource_id) DO UPDATE SET "
            "resource_type = CASE WHEN inventory_snapshot_resource.resource_type = "
            "EXCLUDED.resource_type THEN EXCLUDED.resource_type ELSE NULL END, "
            "props = EXCLUDED.props, provider_ref = EXCLUDED.provider_ref, "
            "last_seen = EXCLUDED.last_seen "
            "WHERE NOT %s OR (inventory_snapshot_resource.resource_type=EXCLUDED.resource_type "
            "AND inventory_snapshot_resource.props=EXCLUDED.props "
            "AND inventory_snapshot_resource.provider_ref "
            "IS NOT DISTINCT FROM EXCLUDED.provider_ref "
            "AND inventory_snapshot_resource.last_seen IS NOT DISTINCT FROM EXCLUDED.last_seen)",
            (Jsonb(rows), immutable_resources),
        )
        if immutable_resources and cursor.rowcount != len(rows):
            raise ValueError("inventory resource changed across immutable collection chunks")
    for rows in snapshot_write_batches(
        (_link_stage_row(attempt_id, item) for item in batch.links),
        max_rows=write_batch_size,
    ):
        await connection.execute(
            "INSERT INTO inventory_snapshot_link "
            "(snapshot_id, from_id, from_type, link_type, to_id, to_type, props) "
            "SELECT item.snapshot_id, item.from_id, item.from_type, item.link_type, "
            "item.to_id, item.to_type, item.props "
            "FROM jsonb_to_recordset(%s::jsonb) AS item("
            "snapshot_id text, from_id text, from_type text, link_type text, "
            "to_id text, to_type text, props jsonb) "
            "ON CONFLICT (snapshot_id, from_id, link_type, to_id) DO UPDATE SET "
            "from_type = EXCLUDED.from_type, to_type = EXCLUDED.to_type, "
            "props = EXCLUDED.props",
            (Jsonb(rows),),
        )


def _resource_stage_row(attempt_id: str, item: ResourceRecord) -> tuple[dict[str, Any], int]:
    encoded_props = canonical_json_mapping(item.props, "snapshot resource props")
    row = {
        "snapshot_id": attempt_id,
        "resource_id": item.resource_id,
        "resource_type": item.type,
        "props": json.loads(encoded_props),
        "provider_ref": item.provider_ref,
        "last_seen": item.last_seen,
    }
    row_bytes = (
        len(encoded_props.encode("utf-8"))
        + len(item.resource_id.encode("utf-8"))
        + len(item.type.encode("utf-8"))
        + len((item.provider_ref or "").encode("utf-8"))
        + len((item.last_seen or "").encode("utf-8"))
        + len(attempt_id.encode("utf-8"))
        + 128
    )
    return row, row_bytes


def _link_stage_row(attempt_id: str, item: LinkRecord) -> tuple[dict[str, Any], int]:
    encoded_props = canonical_json_mapping(
        snapshot_relationship_props(item), "snapshot relationship props"
    )
    row = {
        "snapshot_id": attempt_id,
        "from_id": item.from_id,
        "from_type": item.from_type,
        "link_type": item.link_type,
        "to_id": item.to_id,
        "to_type": item.to_type,
        "props": json.loads(encoded_props),
    }
    row_bytes = (
        len(encoded_props.encode("utf-8"))
        + len(item.from_id.encode("utf-8"))
        + len(item.from_type.encode("utf-8"))
        + len(item.link_type.encode("utf-8"))
        + len(item.to_id.encode("utf-8"))
        + len(item.to_type.encode("utf-8"))
        + len(attempt_id.encode("utf-8"))
        + 128
    )
    return row, row_bytes


def snapshot_write_batches(
    rows: Iterable[tuple[dict[str, Any], int]],
    *,
    max_rows: int,
    max_bytes: int = MAX_STAGE_BATCH_BYTES,
) -> Iterator[list[dict[str, Any]]]:
    """Bound pending recordset rows and UTF-8 JSON parameter bytes per SQL statement."""
    if max_rows < 1 or max_bytes < 1:
        raise ValueError("inventory snapshot batch limits MUST be >= 1")
    pending: list[dict[str, Any]] = []
    pending_bytes = 2
    for row, row_bytes in rows:
        if row_bytes + 2 > max_bytes:
            raise ValueError("inventory snapshot row exceeds the write-buffer byte limit")
        if pending and (len(pending) >= max_rows or pending_bytes + row_bytes + 1 > max_bytes):
            yield pending
            pending = []
            pending_bytes = 2
        pending.append(row)
        pending_bytes += row_bytes + (1 if len(pending) > 1 else 0)
    if pending:
        yield pending


async def require_candidate_promotion_window(
    connection: psycopg.AsyncConnection[Any],
    *,
    attempt_id: str,
    manifest: InventoryCoverageManifest,
    completed: datetime,
) -> datetime:
    """Bind promotion ordering and overlay cleanup to the locked candidate row."""
    candidate_cursor = await connection.execute(
        "SELECT source, scopes, resource_types, observation_kind, "
        "started_at, clock_timestamp() AS checked_at "
        "FROM inventory_snapshot WHERE id=%s FOR UPDATE",
        (attempt_id,),
    )
    candidate = await candidate_cursor.fetchone()
    if candidate is None or (
        candidate["source"] != manifest.source
        or tuple(candidate["scopes"]) != manifest.scopes
        or tuple(candidate["resource_types"]) != manifest.resource_types
        or candidate["observation_kind"] != manifest.observation_kind.value
    ):
        raise ValueError("inventory candidate binding mismatch")
    candidate_started = candidate["started_at"]
    if (
        not isinstance(candidate_started, datetime)
        or candidate_started.utcoffset() is None
        or not isinstance(completed, datetime)
        or completed.utcoffset() is None
        or not candidate_started <= completed <= candidate["checked_at"]
    ):
        raise ValueError("inventory candidate observation interval is invalid")
    return candidate_started


def canonical_json_mapping(
    value: object, field: str, *, max_bytes: int = MAX_STAGE_JSON_BYTES
) -> str:
    """Encode one mapping as bounded canonical JSON before whole-string materialization."""

    if not isinstance(value, Mapping):
        raise ValueError(f"{field} MUST be an object")
    try:
        if inventory_json_exceeds_budget(value, maximum_bytes=max_bytes):
            raise ValueError(f"{field} exceeds its byte bound")
        encoder = json.JSONEncoder(
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        fragments: list[str] = []
        encoded_bytes = 0
        for fragment in encoder.iterencode(dict(value)):
            encoded_bytes += len(fragment.encode("utf-8"))
            if encoded_bytes > max_bytes:
                raise ValueError(f"{field} exceeds its byte bound")
            fragments.append(fragment)
        return "".join(fragments)
    except (TypeError, ValueError, RecursionError) as exc:
        if "byte bound" in str(exc) or "nesting depth" in str(exc):
            raise ValueError(str(exc)) from exc
        raise ValueError(f"{field} MUST be JSON-compatible") from exc


def snapshot_relationship_props(link: LinkRecord) -> Mapping[str, object]:
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


__all__ = [
    "MAX_STAGE_BATCH_BYTES",
    "MAX_STAGE_JSON_BYTES",
    "canonical_json_mapping",
    "read_inventory_context",
    "require_candidate_promotion_window",
    "snapshot_relationship_props",
    "snapshot_write_batches",
    "stage_snapshot_batch",
]
