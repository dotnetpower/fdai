"""Load one complete active inventory snapshot for journal-backed release replay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import IsolationLevel
from psycopg.rows import dict_row

from fdai.core.ontology_platform.inventory_projection import (
    DEFAULT_OBSERVED_STATE_FRESHNESS_CEILING_SECONDS,
)
from fdai.delivery.inventory_sync import (
    PromotedInventoryObservation,
    compute_relationship_coverage,
)
from fdai.delivery.persistence.postgres_inventory_projection_replay import (
    MAX_ACTIVE_PROJECTION_OBSERVATIONS,
    projection_replay_drops,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    _PROMOTION_LOCK,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.providers.inventory import LinkRecord, ResourceRecord
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

_IDENTITY_ONLY_MANIFEST_SCHEMA_VERSION = "1.1.0"


@dataclass(frozen=True, slots=True)
class _LegacyManifestEvidence:
    link_keys: frozenset[tuple[str, str, str]]
    manifest_digest: str


class PostgresInventorySnapshotReplayLoader:
    """Read the exact active snapshot without invoking a provider."""

    def __init__(self, *, config: PostgresInventorySnapshotStoreConfig) -> None:
        self._config = config

    async def load(self) -> PromotedInventoryObservation:
        """Return one bounded complete observation while holding the promotion read lock."""

        async with await self._connect() as connection:
            await connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
            await connection.set_read_only(True)
            await self._set_timeout(connection)
            await connection.execute("SELECT pg_advisory_xact_lock_shared(%s)", (_PROMOTION_LOCK,))
            snapshot_cursor = await connection.execute(
                "SELECT s.id, s.completed_at, s.metadata "
                "FROM inventory_active a JOIN inventory_snapshot s ON s.id=a.snapshot_id "
                "WHERE a.singleton=TRUE AND s.status='active'"
            )
            snapshot = await snapshot_cursor.fetchone()
            if snapshot is None or snapshot["completed_at"] is None:
                raise ValueError("active inventory snapshot is unavailable for journal bootstrap")
            generation = str(snapshot["id"])
            resources_cursor = await connection.execute(
                "SELECT resource_id, resource_type, props, provider_ref, last_seen "
                "FROM inventory_snapshot_resource WHERE snapshot_id=%s "
                "ORDER BY resource_id LIMIT %s",
                (generation, MAX_ACTIVE_PROJECTION_OBSERVATIONS + 1),
            )
            resources = await resources_cursor.fetchall()
            if len(resources) > MAX_ACTIVE_PROJECTION_OBSERVATIONS:
                raise ValueError("active inventory snapshot journal bootstrap exceeds its bound")
            remaining = MAX_ACTIVE_PROJECTION_OBSERVATIONS - len(resources)
            links_cursor = await connection.execute(
                "SELECT from_id, from_type, link_type, to_id, to_type, props "
                "FROM inventory_snapshot_link WHERE snapshot_id=%s "
                "ORDER BY link_type, from_id, to_id LIMIT %s",
                (generation, remaining + 1),
            )
            links = await links_cursor.fetchall()
            if len(links) > remaining:
                raise ValueError("active inventory snapshot journal bootstrap exceeds its bound")
            manifest_cursor = await connection.execute(
                "SELECT value FROM state_kv WHERE key='inventory-ontology:manifest'"
            )
            manifest_row = await manifest_cursor.fetchone()
        if manifest_row is None:
            raise ValueError("inventory projection replay manifest is unavailable")
        return build_active_snapshot_observation(
            snapshot=snapshot,
            resource_rows=resources,
            link_rows=links,
            prior_manifest=_mapping(manifest_row["value"]),
        )

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


def build_active_snapshot_observation(
    *,
    snapshot: Mapping[str, Any],
    resource_rows: Sequence[Mapping[str, Any]],
    link_rows: Sequence[Mapping[str, Any]],
    prior_manifest: Mapping[str, Any],
) -> PromotedInventoryObservation:
    """Rehydrate one verified active snapshot for the existing dual-write path."""

    generation = str(snapshot["id"])
    if prior_manifest.get("generation") != generation:
        raise ValueError("inventory projection replay manifest generation changed")
    metadata = _mapping(snapshot["metadata"])
    legacy_evidence = _legacy_manifest_evidence(
        generation=generation,
        metadata=metadata,
        prior_manifest=prior_manifest,
        resource_rows=resource_rows,
        link_rows=link_rows,
    )
    if legacy_evidence is None and metadata.get("projection_complete") is not True:
        raise ValueError("active inventory snapshot is incomplete for journal bootstrap")
    recorded_at = _timestamp(snapshot["completed_at"], "snapshot completed_at")
    resources = tuple(
        ResourceRecord(
            resource_id=str(row["resource_id"]),
            type=str(row["resource_type"]),
            props=_mapping(row["props"]),
            provider_ref=str(row["provider_ref"]) if row["provider_ref"] is not None else None,
            last_seen=(
                _timestamp(row["last_seen"], "resource last_seen").isoformat()
                if row["last_seen"] is not None
                else None
            ),
        )
        for row in resource_rows
    )
    links = tuple(
        _link_record(
            row,
            generation=generation,
            recorded_at=recorded_at,
            legacy_evidence=legacy_evidence,
        )
        for row in link_rows
    )
    observation = PromotedInventoryObservation(
        generation=generation,
        resources=resources,
        links=links,
        complete=True,
        relationship_drops=(
            () if legacy_evidence is not None else projection_replay_drops(metadata, prior_manifest)
        ),
        recorded_at=recorded_at,
    )
    if legacy_evidence is None:
        expected_coverage = _mapping(metadata.get("relationship_coverage"))
        actual_coverage = dict(compute_relationship_coverage(observation).to_metadata())
        if actual_coverage != dict(expected_coverage):
            raise ValueError("inventory snapshot journal bootstrap relationship coverage changed")
    return observation


def _link_record(
    row: Mapping[str, Any],
    *,
    generation: str,
    recorded_at: datetime,
    legacy_evidence: _LegacyManifestEvidence | None,
) -> LinkRecord:
    properties = dict(_mapping(row["props"]))
    raw_observation = properties.pop(LINK_OBSERVATION_METADATA_PROPERTY, None)
    properties.pop("provider_relationship_evidence", None)
    if isinstance(raw_observation, Mapping):
        observation_metadata = LinkObservationMetadata.from_mapping(raw_observation)
    elif raw_observation is not None or legacy_evidence is None:
        raise ValueError("inventory snapshot relationship has no observation metadata")
    else:
        key = (str(row["from_id"]), str(row["link_type"]), str(row["to_id"]))
        if key not in legacy_evidence.link_keys:
            raise ValueError("legacy inventory snapshot relationship is absent from its manifest")
        observation_metadata = _legacy_link_observation_metadata(
            row,
            generation=generation,
            recorded_at=recorded_at,
            manifest_digest=legacy_evidence.manifest_digest,
        )
    return LinkRecord(
        from_id=str(row["from_id"]),
        from_type=str(row["from_type"]),
        link_type=str(row["link_type"]),
        to_id=str(row["to_id"]),
        to_type=str(row["to_type"]),
        link_props=properties,
        observation_metadata=observation_metadata,
    )


def _legacy_manifest_evidence(
    *,
    generation: str,
    metadata: Mapping[str, Any],
    prior_manifest: Mapping[str, Any],
    resource_rows: Sequence[Mapping[str, Any]],
    link_rows: Sequence[Mapping[str, Any]],
) -> _LegacyManifestEvidence | None:
    if prior_manifest.get("schema_version") != _IDENTITY_ONLY_MANIFEST_SCHEMA_VERSION:
        return None
    if set(prior_manifest) != {
        "schema_version",
        "generation",
        "ontology_release_digest",
        "complete",
        "dropped_reasons",
        "object_ids",
        "link_keys",
    }:
        raise ValueError("legacy inventory projection manifest shape is invalid")
    if "projection_complete" in metadata or "relationship_coverage" in metadata:
        raise ValueError("legacy inventory snapshot metadata is mixed with current fields")
    provider_coverage = _mapping(metadata.get("provider_scope_coverage"))
    if provider_coverage.get("provider_identity_complete") is not True:
        raise ValueError("legacy inventory snapshot provider identity is incomplete")
    if (
        prior_manifest.get("generation") != generation
        or prior_manifest.get("complete") is not True
        or prior_manifest.get("dropped_reasons") != []
        or not _digest(prior_manifest.get("ontology_release_digest"))
    ):
        raise ValueError("legacy inventory projection manifest is incomplete")
    object_ids = _canonical_object_ids(prior_manifest.get("object_ids"))
    link_keys = _canonical_link_keys(prior_manifest.get("link_keys"))
    snapshot_object_ids = tuple(str(row["resource_id"]) for row in resource_rows)
    if snapshot_object_ids != object_ids:
        raise ValueError("legacy inventory snapshot object identities changed")
    snapshot_link_keys = {
        (str(row["from_id"]), str(row["link_type"]), str(row["to_id"])) for row in link_rows
    }
    if len(snapshot_link_keys) != len(link_rows) or not snapshot_link_keys.issubset(link_keys):
        raise ValueError("legacy inventory snapshot relationship identities changed")
    return _LegacyManifestEvidence(
        link_keys=frozenset(link_keys),
        manifest_digest=_canonical_digest(prior_manifest),
    )


def _legacy_link_observation_metadata(
    row: Mapping[str, Any],
    *,
    generation: str,
    recorded_at: datetime,
    manifest_digest: str,
) -> LinkObservationMetadata:
    from_type = str(row["from_type"])
    link_type = str(row["link_type"])
    to_type = str(row["to_type"])
    mapping_revision = _canonical_digest(
        {"from_type": from_type, "link_type": link_type, "to_type": to_type}
    )
    schema_revision = f"inventory-ontology-manifest/{_IDENTITY_ONLY_MANIFEST_SCHEMA_VERSION}"
    state_fact = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-snapshot",
        source_revision=generation,
        effective_at=recorded_at,
        recorded_at=recorded_at,
        evidence_cutoff=recorded_at,
        freshness_ceiling_seconds=DEFAULT_OBSERVED_STATE_FRESHNESS_CEILING_SECONDS,
        completeness=1.0,
        synthetic=False,
        evidence_refs=(
            f"inventory-generation:{generation}",
            f"inventory-ontology-manifest:{manifest_digest}",
        ),
    )
    return LinkObservationMetadata(
        state_fact=state_fact,
        verification_method="deterministic-cross-check",
        verified=True,
        verifier_identity="inventory-legacy-manifest-verifier",
        verifier_revision="legacy-manifest-cross-check/v1",
        verification_receipt_ref=f"inventory-ontology-manifest:{manifest_digest}",
        inventory_generation=generation,
        mapping_id=f"legacy-inventory-link:{link_type}",
        mapping_revision=mapping_revision,
        source_schema_version=schema_revision,
        source_schema_digest=_text_digest(schema_revision),
    )


def _canonical_object_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError("legacy inventory projection object identities are invalid")
    identities = tuple(value)
    if identities != tuple(sorted(set(identities))):
        raise ValueError("legacy inventory projection object identities are not canonical")
    return identities


def _canonical_link_keys(value: object) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(value, list):
        raise ValueError("legacy inventory projection relationship identities are invalid")
    identities = tuple(
        tuple(item)
        for item in value
        if isinstance(item, list)
        and len(item) == 3
        and all(isinstance(part, str) and part for part in item)
    )
    canonical = tuple(sorted(set(identities), key=lambda item: (item[1], item[0], item[2])))
    if len(identities) != len(value) or identities != canonical:
        raise ValueError("legacy inventory projection relationship identities are not canonical")
    return identities


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _text_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("inventory snapshot replay value MUST be an object")
    return value


def _timestamp(value: object, field: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"inventory snapshot replay {field} MUST be timezone-aware")
    return parsed.astimezone(UTC)


__all__ = ["PostgresInventorySnapshotReplayLoader", "build_active_snapshot_observation"]
