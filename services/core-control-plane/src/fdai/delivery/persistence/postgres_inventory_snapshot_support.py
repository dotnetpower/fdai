"""Shared encoding and context-read helpers for PostgreSQL inventory snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

from fdai.shared.providers.inventory import LinkRecord
from fdai.shared.providers.state_evidence import LINK_OBSERVATION_METADATA_PROPERTY


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


def canonical_json_mapping(value: object, field: str) -> str:
    """Encode one mapping as bounded canonical JSON."""

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
    "canonical_json_mapping",
    "read_inventory_context",
    "snapshot_relationship_props",
]
