"""Inventory-promotion publishing into retained topology history."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.state_transitions import StateTransitionBatch
from fdai.core.ontology_platform.topology_history import (
    TopologyObjectRevision,
    TopologyRevisionBatch,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.inventory_topology_history import InventoryTopologyHistoryPublisher
from fdai.shared.providers.inventory import (
    LinkRecord,
    RelationshipDrop,
    RelationshipDropReason,
    ResourceRecord,
)
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

RECORDED_AT = datetime(2026, 8, 13, 1, tzinfo=UTC)
RELEASE_DIGEST = "sha256:" + ("a" * 64)


def _state_properties_json(
    state: str,
    *,
    at: datetime,
    generation: str,
) -> str:
    metadata = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision=generation,
        effective_at=at,
        recorded_at=at,
        evidence_cutoff=at,
        freshness_ceiling_seconds=600,
        completeness=1.0,
        synthetic=False,
        evidence_refs=(f"inventory-generation:{generation}",),
    )
    return json.dumps(
        {
            "properties": {
                "state": state,
                "state_fact_metadata": metadata.to_mapping(),
            }
        },
        sort_keys=True,
        separators=(",", ":"),
    )


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


class _HistoryReader:
    def __init__(self, batches: tuple[TopologyRevisionBatch, ...]) -> None:
        self.batches = batches

    async def read(
        self,
        *,
        as_of: datetime,
        known_at: datetime,
    ) -> tuple[TopologyRevisionBatch, ...]:
        assert as_of == known_at == RECORDED_AT
        return self.batches


class _TransitionWriter:
    def __init__(self) -> None:
        self.batches: list[StateTransitionBatch] = []

    async def append(self, batch: StateTransitionBatch) -> bool:
        self.batches.append(batch)
        return True


class _FailingTransitionWriter:
    async def append(self, batch: StateTransitionBatch) -> bool:
        del batch
        raise RuntimeError("transition store unavailable")


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


async def test_relationship_gap_withholds_complete_history_baseline() -> None:
    writer = _Writer()
    publisher = InventoryTopologyHistoryPublisher(
        writer=writer,
        ontology_release_digest=RELEASE_DIGEST,
    )

    result = await publisher.publish(
        PromotedInventoryObservation(
            generation="snapshot-partial-links",
            resources=(ResourceRecord(resource_id="vm-1", type="compute.vm"),),
            links=(),
            complete=True,
            relationship_drops=(
                # The source observed a candidate but not its endpoint.
                # It must not become a complete replay baseline.
                RelationshipDrop(reason=RelationshipDropReason.MISSING_TARGET_ENDPOINT),
            ),
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


async def test_inventory_state_change_appends_transition_without_claiming_interval_coverage() -> (
    None
):
    previous_at = RECORDED_AT - timedelta(minutes=10)
    previous = TopologyRevisionBatch(
        revision_id="previous",
        provider_generation_ref="snapshot-0",
        effective_at=previous_at,
        recorded_at=previous_at,
        complete_snapshot=True,
        object_revisions=(
            TopologyObjectRevision(
                object_id="vm-1",
                object_type="Resource",
                properties_json=_state_properties_json(
                    "running",
                    at=previous_at,
                    generation="snapshot-0",
                ),
                effective_at=previous_at,
                recorded_at=previous_at,
                deleted=False,
                evidence_ref="inventory-generation:snapshot-0",
            ),
        ),
    )
    current = TopologyRevisionBatch(
        revision_id="current-retry",
        provider_generation_ref="snapshot-1",
        effective_at=RECORDED_AT,
        recorded_at=RECORDED_AT,
        complete_snapshot=True,
        object_revisions=(
            TopologyObjectRevision(
                object_id="vm-1",
                object_type="Resource",
                properties_json=_state_properties_json(
                    "deallocated",
                    at=RECORDED_AT,
                    generation="snapshot-1",
                ),
                effective_at=RECORDED_AT,
                recorded_at=RECORDED_AT,
                deleted=False,
                evidence_ref="inventory-generation:snapshot-1",
            ),
        ),
    )
    transition_writer = _TransitionWriter()
    publisher = InventoryTopologyHistoryPublisher(
        writer=_Writer(),
        ontology_release_digest=RELEASE_DIGEST,
        history_reader=_HistoryReader((previous,)),
        transition_writer=transition_writer,
    )

    await publisher.publish(
        PromotedInventoryObservation(
            generation="snapshot-1",
            resources=(
                ResourceRecord(
                    resource_id="vm-1",
                    type="compute.vm",
                    props={"status": "PowerState/deallocated"},
                    last_seen=RECORDED_AT.isoformat(),
                ),
            ),
            links=(),
            complete=True,
            recorded_at=RECORDED_AT,
        )
    )

    assert len(transition_writer.batches) == 1
    batch = transition_writer.batches[0]
    assert len(batch.transitions) == 1
    transition = batch.transitions[0]
    assert (transition.from_state, transition.to_state) == ("running", "deallocated")
    assert transition.state_type == "resource.operational_state"
    assert batch.coverage[0].complete is False
    assert batch.coverage[0].limitation == "snapshot_interval_only"

    retry_transitions = _TransitionWriter()
    retry_writer = _Writer()
    retry_publisher = InventoryTopologyHistoryPublisher(
        writer=retry_writer,
        ontology_release_digest=RELEASE_DIGEST,
        history_reader=_HistoryReader((current,)),
        transition_writer=retry_transitions,
    )
    await retry_publisher.publish(
        PromotedInventoryObservation(
            generation="snapshot-1",
            resources=(
                ResourceRecord(
                    resource_id="vm-1",
                    type="compute.vm",
                    props={"status": "PowerState/deallocated"},
                    last_seen=RECORDED_AT.isoformat(),
                ),
            ),
            links=(),
            complete=True,
            recorded_at=RECORDED_AT,
        )
    )

    assert retry_transitions.batches == []
    assert len(retry_writer.calls) == 1


async def test_transition_failure_prevents_topology_history_from_advancing() -> None:
    previous_at = RECORDED_AT - timedelta(minutes=10)
    previous = TopologyRevisionBatch(
        revision_id="previous",
        provider_generation_ref="snapshot-0",
        effective_at=previous_at,
        recorded_at=previous_at,
        complete_snapshot=True,
        object_revisions=(
            TopologyObjectRevision(
                object_id="vm-1",
                object_type="Resource",
                properties_json=_state_properties_json(
                    "PowerState/running",
                    at=previous_at,
                    generation="snapshot-0",
                ),
                effective_at=previous_at,
                recorded_at=previous_at,
                deleted=False,
                evidence_ref="inventory-generation:snapshot-0",
            ),
        ),
    )
    writer = _Writer()
    publisher = InventoryTopologyHistoryPublisher(
        writer=writer,
        ontology_release_digest=RELEASE_DIGEST,
        history_reader=_HistoryReader((previous,)),
        transition_writer=_FailingTransitionWriter(),
    )

    with pytest.raises(RuntimeError, match="transition store unavailable"):
        await publisher.publish(
            PromotedInventoryObservation(
                generation="snapshot-1",
                resources=(
                    ResourceRecord(
                        resource_id="vm-1",
                        type="compute.vm",
                        props={"status": "PowerState/deallocated"},
                        last_seen=RECORDED_AT.isoformat(),
                    ),
                ),
                links=(),
                complete=True,
                recorded_at=RECORDED_AT,
            )
        )

    assert writer.calls == []


async def test_large_inventory_transition_set_is_written_in_bounded_batches() -> None:
    previous_at = RECORDED_AT - timedelta(minutes=10)
    resource_ids = tuple(f"vm-{index:04d}" for index in range(513))
    previous = TopologyRevisionBatch(
        revision_id="previous-large",
        provider_generation_ref="snapshot-large-0",
        effective_at=previous_at,
        recorded_at=previous_at,
        complete_snapshot=True,
        object_revisions=tuple(
            TopologyObjectRevision(
                object_id=resource_id,
                object_type="Resource",
                properties_json=_state_properties_json(
                    "PowerState/running",
                    at=previous_at,
                    generation="snapshot-large-0",
                ),
                effective_at=previous_at,
                recorded_at=previous_at,
                deleted=False,
                evidence_ref="inventory-generation:snapshot-large-0",
            )
            for resource_id in resource_ids
        ),
    )
    transition_writer = _TransitionWriter()
    publisher = InventoryTopologyHistoryPublisher(
        writer=_Writer(),
        ontology_release_digest=RELEASE_DIGEST,
        history_reader=_HistoryReader((previous,)),
        transition_writer=transition_writer,
    )

    await publisher.publish(
        PromotedInventoryObservation(
            generation="snapshot-large-1",
            resources=tuple(
                ResourceRecord(
                    resource_id=resource_id,
                    type="compute.vm",
                    props={"status": "PowerState/deallocated"},
                    last_seen=RECORDED_AT.isoformat(),
                )
                for resource_id in resource_ids
            ),
            links=(),
            complete=True,
            recorded_at=RECORDED_AT,
        )
    )

    assert [len(batch.transitions) for batch in transition_writer.batches] == [512, 1]
    assert [len(batch.coverage) for batch in transition_writer.batches] == [512, 1]
