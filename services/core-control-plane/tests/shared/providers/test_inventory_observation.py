"""Normalized inventory observation and deterministic replay tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.shared.providers.inventory_observation import (
    InventoryMutationKind,
    InventoryObservationKind,
    InventoryObservationSubjectKind,
    NormalizedInventoryObservation,
    replay_object_observations,
)

NOW = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)


def _object_observation(
    *,
    event_id: str,
    seconds: int,
    kind: InventoryObservationKind,
    properties: dict[str, object],
    confirmed: bool = False,
) -> NormalizedInventoryObservation:
    timestamp = NOW + timedelta(seconds=seconds)
    return NormalizedInventoryObservation.create(
        idempotency_key=f"event:{event_id}",
        subject_kind=InventoryObservationSubjectKind.OBJECT,
        observation_kind=kind,
        mutation_kind=(
            InventoryMutationKind.DELETE
            if kind is InventoryObservationKind.TOMBSTONE
            else InventoryMutationKind.UPSERT
        ),
        subject_ref="resource-1",
        subject_type="compute.vm",
        properties=properties,
        property_mask=tuple(properties),
        properties_complete=kind is InventoryObservationKind.FULL,
        links_complete=False,
        tombstone_confirmed=confirmed,
        operation="Microsoft.Compute/virtualMachines/write",
        operation_status="Succeeded",
        source_identity="test.inventory",
        source_event_id=event_id,
        source_revision=f"revision:{event_id}",
        effective_at=timestamp,
        observed_at=timestamp,
        evidence_cutoff=timestamp,
        recorded_at=NOW + timedelta(minutes=1),
    )


def test_sparse_observations_preserve_tags_sku_and_unobserved_properties() -> None:
    hint = _object_observation(
        event_id="hint",
        seconds=1,
        kind=InventoryObservationKind.CHANGE_HINT,
        properties={},
    )
    partial = _object_observation(
        event_id="partial",
        seconds=2,
        kind=InventoryObservationKind.PARTIAL,
        properties={"power_state": "running"},
    )

    replay = replay_object_observations(
        (hint, partial),
        resource_type="compute.vm",
        baseline_properties={
            "tags": {"environment": "example"},
            "sku": {"name": "Standard_D2s_v5"},
            "location": "example-region",
        },
        baseline_provider_ref="/subscriptions/example/resourceGroups/example/providers/example",
    )

    assert replay.properties == {
        "location": "example-region",
        "power_state": "running",
        "sku": {"name": "Standard_D2s_v5"},
        "tags": {"environment": "example"},
    }
    assert "operation_status" not in replay.properties


def test_duplicate_reorder_and_restart_replay_produce_one_digest() -> None:
    older = _object_observation(
        event_id="older",
        seconds=1,
        kind=InventoryObservationKind.PARTIAL,
        properties={"tags": {"environment": "example"}},
    )
    newer = _object_observation(
        event_id="newer",
        seconds=2,
        kind=InventoryObservationKind.PARTIAL,
        properties={"sku": {"name": "Standard_D2s_v5"}},
    )
    baseline = {"location": "example-region"}

    expected = replay_object_observations(
        (older, newer),
        resource_type="compute.vm",
        baseline_properties=baseline,
        baseline_provider_ref=None,
    )
    reordered = replay_object_observations(
        (newer, older, newer, older),
        resource_type="compute.vm",
        baseline_properties=baseline,
        baseline_provider_ref=None,
    )
    restarted = replay_object_observations(
        tuple(reversed((newer, older))),
        resource_type="compute.vm",
        baseline_properties=baseline,
        baseline_provider_ref=None,
    )

    assert expected.digest == reordered.digest == restarted.digest
    assert expected.properties == reordered.properties == restarted.properties


def test_partial_property_mask_cannot_change_unmasked_values() -> None:
    observation = _object_observation(
        event_id="masked",
        seconds=1,
        kind=InventoryObservationKind.PARTIAL,
        properties={"tags": {"owner": "example-team"}},
    )

    replay = replay_object_observations(
        (observation,),
        resource_type="compute.vm",
        baseline_properties={"tags": {"owner": "old"}, "sku": "stable"},
        baseline_provider_ref=None,
    )

    assert replay.properties == {
        "tags": {"owner": "example-team"},
        "sku": "stable",
    }


def test_tombstone_candidate_does_not_claim_absence_before_confirmation() -> None:
    candidate = _object_observation(
        event_id="delete-candidate",
        seconds=1,
        kind=InventoryObservationKind.TOMBSTONE,
        properties={},
    )
    confirmed = _object_observation(
        event_id="delete-confirmed",
        seconds=2,
        kind=InventoryObservationKind.TOMBSTONE,
        properties={},
        confirmed=True,
    )

    pending = replay_object_observations(
        (candidate,),
        resource_type="compute.vm",
        baseline_properties={"status": "running"},
        baseline_provider_ref=None,
    )
    deleted = replay_object_observations(
        (candidate, confirmed),
        resource_type="compute.vm",
        baseline_properties={"status": "running"},
        baseline_provider_ref=None,
    )

    assert pending.present is True
    assert pending.properties == {"status": "running"}
    assert deleted.present is False


def test_property_mask_must_equal_observed_properties() -> None:
    with pytest.raises(ValueError, match="property_mask MUST match"):
        NormalizedInventoryObservation.create(
            idempotency_key="event:invalid",
            subject_kind=InventoryObservationSubjectKind.OBJECT,
            observation_kind=InventoryObservationKind.PARTIAL,
            mutation_kind=InventoryMutationKind.UPSERT,
            subject_ref="resource-1",
            subject_type="compute.vm",
            properties={"tags": {}},
            property_mask=("sku",),
            properties_complete=False,
            links_complete=False,
            tombstone_confirmed=False,
            source_identity="test.inventory",
            source_event_id="invalid",
            source_revision="revision:invalid",
            effective_at=NOW,
            observed_at=NOW,
            evidence_cutoff=NOW,
            recorded_at=NOW,
        )


def test_relationship_observation_is_typed_and_content_addressed() -> None:
    observation = NormalizedInventoryObservation.create(
        idempotency_key="event:relationship",
        subject_kind=InventoryObservationSubjectKind.RELATIONSHIP,
        observation_kind=InventoryObservationKind.FULL,
        mutation_kind=InventoryMutationKind.UPSERT,
        subject_ref="relationship:example",
        subject_type="depends_on",
        properties={"verified": True},
        property_mask=("verified",),
        properties_complete=True,
        links_complete=True,
        tombstone_confirmed=False,
        source_identity="test.inventory",
        source_event_id="relationship",
        source_revision="revision:relationship",
        effective_at=NOW,
        observed_at=NOW,
        evidence_cutoff=NOW,
        recorded_at=NOW,
        from_id="resource-1",
        from_type="compute.vm",
        link_type="depends_on",
        to_id="resource-2",
        to_type="postgresql",
    )

    assert observation.observation_id == observation.content_digest
    assert observation.observation_kind is InventoryObservationKind.FULL
