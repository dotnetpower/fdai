"""Inventory-promotion publishing into retained topology history."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.inventory_topology_history import InventoryTopologyHistoryPublisher
from fdai.shared.providers.inventory import LinkRecord, ResourceRecord
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

RECORDED_AT = datetime(2026, 8, 13, 1, tzinfo=UTC)
RELEASE_DIGEST = "sha256:" + ("a" * 64)


def _observation_metadata() -> LinkObservationMetadata:
    return LinkObservationMetadata(
        state_fact=StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity="inventory-provider",
            source_revision="revision-1",
            effective_at=RECORDED_AT,
            evidence_cutoff=RECORDED_AT,
            recorded_at=RECORDED_AT,
            freshness_ceiling_seconds=300,
            completeness=1.0,
            synthetic=False,
            evidence_refs=("inventory-receipt-1",),
        ),
        verification_method="provider-readback",
        verified=True,
        verifier_identity="inventory-readback",
        verifier_revision="revision-1",
        verification_receipt_ref="verification-receipt-1",
        inventory_generation="snapshot-1",
        mapping_id="test.mapping",
        mapping_revision="sha256:" + ("1" * 64),
        source_schema_version="test-schema-v1",
        source_schema_digest="sha256:" + ("2" * 64),
    )


class _Writer:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, str]] = []

    async def append(
        self,
        batch: object,
        *,
        ontology_release_digest: str,
        source_receipt_digest: str,
    ) -> None:
        self.calls.append((batch, ontology_release_digest, source_receipt_digest))


async def test_complete_promotion_publishes_one_retained_topology_baseline() -> None:
    writer = _Writer()
    publisher = InventoryTopologyHistoryPublisher(
        writer=writer,
        ontology_release_digest=RELEASE_DIGEST,
    )

    batch = await publisher.publish(
        PromotedInventoryObservation(
            generation="snapshot-1",
            resources=(
                ResourceRecord(
                    resource_id="vm-1",
                    type="compute.vm",
                    props={"name": "vm-1"},
                ),
                ResourceRecord(resource_id="disk-1", type="storage.disk"),
            ),
            links=(
                LinkRecord(
                    from_id="vm-1",
                    from_type="compute.vm",
                    link_type="attached_to",
                    to_id="disk-1",
                    to_type="storage.disk",
                    observation_metadata=_observation_metadata(),
                ),
            ),
            complete=True,
            recorded_at=RECORDED_AT,
        )
    )

    assert batch is not None
    assert batch.provider_generation_ref == "snapshot-1"
    assert batch.effective_at == RECORDED_AT
    assert batch.recorded_at == RECORDED_AT
    assert batch.complete_snapshot is True
    assert [item.object_id for item in batch.object_revisions] == ["disk-1", "vm-1"]
    assert batch.object_revisions[0].evidence_ref == "inventory-generation:snapshot-1"
    assert batch.link_revisions[0].from_type == "Resource"
    assert batch.link_revisions[0].to_type == "Resource"
    assert writer.calls[0][0:2] == (batch, RELEASE_DIGEST)
    assert writer.calls[0][2].startswith("sha256:")


async def test_incomplete_promotion_does_not_publish_partial_history() -> None:
    writer = _Writer()
    publisher = InventoryTopologyHistoryPublisher(
        writer=writer,
        ontology_release_digest=RELEASE_DIGEST,
    )

    result = await publisher.publish(
        PromotedInventoryObservation(
            generation="snapshot-truncated",
            resources=(),
            links=(),
            complete=False,
            recorded_at=RECORDED_AT,
        )
    )

    assert result is None
    assert writer.calls == []


async def test_same_promotion_has_one_deterministic_revision_identity() -> None:
    writer = _Writer()
    publisher = InventoryTopologyHistoryPublisher(
        writer=writer,
        ontology_release_digest=RELEASE_DIGEST,
    )
    observation = PromotedInventoryObservation(
        generation="snapshot-1",
        resources=(ResourceRecord(resource_id="vm-1", type="compute.vm"),),
        links=(),
        complete=True,
        recorded_at=RECORDED_AT,
    )

    first = await publisher.publish(observation)
    second = await publisher.publish(observation)

    assert first is not None
    assert second is not None
    assert first.revision_id == second.revision_id
    assert writer.calls[0][2] == writer.calls[1][2]
