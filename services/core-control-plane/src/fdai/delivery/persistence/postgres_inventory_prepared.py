"""Content-bound inventory candidates; sealing alone never advances an active graph."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.delivery.azure.inventory_redaction import redact_runtime_environment
from fdai.delivery.inventory_collection import collection_context_digest, collection_key
from fdai.delivery.inventory_sync_models import (
    InventoryProjectionSourceState,
    InventoryProjectionSourceStatus,
    PromotedInventoryObservation,
    compute_relationship_coverage,
)
from fdai.delivery.persistence.postgres_inventory_chunks import require_collection_context
from fdai.delivery.persistence.postgres_inventory_snapshot_support import (
    InventorySnapshotConnectionConfig,
    snapshot_relationship_props,
)
from fdai.shared.providers.inventory import (
    LinkRecord,
    ProviderRelationshipEvidence,
    RelationshipDrop,
    RelationshipDropReason,
    RelationshipUnavailableReason,
    ResourceRecord,
)
from fdai.shared.providers.inventory_snapshot import (
    InventoryCoverageManifest,
    InventoryObservationKind,
)
from fdai.shared.providers.ontology_instance import normalize_json_value
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
)

_MAX_SEAL_BYTES = 32 * 1024 * 1024


def _digest(value: object) -> str:
    digest = hashlib.sha256()
    size = 0
    for part in json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False).iterencode(
        normalize_json_value(value)
    ):
        encoded = part.encode()
        size += len(encoded)
        if size > _MAX_SEAL_BYTES:
            raise ValueError("inventory prepared content exceeds its byte bound")
        digest.update(encoded)
    return "sha256:" + digest.hexdigest()


def _time(value: str | datetime | None) -> str | None:
    if value is None:
        return None
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if parsed.tzinfo is None:
        raise ValueError("inventory prepared time must be timezone-aware")
    return parsed.astimezone(UTC).isoformat()


def candidate_graph_digest(observation: PromotedInventoryObservation) -> str:
    if (
        not observation.complete
        or observation.recorded_at is None
        or len(observation.resources) > 50_000
        or len(observation.links) > 200_000
        or len({item.resource_id for item in observation.resources}) != len(observation.resources)
        or len({(item.from_id, item.link_type, item.to_id) for item in observation.links})
        != len(observation.links)
        or any(item.props.get("_truncated") is True for item in observation.resources)
        or any(redact_runtime_environment(item) != item for item in observation.resources)
        or any(
            item.observation_metadata is None
            or not item.observation_metadata.verified
            or item.observation_metadata.inventory_generation != observation.generation
            or item.observation_metadata.state_fact.synthetic
            or item.observation_metadata.state_fact.conflicts
            or item.observation_metadata.state_fact.completeness != 1.0
            for item in observation.links
        )
    ):
        raise ValueError("inventory prepared candidate requires complete verified observations")
    resources = [
        {
            "resource_id": item.resource_id,
            "resource_type": item.type,
            "props": item.props,
            "provider_ref": item.provider_ref,
            "last_seen": _time(item.last_seen),
        }
        for item in sorted(observation.resources, key=lambda item: item.resource_id)
    ]
    links = [
        {
            "from_id": item.from_id,
            "from_type": item.from_type,
            "link_type": item.link_type,
            "to_id": item.to_id,
            "to_type": item.to_type,
            "props": snapshot_relationship_props(item),
        }
        for item in sorted(
            observation.links, key=lambda item: (item.from_id, item.link_type, item.to_id)
        )
    ]
    return _digest({"resources": resources, "links": links})


async def _stored_graph_digest(connection: psycopg.AsyncConnection[Any], attempt_id: str) -> str:
    cursor = await connection.execute(
        "SELECT resource_id, resource_type, props, provider_ref, last_seen "
        "FROM inventory_snapshot_resource WHERE snapshot_id=%s ORDER BY resource_id LIMIT 50001",
        (attempt_id,),
    )
    resources = await cursor.fetchall()
    cursor = await connection.execute(
        "SELECT from_id, from_type, link_type, to_id, to_type, props "
        "FROM inventory_snapshot_link WHERE snapshot_id=%s "
        "ORDER BY from_id, link_type, to_id LIMIT 200001",
        (attempt_id,),
    )
    links = await cursor.fetchall()
    if len(resources) > 50_000 or len(links) > 200_000:
        raise ValueError("inventory prepared graph exceeds its record bound")
    return _digest(
        {
            "resources": [
                {**row, "last_seen": _time(row["last_seen"])}
                for row in sorted(resources, key=lambda row: row["resource_id"])
            ],
            "links": sorted(
                links, key=lambda row: (row["from_id"], row["link_type"], row["to_id"])
            ),
        }
    )


async def require_collecting(connection: psycopg.AsyncConnection[Any], attempt_id: str) -> None:
    cursor = await connection.execute(
        "SELECT status FROM inventory_snapshot WHERE id=%s FOR UPDATE", (attempt_id,)
    )
    row = await cursor.fetchone()
    if row is None or row["status"] != "collecting":
        raise ValueError("inventory attempt is missing or no longer collecting")


async def require_unsealed(connection: psycopg.AsyncConnection[Any], attempt_id: str) -> None:
    cursor = await connection.execute(
        "SELECT 1 FROM state_kv WHERE key=%s", (collection_key(attempt_id) + ":prepared",)
    )
    if await cursor.fetchone() is not None:
        raise ValueError("inventory prepared candidate cannot be changed")


def _validate_candidate_manifest(
    manifest: InventoryCoverageManifest, observation: PromotedInventoryObservation
) -> None:
    metadata = manifest.metadata
    if (
        manifest.started_at is None
        or manifest.completed_at is None
        or observation.recorded_at is None
        or not manifest.started_at <= observation.recorded_at <= manifest.completed_at
        or observation.complete is not True
        or len(observation.relationship_drops) > 200_000
        or type(observation.state_base_generation_checked) is not bool
        or metadata.get("projection_complete") is not True
        or metadata.get("prepared_candidate_required") is not True
        or ("state_base_generation" in metadata) != observation.state_base_generation_checked
        or metadata.get("state_base_generation") != observation.state_base_generation
        or any(
            state.observed_at is not None and state.observed_at > observation.recorded_at
            for state in observation.source_states
        )
        or _digest(metadata.get("relationship_coverage"))
        != _digest(compute_relationship_coverage(observation).to_metadata())
        or _digest(metadata.get("derived_source_states", []))
        != _digest(
            [state.to_metadata() for state in observation.source_states if not state.additive]
        )
        or _digest(metadata.get("additive_source_states", []))
        != _digest([state.to_metadata() for state in observation.source_states if state.additive])
    ):
        raise ValueError("inventory prepared manifest differs from its observation")


async def _require_source_window(
    connection: psycopg.AsyncConnection[Any], attempt_id: str, manifest: InventoryCoverageManifest
) -> None:
    cursor = await connection.execute(
        "SELECT started_at, clock_timestamp() AS current_time FROM inventory_snapshot WHERE id=%s",
        (attempt_id,),
    )
    row = await cursor.fetchone()
    if (
        row is None
        or manifest.started_at != row["started_at"]
        or manifest.completed_at is None
        or manifest.completed_at > row["current_time"]
    ):
        raise ValueError("inventory prepared source window changed or is in the future")


async def seal_candidate(
    config: InventorySnapshotConnectionConfig,
    source_manifest: InventoryCoverageManifest,
    manifest: InventoryCoverageManifest,
    observation: PromotedInventoryObservation,
) -> Mapping[str, Any]:
    """Seal exact staged bytes after source exhaustion; retain the original observation clocks."""
    _validate_candidate_manifest(manifest, observation)
    if (
        manifest.source != source_manifest.source
        or manifest.scopes != source_manifest.scopes
        or manifest.resource_types != source_manifest.resource_types
        or manifest.observation_kind != source_manifest.observation_kind
        or manifest.started_at != source_manifest.started_at
        or manifest.completed_at is None
        or observation.recorded_at is None
        or manifest.completed_at < observation.recorded_at
        or manifest.metadata.get("projection_complete") is not True
        or normalize_json_value(manifest.metadata.get("relationship_coverage"))
        != normalize_json_value(compute_relationship_coverage(observation).to_metadata())
        or any(
            normalize_json_value(manifest.metadata.get(key)) != normalize_json_value(value)
            for key, value in source_manifest.metadata.items()
            if key != "provider_scope_coverage"
        )
    ):
        raise ValueError("inventory prepared manifest does not match its source")
    attempt_id = observation.generation
    record: dict[str, Any] = normalize_json_value(
        {
            "schema_version": "1.0.0",
            "attempt_id": attempt_id,
            "context_digest": collection_context_digest(source_manifest),
            "manifest": asdict(manifest),
            "recorded_at": _time(observation.recorded_at),
            "graph_digest": candidate_graph_digest(observation),
            "auxiliary": {
                "mapping_evidence": [
                    {
                        "identity": [item.from_id, item.link_type, item.to_id],
                        "evidence": asdict(item.mapping_evidence),
                        "properties": {
                            key: value
                            for key, value in item.link_props.items()
                            if key == "provider_relationship_evidence"
                        },
                    }
                    for item in observation.links
                    if item.mapping_evidence is not None
                ],
                "relationship_drops": [asdict(item) for item in observation.relationship_drops],
                "source_states": [asdict(item) for item in observation.source_states],
                "state_base_generation": observation.state_base_generation,
                "state_base_generation_checked": observation.state_base_generation_checked,
            },
        }
    )
    record["content_digest"] = _digest(record)
    async with (
        asyncio.timeout(30),
        await psycopg.AsyncConnection.connect(
            config.dsn, row_factory=dict_row, connect_timeout=config.connect_timeout_s
        ) as connection,
    ):
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)", (str(config.statement_timeout_ms),)
        )
        await require_collecting(connection, attempt_id)
        await require_collection_context(connection, attempt_id, record["context_digest"])
        await _require_source_window(connection, attempt_id, manifest)
        if await _stored_graph_digest(connection, attempt_id) != record["graph_digest"]:
            raise ValueError("inventory prepared graph differs from staged observations")
        key = collection_key(attempt_id) + ":prepared"
        await connection.execute(
            "INSERT INTO state_kv (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
            (key, Jsonb(record)),
        )
        cursor = await connection.execute("SELECT value FROM state_kv WHERE key=%s", (key,))
        retained = await cursor.fetchone()
        if retained is None or _digest(retained["value"]) != _digest(record):
            raise ValueError("inventory prepared candidate content changed")
    return record


async def verify_prepared_candidate(
    connection: psycopg.AsyncConnection[Any], attempt_id: str, manifest: InventoryCoverageManifest
) -> None:
    """Recheck a seal inside promotion; legacy unsealed attempts keep their existing checks."""
    cursor = await connection.execute(
        "SELECT value FROM state_kv WHERE key=%s", (collection_key(attempt_id) + ":prepared",)
    )
    row = await cursor.fetchone()
    if row is None:
        if manifest.metadata.get("prepared_candidate_required") is True:
            raise ValueError("inventory prepared seal is missing")
        return
    record = row["value"]
    if (
        not isinstance(record, Mapping)
        or set(record)
        != {
            "schema_version",
            "attempt_id",
            "context_digest",
            "manifest",
            "recorded_at",
            "graph_digest",
            "auxiliary",
            "content_digest",
        }
        or record.get("schema_version") != "1.0.0"
        or record.get("attempt_id") != attempt_id
        or record.get("content_digest")
        != _digest({key: value for key, value in record.items() if key != "content_digest"})
        or _digest(record.get("manifest")) != _digest(asdict(manifest))
    ):
        raise ValueError("inventory prepared seal is invalid or manifest changed")
    await require_collection_context(connection, attempt_id, record["context_digest"])
    await _require_source_window(connection, attempt_id, manifest)
    if await _stored_graph_digest(connection, attempt_id) != record.get("graph_digest"):
        raise ValueError("inventory prepared graph changed before promotion")


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("inventory prepared time is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("inventory prepared time must be timezone-aware")
    return parsed


async def load_prepared_candidate(
    config: InventorySnapshotConnectionConfig, source_manifest: InventoryCoverageManifest
) -> tuple[InventoryCoverageManifest, PromotedInventoryObservation] | None:
    """Resume only a fully sealed, unexpired candidate from the exact collection context."""
    context = collection_context_digest(source_manifest)
    async with (
        asyncio.timeout(30),
        await psycopg.AsyncConnection.connect(
            config.dsn, row_factory=dict_row, connect_timeout=config.connect_timeout_s
        ) as connection,
    ):
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)", (str(config.statement_timeout_ms),)
        )
        cursor = await connection.execute(
            "SELECT candidate.id, seal.key, seal.value FROM inventory_snapshot candidate "
            "JOIN state_kv seal ON seal.value->>'attempt_id'=candidate.id "
            "AND starts_with(seal.key, 'inventory-collection:') AND right(seal.key, 9)=':prepared' "
            "WHERE candidate.status='collecting' AND seal.value->>'context_digest'=%s "
            "AND candidate.started_at BETWEEN NOW()-INTERVAL '30 minutes' AND NOW() "
            "ORDER BY candidate.started_at DESC, candidate.id LIMIT 2 FOR UPDATE OF candidate",
            (context,),
        )
        candidates = await cursor.fetchall()
        if not candidates:
            return None
        if len(candidates) != 1:
            raise ValueError("inventory prepared recovery has ambiguous candidates")
        candidate = candidates[0]
        attempt_id = candidate["id"]
        if candidate["key"] != collection_key(attempt_id) + ":prepared":
            raise ValueError("inventory prepared recovery identity changed")
        record = candidate["value"]
        try:
            manifest_values = dict(record["manifest"])
            manifest_values["started_at"] = _datetime(manifest_values["started_at"])
            manifest_values["completed_at"] = _datetime(manifest_values["completed_at"])
            manifest_values["scopes"] = tuple(manifest_values["scopes"])
            manifest_values["resource_types"] = tuple(manifest_values["resource_types"])
            manifest_values["observation_kind"] = InventoryObservationKind(
                manifest_values["observation_kind"]
            )
            manifest = InventoryCoverageManifest(**manifest_values)
            await verify_prepared_candidate(connection, attempt_id, manifest)
            cursor = await connection.execute(
                "SELECT resource_id, resource_type, props, provider_ref, last_seen "
                "FROM inventory_snapshot_resource WHERE snapshot_id=%s "
                "ORDER BY resource_id LIMIT 50001",
                (attempt_id,),
            )
            resources = tuple(
                ResourceRecord(
                    resource_id=row["resource_id"],
                    type=row["resource_type"],
                    props=row["props"],
                    provider_ref=row["provider_ref"],
                    last_seen=_time(row["last_seen"]),
                )
                for row in sorted(await cursor.fetchall(), key=lambda row: row["resource_id"])
            )
            cursor = await connection.execute(
                "SELECT from_id, from_type, link_type, to_id, to_type, props "
                "FROM inventory_snapshot_link WHERE snapshot_id=%s "
                "ORDER BY from_id, link_type, to_id LIMIT 200001",
                (attempt_id,),
            )
            links = []
            auxiliary = record["auxiliary"]
            mapping_evidence = {
                tuple(item["identity"]): item for item in auxiliary["mapping_evidence"]
            }
            for row in sorted(
                await cursor.fetchall(),
                key=lambda row: (row["from_id"], row["link_type"], row["to_id"]),
            ):
                properties = dict(row.pop("props"))
                metadata = LinkObservationMetadata.from_mapping(
                    properties.pop(LINK_OBSERVATION_METADATA_PROPERTY)
                )
                retained_evidence = mapping_evidence.pop(
                    (row["from_id"], row["link_type"], row["to_id"]), None
                )
                evidence = None
                if retained_evidence is not None:
                    evidence = ProviderRelationshipEvidence(**retained_evidence["evidence"])
                    properties.pop("provider_relationship_evidence", None)
                    properties.update(retained_evidence["properties"])
                links.append(
                    LinkRecord(
                        **row,
                        link_props=properties,
                        mapping_evidence=evidence,
                        observation_metadata=metadata,
                    )
                )
            if mapping_evidence:
                raise ValueError("inventory prepared mapping evidence has no relationship")
            drops = tuple(
                RelationshipDrop(
                    **{
                        **item,
                        "reason": RelationshipDropReason(item["reason"]),
                        "unavailable_reason": RelationshipUnavailableReason(
                            item["unavailable_reason"]
                        )
                        if item["unavailable_reason"] is not None
                        else None,
                    }
                )
                for item in auxiliary["relationship_drops"]
            )
            states = tuple(
                InventoryProjectionSourceState(
                    **{
                        **item,
                        "status": InventoryProjectionSourceStatus(item["status"]),
                        "observed_at": _datetime(item["observed_at"])
                        if item["observed_at"] is not None
                        else None,
                    }
                )
                for item in auxiliary["source_states"]
            )
            observation = PromotedInventoryObservation(
                generation=attempt_id,
                resources=resources,
                links=tuple(links),
                complete=True,
                recorded_at=_datetime(record["recorded_at"]),
                relationship_drops=drops,
                source_states=states,
                state_base_generation=auxiliary["state_base_generation"],
                state_base_generation_checked=auxiliary["state_base_generation_checked"],
            )
            _validate_candidate_manifest(manifest, observation)
            if candidate_graph_digest(observation) != record["graph_digest"]:
                raise ValueError("inventory prepared recovery content changed")
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("inventory prepared recovery record is malformed") from exc
    return manifest, observation
