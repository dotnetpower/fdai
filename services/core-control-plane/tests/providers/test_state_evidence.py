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


def test_link_verification_requires_independent_identity() -> None:
    with pytest.raises(ValueError, match="identify verifier"):
        LinkObservationMetadata(
            state_fact=_fact(),
            verification_method="provider-readback",
            verified=True,
        )

    metadata = LinkObservationMetadata(
        state_fact=_fact(),
        verification_method="provider-readback",
        verified=True,
        verifier_identity="inventory-readback",
        verifier_revision="revision-2",
    )
    assert LinkObservationMetadata.from_mapping(metadata.to_mapping()) == metadata
