"""Focused unit tests for immutable direction graph comparison."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.ontology_platform.direction_shadow import (
    ComparisonBounds,
    ComparisonDisposition,
    DirectionGraphGeneration,
    DirectionGraphLink,
    RebuildPointer,
    compare_graph_generations,
    replay_matches,
)
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

PRIOR_RELEASE = "sha256:" + "a" * 64
ALIGNED_RELEASE = "sha256:" + "b" * 64
NOW = datetime(2026, 8, 12, tzinfo=UTC)


def _metadata(reference: str) -> LinkObservationMetadata:
    return LinkObservationMetadata(
        state_fact=StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity="inventory-source",
            source_revision="generation-1",
            effective_at=NOW,
            recorded_at=NOW,
            evidence_cutoff=NOW,
            freshness_ceiling_seconds=300,
            completeness=1.0,
            synthetic=False,
            evidence_refs=(f"evidence:{reference}",),
        ),
        verification_method="deterministic-cross-check",
        verified=True,
        verifier_identity="inventory-verifier",
        verifier_revision="verifier-1",
        verification_receipt_ref=f"receipt:{reference}",
    )


def _link(link_type: str, from_id: str, to_id: str) -> DirectionGraphLink:
    return DirectionGraphLink(
        link_type=link_type,
        from_id=from_id,
        to_id=to_id,
        observation_metadata=_metadata(f"{link_type}:{from_id}:{to_id}"),
    )


def _generation(
    name: str,
    release: str,
    links: tuple[DirectionGraphLink, ...],
) -> DirectionGraphGeneration:
    return DirectionGraphGeneration.create(
        generation_ref=name,
        ontology_release_digest=release,
        object_ids=("anchor", "child", "dependent", "parent", "prerequisite"),
        links=links,
        complete=True,
    )


def test_comparator_measures_directional_semantic_and_blast_radius_differences() -> None:
    legacy = _generation(
        "legacy-generation",
        PRIOR_RELEASE,
        (
            _link("contains", "child", "parent"),
            _link("attached_to", "anchor", "child"),
            _link("depends_on", "prerequisite", "dependent"),
        ),
    )
    aligned = _generation(
        "aligned-generation",
        ALIGNED_RELEASE,
        (
            _link("contains", "parent", "child"),
            _link("attached_to", "child", "anchor"),
            _link("depends_on", "dependent", "prerequisite"),
        ),
    )

    receipt = compare_graph_generations(
        legacy,
        aligned,
        migration_revision="20260808_0078",
        rebuild_pointer=RebuildPointer(
            authoritative_generation_ref="inventory-generation:aligned",
            rebuild_procedure_ref="runbook:ontology-current-state-rebuild:v1",
        ),
        bounds=ComparisonBounds(traversal_depth=3, blast_radius_depth=2),
    )

    assert receipt.disposition is ComparisonDisposition.COMPLETE
    assert receipt.added_links == ()
    assert receipt.removed_links == ()
    assert len(receipt.reversed_links) == 3
    assert {item.query for item in receipt.directional_query_deltas} == {
        "traversal:attached_to:incoming",
        "traversal:attached_to:outgoing",
        "traversal:contains:incoming",
        "traversal:contains:outgoing",
        "traversal:depends_on:incoming",
        "traversal:depends_on:outgoing",
    }
    assert receipt.contains_descendant_deltas
    assert receipt.attached_anchor_deltas
    assert receipt.depends_prerequisite_deltas
    assert receipt.blast_radius_deltas
    assert receipt.prior_release_digest == PRIOR_RELEASE
    assert receipt.aligned_release_digest == ALIGNED_RELEASE
    assert receipt.legacy_generation_digest == legacy.generation_digest
    assert receipt.aligned_generation_digest == aligned.generation_digest
    assert receipt.rebuild_pointer.restores_deleted_rows is False
    assert receipt.rebuild_pointer.strategy == (
        "rebuild_current_state_from_authoritative_inventory"
    )
    assert receipt.migration_ready is False
    assert receipt.graph_mutation_authority is False
    assert receipt.migration_execution_authority is False
    assert receipt.receipt_digest.startswith("sha256:")
    assert replay_matches(receipt, legacy, aligned) is True


def test_added_and_removed_links_are_not_misclassified_as_reversals() -> None:
    legacy = _generation(
        "legacy-add-remove",
        PRIOR_RELEASE,
        (
            _link("contains", "parent", "child"),
            _link("depends_on", "dependent", "prerequisite"),
        ),
    )
    aligned = _generation(
        "aligned-add-remove",
        ALIGNED_RELEASE,
        (
            _link("contains", "parent", "child"),
            _link("attached_to", "child", "anchor"),
        ),
    )

    receipt = compare_graph_generations(
        legacy,
        aligned,
        migration_revision="20260808_0078",
        rebuild_pointer=RebuildPointer(
            authoritative_generation_ref="inventory-generation:aligned",
            rebuild_procedure_ref="runbook:ontology-current-state-rebuild:v1",
        ),
    )

    assert [(item.link_type, item.from_id, item.to_id) for item in receipt.added_links] == [
        ("attached_to", "child", "anchor")
    ]
    assert [(item.link_type, item.from_id, item.to_id) for item in receipt.removed_links] == [
        ("depends_on", "dependent", "prerequisite")
    ]
    assert receipt.reversed_links == ()
