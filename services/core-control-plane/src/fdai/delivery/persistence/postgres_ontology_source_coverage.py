"""Resolve exact inventory source coverage for ontology graph reads."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import psycopg

from fdai.delivery.inventory_sync import INVENTORY_ACTIVE_SCOPE_CHECKPOINT_KEY
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

# Typed reasons, in reporting order, for a graph read that cannot claim source completeness.
PROJECTION_UNAVAILABLE = "inventory_projection_unavailable"
GENERATION_TRANSITION = "inventory_generation_transition"
PROJECTION_INCOMPLETE = "inventory_projection_incomplete"
PROJECTION_INCONSISTENT = "inventory_projection_inconsistent"
STORAGE_PRESSURE = "inventory_storage_pressure"
CORRECTION_PENDING = "inventory_correction_pending"
OBSERVATION_PENDING = "inventory_observation_pending"
RELATIONSHIP_RECONCILIATION_PENDING = "inventory_relationship_reconciliation_pending"
RELATIONSHIP_INCOMPLETE = "inventory_relationship_incomplete"


@dataclass(frozen=True, slots=True)
class InventoryGraphSourceCoverage:
    """Graph source completeness, its exact generation, and why it is incomplete."""

    complete: bool
    generation: str | None
    reason: str | None = None


async def resource_graph_source_coverage(
    connection: psycopg.AsyncConnection[Any],
    objects: Sequence[OntologyObjectRecord],
    *,
    requires_resource_coverage: bool = False,
    expresses_relationships: bool = True,
) -> tuple[bool, str | None]:
    """Read exact inventory projection coverage for snapshots containing Resources."""

    coverage = await resource_graph_source_coverage_detail(
        connection,
        objects,
        requires_resource_coverage=requires_resource_coverage,
        expresses_relationships=expresses_relationships,
    )
    return coverage.complete, coverage.generation


async def resource_graph_source_coverage_detail(
    connection: psycopg.AsyncConnection[Any],
    objects: Sequence[OntologyObjectRecord],
    *,
    requires_resource_coverage: bool = False,
    expresses_relationships: bool = True,
) -> InventoryGraphSourceCoverage:
    """Read inventory projection coverage and keep the typed incompleteness reason."""

    if not requires_resource_coverage and not any(
        record.object_type == "Resource" for record in objects
    ):
        return InventoryGraphSourceCoverage(complete=True, generation=None)
    cursor = await connection.execute(
        "SELECT active.snapshot_id, status.value AS status_value, "
        "manifest.value AS manifest_value, "
        "observation_watermarks.value AS observation_watermarks_value, "
        "storage_pressure.value AS storage_pressure_value, "
        "EXISTS (SELECT 1 FROM jsonb_array_elements_text(snapshot.scopes) "
        "AS correction_scope(scope) JOIN inventory_observation_partition AS correction "
        "ON correction.scope_ref=correction_scope.scope "
        "WHERE correction.state='correction_pending' "
        "AND (snapshot.metadata->>'coverage_scope' IS DISTINCT FROM 'full_provider_scope' "
        "OR correction.last_watermark>COALESCE("
        "(manifest.value->>'journal_high_watermark')::bigint, 0))) AS pending_correction, "
        "EXISTS (SELECT 1 FROM jsonb_array_elements_text(snapshot.scopes) "
        "AS active_scope(scope) JOIN state_kv AS marker ON "
        "marker.key = 'inventory-relationship-reconciliation:' || active_scope.scope) "
        "AS pending_reconciliation, "
        "EXISTS (SELECT 1 FROM jsonb_array_elements_text(snapshot.scopes) "
        "AS pending_scope(scope) JOIN inventory_observation_journal AS pending "
        "ON pending.scope_ref=pending_scope.scope "
        "WHERE pending.watermark>CASE WHEN "
        "active_checkpoint.value->>'generation'=active.snapshot_id "
        "AND active_checkpoint.value->'scope_refs'=snapshot.scopes "
        "THEN COALESCE((active_checkpoint.value->>'projection_high_watermark')::bigint, 0) "
        "ELSE COALESCE("
        "(observation_watermarks.value->>'ontology_projection_watermark')::bigint, 0) END "
        "AND NOT (pending.source_revision=active.snapshot_id "
        "OR pending.effective_at<=snapshot.started_at)) AS pending_active_observation "
        "FROM inventory_active AS active "
        "JOIN inventory_snapshot AS snapshot ON snapshot.id=active.snapshot_id "
        "LEFT JOIN state_kv AS status ON status.key='inventory-ontology:status' "
        "LEFT JOIN state_kv AS manifest ON manifest.key='inventory-ontology:manifest' "
        "LEFT JOIN state_kv AS observation_watermarks "
        "ON observation_watermarks.key='inventory-observation:watermarks' "
        "LEFT JOIN state_kv AS active_checkpoint "
        "ON active_checkpoint.key=%s "
        "LEFT JOIN state_kv AS storage_pressure "
        "ON storage_pressure.key='operational-history:storage-pressure' "
        "WHERE active.singleton=TRUE",
        (INVENTORY_ACTIVE_SCOPE_CHECKPOINT_KEY,),
    )
    row = await cursor.fetchone()
    if row is None:
        return InventoryGraphSourceCoverage(
            complete=False,
            generation=None,
            reason=PROJECTION_UNAVAILABLE,
        )
    status = _json_mapping(row.get("status_value"))
    manifest = _json_mapping(row.get("manifest_value"))
    observation_watermarks_value = row.get("observation_watermarks_value")
    observation_watermarks = _json_mapping(observation_watermarks_value)
    storage_pressure = _json_mapping(row.get("storage_pressure_value"))
    return inventory_graph_source_coverage_detail(
        active_generation=row.get("snapshot_id"),
        status=status,
        manifest=manifest,
        expresses_relationships=expresses_relationships,
        pending_reconciliation=bool(row.get("pending_reconciliation")),
        pending_observation=bool(row.get("pending_active_observation")),
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
    pending_observation: bool | None = None,
    journal_high_watermark: object = None,
    ontology_projection_watermark: object = None,
    pending_tombstones: object = None,
    observation_watermark_state_present: bool = False,
    pending_correction: bool = False,
    storage_pressure_hard: bool = False,
) -> tuple[bool, str | None]:
    """Reduce inventory projection state to exact graph generation and completeness."""

    coverage = inventory_graph_source_coverage_detail(
        active_generation=active_generation,
        status=status,
        manifest=manifest,
        expresses_relationships=expresses_relationships,
        pending_reconciliation=pending_reconciliation,
        pending_observation=pending_observation,
        journal_high_watermark=journal_high_watermark,
        ontology_projection_watermark=ontology_projection_watermark,
        pending_tombstones=pending_tombstones,
        observation_watermark_state_present=observation_watermark_state_present,
        pending_correction=pending_correction,
        storage_pressure_hard=storage_pressure_hard,
    )
    return coverage.complete, coverage.generation


def inventory_graph_source_coverage_detail(
    *,
    active_generation: object,
    status: Mapping[str, Any],
    manifest: Mapping[str, Any],
    expresses_relationships: bool = True,
    pending_reconciliation: bool = False,
    pending_observation: bool | None = None,
    journal_high_watermark: object = None,
    ontology_projection_watermark: object = None,
    pending_tombstones: object = None,
    observation_watermark_state_present: bool = False,
    pending_correction: bool = False,
    storage_pressure_hard: bool = False,
) -> InventoryGraphSourceCoverage:
    """Reduce inventory projection state to completeness plus every typed gap reason."""

    manifest_generation = manifest.get("generation")
    source_generation = manifest_generation if isinstance(manifest_generation, str) else None
    watermark_incomplete = (
        pending_observation
        if pending_observation is not None
        else _observation_watermarks_incomplete(
            journal_high_watermark,
            ontology_projection_watermark,
            pending_tombstones,
            state_present=observation_watermark_state_present,
        )
    )
    reasons: list[str] = []
    if (
        not isinstance(active_generation, str)
        or source_generation is None
        or status.get("status") != "available"
    ):
        reasons.append(PROJECTION_UNAVAILABLE)
    if isinstance(active_generation, str) and (
        status.get("generation") != active_generation
        or (source_generation is not None and source_generation != active_generation)
    ):
        reasons.append(GENERATION_TRANSITION)
    if ("complete" in status and status.get("complete") is not True) or manifest.get(
        "complete"
    ) is not True:
        reasons.append(PROJECTION_INCOMPLETE)
    if (
        "manifest_digest" in manifest
        and (
            not isinstance(manifest.get("manifest_digest"), str)
            or manifest.get("manifest_digest") != status.get("manifest_digest")
        )
    ) or (
        "ontology_release_digest" in manifest
        and manifest.get("ontology_release_digest") != status.get("ontology_release_digest")
    ):
        reasons.append(PROJECTION_INCONSISTENT)
    if storage_pressure_hard:
        reasons.append(STORAGE_PRESSURE)
    if pending_correction:
        reasons.append(CORRECTION_PENDING)
    if watermark_incomplete:
        reasons.append(OBSERVATION_PENDING)
    if pending_reconciliation and expresses_relationships:
        reasons.append(RELATIONSHIP_RECONCILIATION_PENDING)
    if reasons:
        return _incomplete(source_generation, reasons)
    # Relationship coverage bounds relationship claims. A snapshot whose object set admits
    # no intra-set edge states nothing about relationships, so classified non-edges
    # elsewhere in the generation cannot make its object evidence incomplete.
    if not expresses_relationships:
        return InventoryGraphSourceCoverage(complete=True, generation=source_generation)
    relationship_complete = manifest.get("relationship_complete")
    if relationship_complete is None:
        dropped = manifest.get("dropped_reasons")
        relationships_verified = isinstance(dropped, list) and not dropped
    else:
        relationships_verified = relationship_complete is True
    if not relationships_verified:
        return _incomplete(source_generation, [RELATIONSHIP_INCOMPLETE])
    return InventoryGraphSourceCoverage(complete=True, generation=source_generation)


def _incomplete(generation: str | None, reasons: Sequence[str]) -> InventoryGraphSourceCoverage:
    return InventoryGraphSourceCoverage(
        complete=False,
        generation=generation,
        reason="+".join(dict.fromkeys(reasons)),
    )


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
