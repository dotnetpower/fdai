"""Resolve exact inventory source coverage for ontology graph reads."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import psycopg

from fdai.shared.providers.ontology_instance import OntologyObjectRecord


async def resource_graph_source_coverage(
    connection: psycopg.AsyncConnection[Any],
    objects: Sequence[OntologyObjectRecord],
    *,
    requires_resource_coverage: bool = False,
    expresses_relationships: bool = True,
) -> tuple[bool, str | None]:
    """Read exact inventory projection coverage for snapshots containing Resources."""

    if not requires_resource_coverage and not any(
        record.object_type == "Resource" for record in objects
    ):
        return True, None
    cursor = await connection.execute(
        "SELECT active.snapshot_id, status.value AS status_value, "
        "manifest.value AS manifest_value, "
        "observation_watermarks.value AS observation_watermarks_value, "
        "storage_pressure.value AS storage_pressure_value, "
        "EXISTS (SELECT 1 FROM inventory_observation_partition AS correction "
        "WHERE correction.scope_ref IN ("
        "SELECT value FROM jsonb_array_elements_text(snapshot.scopes)) "
        "AND correction.state='correction_pending') AS pending_correction, "
        "EXISTS (SELECT 1 FROM jsonb_array_elements_text(snapshot.scopes) "
        "AS active_scope(scope) JOIN state_kv AS marker ON "
        "marker.key = 'inventory-relationship-reconciliation:' || active_scope.scope) "
        "AS pending_reconciliation "
        "FROM inventory_active AS active "
        "JOIN inventory_snapshot AS snapshot ON snapshot.id=active.snapshot_id "
        "LEFT JOIN state_kv AS status ON status.key='inventory-ontology:status' "
        "LEFT JOIN state_kv AS manifest ON manifest.key='inventory-ontology:manifest' "
        "LEFT JOIN state_kv AS observation_watermarks "
        "ON observation_watermarks.key='inventory-observation:watermarks' "
        "LEFT JOIN state_kv AS storage_pressure "
        "ON storage_pressure.key='operational-history:storage-pressure' "
        "WHERE active.singleton=TRUE"
    )
    row = await cursor.fetchone()
    if row is None:
        return False, None
    status = _json_mapping(row.get("status_value"))
    manifest = _json_mapping(row.get("manifest_value"))
    observation_watermarks_value = row.get("observation_watermarks_value")
    observation_watermarks = _json_mapping(observation_watermarks_value)
    storage_pressure = _json_mapping(row.get("storage_pressure_value"))
    return resolve_inventory_graph_source_coverage(
        active_generation=row.get("snapshot_id"),
        status=status,
        manifest=manifest,
        expresses_relationships=expresses_relationships,
        pending_reconciliation=bool(row.get("pending_reconciliation")),
        journal_high_watermark=observation_watermarks.get("journal_high_watermark"),
        ontology_projection_watermark=observation_watermarks.get("ontology_projection_watermark"),
        pending_tombstones=observation_watermarks.get("pending_tombstones"),
        observation_watermark_state_present=observation_watermarks_value is not None,
        pending_correction=bool(row.get("pending_correction")),
        storage_pressure_hard=storage_pressure.get("hold_completeness_dependent_work") is True,
    )


def resolve_inventory_graph_source_coverage(
    *,
    active_generation: object,
    status: Mapping[str, Any],
    manifest: Mapping[str, Any],
    expresses_relationships: bool = True,
    pending_reconciliation: bool = False,
    journal_high_watermark: object = None,
    ontology_projection_watermark: object = None,
    pending_tombstones: object = None,
    observation_watermark_state_present: bool = False,
    pending_correction: bool = False,
    storage_pressure_hard: bool = False,
) -> tuple[bool, str | None]:
    """Reduce inventory projection state to exact graph generation and completeness."""

    manifest_generation = manifest.get("generation")
    source_generation = manifest_generation if isinstance(manifest_generation, str) else None
    watermark_incomplete = _observation_watermarks_incomplete(
        journal_high_watermark,
        ontology_projection_watermark,
        pending_tombstones,
        state_present=observation_watermark_state_present,
    )
    if (
        watermark_incomplete
        or pending_correction
        or storage_pressure_hard
        or (pending_reconciliation and expresses_relationships)
        or (
            not isinstance(active_generation, str)
            or source_generation is None
            or status.get("status") != "available"
            or status.get("generation") != active_generation
            or ("complete" in status and status.get("complete") is not True)
            or source_generation != active_generation
            or manifest.get("complete") is not True
            or (
                "manifest_digest" in manifest
                and (
                    not isinstance(manifest.get("manifest_digest"), str)
                    or manifest.get("manifest_digest") != status.get("manifest_digest")
                )
            )
            or (
                "ontology_release_digest" in manifest
                and manifest.get("ontology_release_digest") != status.get("ontology_release_digest")
            )
        )
    ):
        return False, source_generation
    # Relationship coverage bounds relationship claims. A snapshot whose object set admits
    # no intra-set edge states nothing about relationships, so classified non-edges
    # elsewhere in the generation cannot make its object evidence incomplete.
    if not expresses_relationships:
        return True, source_generation
    relationship_complete = manifest.get("relationship_complete")
    if relationship_complete is None:
        dropped = manifest.get("dropped_reasons")
        return isinstance(dropped, list) and not dropped, source_generation
    return relationship_complete is True, source_generation


def _json_mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, Mapping) else {}


def _observation_watermarks_incomplete(
    journal_high_watermark: object,
    ontology_projection_watermark: object,
    pending_tombstones: object,
    *,
    state_present: bool,
) -> bool:
    if (
        journal_high_watermark is None
        and ontology_projection_watermark is None
        and pending_tombstones is None
    ):
        return state_present
    if (
        not isinstance(journal_high_watermark, int)
        or isinstance(journal_high_watermark, bool)
        or journal_high_watermark < 0
        or not isinstance(ontology_projection_watermark, int)
        or isinstance(ontology_projection_watermark, bool)
        or ontology_projection_watermark < 0
        or not isinstance(pending_tombstones, int)
        or isinstance(pending_tombstones, bool)
        or pending_tombstones < 0
    ):
        return True
    return journal_high_watermark > ontology_projection_watermark or pending_tombstones > 0
