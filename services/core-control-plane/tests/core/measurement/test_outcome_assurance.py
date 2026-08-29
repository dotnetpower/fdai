from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.measurement.outcome_assurance import (
    ConfidenceInterval,
    ControlAssuranceState,
    ControlAssuranceSummary,
    GuardEvaluation,
    ObjectiveAttributionState,
    ObjectiveAttributionSummary,
    OutcomeAssuranceProjection,
    OutcomeAssuranceScope,
    OutcomeAssuranceWindow,
    OutcomeEvidenceState,
    OutcomeMeasurement,
    OutcomeMeasurementObservation,
    OutcomeProvenance,
    OutcomeVertical,
    ReadinessFacet,
    ReadinessFacetSnapshot,
    ReadinessFacetState,
    latest_authoritative_observations,
)

NOW = datetime(2026, 8, 29, 0, 0, tzinfo=UTC)


def _projection() -> OutcomeAssuranceProjection:
    return OutcomeAssuranceProjection(
        scope=OutcomeAssuranceScope(
            scope_ref="scope.checkout",
            service_refs=("service.checkout",),
            workload_refs=("workload.checkout-api",),
            vertical=OutcomeVertical.CHANGE_SAFETY,
        ),
        window=OutcomeAssuranceWindow(
            start=NOW - timedelta(days=7),
            end=NOW,
            scenario_set_version="scenario-set-2026-08-29",
        ),
        readiness=(
            ReadinessFacetSnapshot(
                facet=ReadinessFacet.PLATFORM,
                state=ReadinessFacetState.READY,
                evidence_refs=("startup:2026-08-29",),
                observed_at=NOW - timedelta(hours=2),
                expires_at=NOW + timedelta(hours=2),
            ),
            ReadinessFacetSnapshot(
                facet=ReadinessFacet.MEASUREMENT,
                state=ReadinessFacetState.OBSERVED,
                evidence_refs=("measurement-baseline:2026-08-29",),
                observed_at=NOW - timedelta(hours=1),
                expires_at=NOW + timedelta(hours=1),
            ),
        ),
        alignment=ObjectiveAttributionSummary(
            state=ObjectiveAttributionState.PARTIAL,
            objective_refs=("objective.change-failure-rate@1.0.0",),
            workflow_refs=("workflow.change-safety",),
            action_type_ids=("kubernetes.rollout.restart",),
            finalized_events=4,
            attributed_events=3,
            unattributed_events=1,
            coverage=0.75,
            evidence_refs=("audit:action-run-2026-08-29",),
        ),
        outcomes=(
            OutcomeMeasurement(
                objective_ref="objective.change-failure-rate@1.0.0",
                metric="change_failure_rate",
                state=OutcomeEvidenceState.MEASURED,
                current_value=0.02,
                baseline_value=0.03,
                target_value=0.025,
                unit="ratio",
                sample_size=48,
                confidence_interval=ConfidenceInterval(low=0.01, high=0.03),
                source_time=NOW - timedelta(minutes=5),
                evidence_refs=("measurement:change-failure-rate",),
            ),
        ),
        guards=ControlAssuranceSummary(
            state=ControlAssuranceState.HEALTHY,
            guard_evaluations=(
                GuardEvaluation(
                    guard_id="policy_escape_zero",
                    threshold=0.0,
                    observed_value=0.0,
                    passed=True,
                    evidence_ref="guard:policy-escape-zero",
                ),
            ),
            evidence_refs=("promotion:change-safety-2026-08-29",),
        ),
        provenance=OutcomeProvenance(
            source_names=("readiness", "measurement", "audit"),
            as_of=NOW,
            synthetic=False,
        ),
    )


def test_projection_round_trips_with_stable_json() -> None:
    projection = _projection()

    payload = projection.to_json()

    assert payload == projection.to_json()
    assert OutcomeAssuranceProjection.from_json(payload) == projection


def test_alignment_requires_unattributed_events_in_denominator() -> None:
    with pytest.raises(ValueError, match="finalized_events MUST equal"):
        ObjectiveAttributionSummary(
            state=ObjectiveAttributionState.PARTIAL,
            objective_refs=("objective.change-failure-rate@1.0.0",),
            finalized_events=3,
            attributed_events=3,
            unattributed_events=1,
            coverage=0.75,
            evidence_refs=("audit:action-run-2026-08-29",),
        )


def test_alignment_state_must_match_coverage_split() -> None:
    with pytest.raises(ValueError, match="state MUST reflect"):
        ObjectiveAttributionSummary(
            state=ObjectiveAttributionState.ATTRIBUTED,
            objective_refs=("objective.change-failure-rate@1.0.0",),
            finalized_events=4,
            attributed_events=3,
            unattributed_events=1,
            coverage=0.75,
            evidence_refs=("audit:action-run-2026-08-29",),
        )


def test_measured_outcome_requires_full_evidence() -> None:
    with pytest.raises(
        ValueError,
        match="measured Outcome Assurance values MUST include",
    ):
        OutcomeMeasurement(
            objective_ref="objective.change-failure-rate@1.0.0",
            metric="change_failure_rate",
            state=OutcomeEvidenceState.MEASURED,
            current_value=0.02,
            baseline_value=0.03,
            target_value=0.025,
            unit="ratio",
            sample_size=48,
            confidence_interval=ConfidenceInterval(low=0.01, high=0.03),
        )


def test_policy_escape_forces_blocked_control_assurance() -> None:
    with pytest.raises(ValueError, match="policy escapes MUST force blocked"):
        ControlAssuranceSummary(
            state=ControlAssuranceState.HEALTHY,
            policy_escape_count=1,
            evidence_refs=("promotion:change-safety-2026-08-29",),
        )


def test_latest_authoritative_observations_keep_latest_recorded_row_per_event_metric() -> None:
    earliest = OutcomeMeasurementObservation(
        event_id="event-1",
        objective_ref="objective.change-failure-rate@1.0.0",
        metric="change_failure_rate",
        observation_id="obs-a",
        observed_at=NOW - timedelta(minutes=30),
        recorded_at=NOW - timedelta(minutes=20),
        value=0.05,
        evidence_ref="measurement:older",
    )
    corrected = OutcomeMeasurementObservation(
        event_id="event-1",
        objective_ref="objective.change-failure-rate@1.0.0",
        metric="change_failure_rate",
        observation_id="obs-b",
        observed_at=NOW - timedelta(minutes=25),
        recorded_at=NOW - timedelta(minutes=10),
        value=0.02,
        evidence_ref="measurement:newer",
    )
    unrelated = OutcomeMeasurementObservation(
        event_id="event-2",
        objective_ref="objective.change-failure-rate@1.0.0",
        metric="change_failure_rate",
        observation_id="obs-c",
        observed_at=NOW - timedelta(minutes=12),
        recorded_at=NOW - timedelta(minutes=5),
        value=0.01,
        evidence_ref="measurement:other",
    )

    retained = latest_authoritative_observations((corrected, unrelated, earliest))

    assert retained == (corrected, unrelated)


def test_non_unknown_readiness_requires_evidence_and_freshness() -> None:
    with pytest.raises(ValueError, match="MUST cite evidence"):
        ReadinessFacetSnapshot(
            facet=ReadinessFacet.PLATFORM,
            state=ReadinessFacetState.READY,
            observed_at=NOW - timedelta(minutes=5),
            expires_at=NOW + timedelta(minutes=5),
        )
