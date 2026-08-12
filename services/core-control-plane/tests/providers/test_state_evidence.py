"""Typed state and link evidence metadata invariants."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

RECORDED_AT = datetime(2026, 8, 8, 12, tzinfo=UTC)


def _fact(
    *,
    lane: StateFactLane = StateFactLane.OBSERVED,
    authority: StateFactAuthority = StateFactAuthority.PROVIDER,
) -> StateFactMetadata:
    return StateFactMetadata(
        lane=lane,
        authority=authority,
        source_identity="inventory-provider",
        source_revision="revision-7",
        effective_at=RECORDED_AT - timedelta(minutes=2),
        evidence_cutoff=RECORDED_AT - timedelta(minutes=1),
        recorded_at=RECORDED_AT,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        conflicts=(),
        evidence_refs=("receipt-b", "receipt-a", "receipt-a"),
    )


def test_state_fact_metadata_has_canonical_round_trip() -> None:
    fact = _fact()

    assert fact.evidence_refs == ("receipt-a", "receipt-b")
    assert StateFactMetadata.from_mapping(fact.to_mapping()) == fact
    assert fact.to_mapping()["effective_at"] == "2026-08-08T11:58:00Z"


def test_observed_and_derived_facts_cannot_share_authority() -> None:
    derived = _fact(
        lane=StateFactLane.DERIVED,
        authority=StateFactAuthority.DETERMINISTIC_FUNCTION,
    )

    assert derived.lane is StateFactLane.DERIVED
    with pytest.raises(ValueError, match="invalid.*derived"):
        replace(derived, authority=StateFactAuthority.PROVIDER)


@pytest.mark.parametrize("field_name", ["effective_at", "recorded_at", "evidence_cutoff"])
def test_state_fact_metadata_rejects_naive_timestamps(field_name: str) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_fact(), **{field_name: datetime(2026, 8, 8, 12)})


def test_state_fact_metadata_rejects_future_evidence() -> None:
    with pytest.raises(ValueError, match="evidence_cutoff MUST NOT exceed recorded_at"):
        replace(_fact(), evidence_cutoff=RECORDED_AT + timedelta(seconds=1))


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("freshness_ceiling_seconds", True, "MUST be an integer"),
        ("completeness", True, "MUST be numeric"),
        ("synthetic", 1, "MUST be a boolean"),
    ],
)
def test_direct_state_fact_construction_rejects_bool_integer_aliases(
    field_name: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_fact(), **{field_name: value})


def test_link_verification_requires_independent_identity() -> None:
    with pytest.raises(ValueError, match="verification receipt"):
        LinkObservationMetadata(
            state_fact=_fact(),
            verification_method="provider-readback",
            verified=True,
        )

    with pytest.raises(ValueError, match="independent verifier"):
        LinkObservationMetadata(
            state_fact=_fact(),
            verification_method="provider-readback",
            verified=True,
            verifier_identity="inventory-provider",
            verifier_revision="revision-2",
            verification_receipt_ref="verification-receipt-2",
        )

    with pytest.raises(ValueError, match="trusted verification method"):
        LinkObservationMetadata(
            state_fact=_fact(),
            verification_method="self-asserted",
            verified=True,
            verifier_identity="inventory-readback",
            verifier_revision="revision-2",
            verification_receipt_ref="verification-receipt-2",
        )

    metadata = LinkObservationMetadata(
        state_fact=_fact(),
        verification_method="provider-readback",
        verified=True,
        verifier_identity="inventory-readback",
        verifier_revision="revision-2",
        verification_receipt_ref="verification-receipt-2",
    )
    assert LinkObservationMetadata.from_mapping(metadata.to_mapping()) == metadata


def test_legacy_link_metadata_without_verification_receipt_cannot_claim_verified() -> None:
    metadata = LinkObservationMetadata(
        state_fact=_fact(),
        verification_method="provider-readback",
        verified=True,
        verifier_identity="inventory-readback",
        verifier_revision="revision-2",
        verification_receipt_ref="verification-receipt-2",
    )
    legacy = metadata.to_mapping()
    del legacy["verification_receipt_ref"]

    decoded = LinkObservationMetadata.from_mapping(legacy)

    assert decoded.verified is False
    assert decoded.verifier_identity is None
    assert decoded.verifier_revision is None
    assert decoded.verification_receipt_ref is None


def test_provider_relationship_metadata_round_trip_pins_generation_and_mapping() -> None:
    metadata = LinkObservationMetadata(
        state_fact=_fact(),
        verification_method="deterministic-cross-check",
        verified=True,
        verifier_identity="inventory-generation-verifier",
        verifier_revision="verifier-v1",
        verification_receipt_ref="sha256:" + "1" * 64,
        inventory_generation="inventory-generation-7",
        mapping_id="azure.vm-nic-attached-to-vm",
        mapping_revision="sha256:" + "2" * 64,
        source_schema_version="azure-resource-graph-resources@2022-10-01",
        source_schema_digest="sha256:" + "3" * 64,
    )

    assert LinkObservationMetadata.from_mapping(metadata.to_mapping()) == metadata


def test_provider_relationship_metadata_rejects_partial_provenance() -> None:
    with pytest.raises(ValueError, match="generation, mapping, and schema"):
        LinkObservationMetadata(
            state_fact=_fact(),
            verification_method="deterministic-cross-check",
            verified=True,
            verifier_identity="inventory-generation-verifier",
            verifier_revision="verifier-v1",
            verification_receipt_ref="sha256:" + "1" * 64,
            inventory_generation="inventory-generation-7",
        )
