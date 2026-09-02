"""Operational state-transition contract and query tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.state_transitions import (
    OperationalStateTransition,
    StateTransitionAuthority,
    StateTransitionBatch,
    StateTransitionCoverage,
    StateTransitionLane,
    state_at,
)

NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


def _transition(
    *,
    from_state: str = "running",
    to_state: str = "deallocated",
    effective_at: datetime = NOW,
    recorded_at: datetime = NOW + timedelta(seconds=5),
) -> OperationalStateTransition:
    return OperationalStateTransition.create(
        idempotency_key=f"resource-a:power:{effective_at.isoformat()}",
        subject_ref="resource-a",
        subject_type="Resource",
        state_type="resource.power_state",
        from_state=from_state,
        to_state=to_state,
        lane=StateTransitionLane.OBSERVED,
        authority=StateTransitionAuthority.PROVIDER,
        effective_at=effective_at,
        evidence_cutoff=effective_at + timedelta(seconds=2),
        recorded_at=recorded_at,
        source_identity="provider:inventory",
        source_revision="inventory-generation:1",
        producer_id="huginn.resource-state",
        producer_version="1.0.0",
        freshness_ceiling_seconds=600,
        completeness_basis_points=10_000,
        evidence_refs=("evidence:resource-a",),
    )


def _coverage() -> StateTransitionCoverage:
    return StateTransitionCoverage.create(
        subject_ref="resource-a",
        state_type="resource.power_state",
        coverage_start_at=NOW - timedelta(minutes=10),
        coverage_end_at=NOW + timedelta(seconds=2),
        recorded_at=NOW + timedelta(seconds=5),
        source_identity="provider:inventory",
        source_revision="inventory-generation:1",
        watermark="inventory-watermark:1",
        evidence_ref="evidence:coverage",
        complete=True,
    )


def test_transition_and_coverage_form_content_addressed_batch() -> None:
    transition = _transition()
    coverage = _coverage()

    batch = StateTransitionBatch.create(
        transitions=(transition,),
        coverage=(coverage,),
        recorded_at=NOW + timedelta(seconds=5),
    )

    assert transition.transition_id.startswith("sha256:")
    assert coverage.coverage_id.startswith("sha256:")
    assert batch.batch_id.startswith("sha256:")
    assert transition.execution_authority is False


def test_transition_rejects_same_state_and_execution_authority() -> None:
    with pytest.raises(ValueError, match="MUST change state"):
        _transition(from_state="running", to_state="running")

    with pytest.raises(ValueError, match="MUST NOT grant execution authority"):
        replace(_transition(), execution_authority=True)


def test_state_at_respects_effective_and_recorded_cutoffs() -> None:
    first = _transition()
    late = _transition(
        from_state="deallocated",
        to_state="running",
        effective_at=NOW + timedelta(minutes=5),
        recorded_at=NOW + timedelta(minutes=20),
    )

    assert (
        state_at(
            (first, late),
            subject_ref="resource-a",
            state_type="resource.power_state",
            effective_at=NOW + timedelta(minutes=10),
            known_at=NOW + timedelta(minutes=10),
        )
        == "deallocated"
    )
    assert (
        state_at(
            (first, late),
            subject_ref="resource-a",
            state_type="resource.power_state",
            effective_at=NOW + timedelta(minutes=10),
            known_at=NOW + timedelta(minutes=30),
        )
        == "running"
    )


def test_state_at_uses_transition_id_as_equal_time_tie_breaker() -> None:
    first = _transition(from_state="running", to_state="deallocated")
    second = OperationalStateTransition.create(
        idempotency_key="resource-a:power:equal-time-second",
        subject_ref=first.subject_ref,
        subject_type=first.subject_type,
        state_type=first.state_type,
        from_state="running",
        to_state="stopped",
        lane=first.lane,
        authority=first.authority,
        effective_at=first.effective_at,
        evidence_cutoff=first.evidence_cutoff,
        recorded_at=first.recorded_at,
        source_identity=first.source_identity,
        source_revision=first.source_revision,
        producer_id=first.producer_id,
        producer_version=first.producer_version,
        freshness_ceiling_seconds=first.freshness_ceiling_seconds,
        completeness_basis_points=first.completeness_basis_points,
        evidence_refs=("evidence:resource-a-second",),
    )
    expected = max((first, second), key=lambda item: item.transition_id).to_state

    forward = state_at(
        (first, second),
        subject_ref="resource-a",
        state_type="resource.power_state",
        effective_at=NOW + timedelta(minutes=1),
        known_at=NOW + timedelta(minutes=1),
    )
    reverse = state_at(
        (second, first),
        subject_ref="resource-a",
        state_type="resource.power_state",
        effective_at=NOW + timedelta(minutes=1),
        known_at=NOW + timedelta(minutes=1),
    )

    assert forward == reverse == expected
