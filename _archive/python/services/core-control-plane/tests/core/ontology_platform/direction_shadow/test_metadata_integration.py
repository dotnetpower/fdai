"""Verified inventory-link metadata integration for direction shadow comparison."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.ontology_platform.direction_shadow import (
    ComparisonDisposition,
    DirectionGraphGeneration,
    DirectionGraphLink,
    RebuildPointer,
    compare_graph_generations,
)
from fdai.shared.providers.inventory import LinkRecord
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

PRIOR_RELEASE = "sha256:" + "e" * 64
ALIGNED_RELEASE = "sha256:" + "f" * 64
CUTOFF = datetime(2026, 8, 12, 1, tzinfo=UTC)


def _inventory_link(from_id: str, to_id: str, receipt_ref: str) -> LinkRecord:
    metadata = LinkObservationMetadata(
        state_fact=StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity="authoritative-inventory",
            source_revision="inventory-generation-42",
            effective_at=CUTOFF,
            recorded_at=CUTOFF,
            evidence_cutoff=CUTOFF,
            freshness_ceiling_seconds=300,
            completeness=1.0,
            synthetic=False,
            evidence_refs=(f"evidence:{receipt_ref}",),
        ),
        verification_method="provider-readback",
        verified=True,
        verifier_identity="independent-inventory-verifier",
        verifier_revision="verifier-7",
        verification_receipt_ref=receipt_ref,
    )
    return LinkRecord(
        from_id=from_id,
        from_type="Resource",
        link_type="contains",
        to_id=to_id,
        to_type="Resource",
        observation_metadata=metadata,
    )


def test_verified_link_observation_metadata_supports_complete_review_evidence() -> None:
    legacy_record = _inventory_link("child", "parent", "verification:legacy")
    aligned_record = _inventory_link("parent", "child", "verification:aligned")
    legacy = DirectionGraphGeneration.create(
        generation_ref="inventory-generation:legacy",
        ontology_release_digest=PRIOR_RELEASE,
        object_ids=("parent", "child"),
        links=(DirectionGraphLink.from_inventory_link(legacy_record),),
        complete=True,
    )
    aligned = DirectionGraphGeneration.create(
        generation_ref="inventory-generation:aligned",
        ontology_release_digest=ALIGNED_RELEASE,
        object_ids=("parent", "child"),
        links=(DirectionGraphLink.from_inventory_link(aligned_record),),
        complete=True,
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

    assert receipt.disposition is ComparisonDisposition.COMPLETE
    assert receipt.review_reasons == ()
    assert len(receipt.reversed_links) == 1
    assert receipt.rebuild_pointer.authoritative_generation_ref == ("inventory-generation:aligned")
    assert legacy_record.observation_metadata is not None
    assert legacy_record.observation_metadata.verified is True
