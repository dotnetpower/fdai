from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.measurement.outcome_assurance import (
    ConfidenceInterval,
    ControlAssuranceState,
    ControlAssuranceSummary,
    FinalizedOutcomeEvent,
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
    summarize_objective_attribution,
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


def _finalized_event(
    event_id: str,
    *,
    objective_ref: str | None = "objective.change-failure-rate@1.0.0",
    observed_outcome_ref: str | None = "outcome.change-failure-rate",
) -> FinalizedOutcomeEvent:
    return FinalizedOutcomeEvent(
        event_id=event_id,
        finalized_at=NOW - timedelta(minutes=1),
        decision_case_id=f"decision.{event_id}",
        protected_objective_ref=objective_ref,
        workflow_ref="workflow.change-safety",
        action_type_id="kubernetes.rollout.restart",
        action_run_id=f"run.{event_id}",
        observed_outcome_ref=observed_outcome_ref,
        evidence_refs=(f"audit:{event_id}",),
    )


def _observation(
    event_id: str,
    *,
    observation_id: str,
    recorded_at: datetime,
    evidence_ref: str,
    objective_ref: str = "objective.change-failure-rate@1.0.0",
) -> OutcomeMeasurementObservation:
    return OutcomeMeasurementObservation(
        event_id=event_id,
        objective_ref=objective_ref,
        metric="change_failure_rate",
        observation_id=observation_id,
        observed_at=recorded_at - timedelta(seconds=1),
        recorded_at=recorded_at,
        value=0.02,
        evidence_ref=evidence_ref,
    )


def test_objective_attribution_keeps_incomplete_finalized_events_in_denominator() -> None:
    summary = summarize_objective_attribution(
        (
            _finalized_event("event-1"),
            _finalized_event("event-2", observed_outcome_ref=None),
            _finalized_event("event-3"),
        ),
        (
            _observation(
                "event-1",
                observation_id="observation-1",
                recorded_at=NOW,
                evidence_ref="measurement:event-1",
            ),
        ),
    )

    assert summary.state is ObjectiveAttributionState.PARTIAL
    assert summary.finalized_events == 3
    assert summary.attributed_events == 1
    assert summary.unattributed_events == 2
    assert summary.coverage == pytest.approx(1 / 3)
    assert summary.objective_refs == ("objective.change-failure-rate@1.0.0",)
    assert summary.workflow_refs == ("workflow.change-safety",)
    assert summary.action_type_ids == ("kubernetes.rollout.restart",)
    assert summary.evidence_refs == (
        "audit:event-1",
        "audit:event-2",
        "audit:event-3",
        "measurement:event-1",
    )


def test_objective_attribution_uses_only_latest_observation_evidence() -> None:
    summary = summarize_objective_attribution(
        (_finalized_event("event-1"),),
        (
            _observation(
                "event-1",
                observation_id="observation-old",
                recorded_at=NOW - timedelta(minutes=2),
                evidence_ref="measurement:old",
            ),
            _observation(
                "event-1",
                observation_id="observation-new",
                recorded_at=NOW - timedelta(minutes=1),
                evidence_ref="measurement:new",
            ),
        ),
    )

    assert summary.state is ObjectiveAttributionState.ATTRIBUTED
    assert summary.evidence_refs == ("audit:event-1", "measurement:new")


def test_objective_attribution_does_not_infer_from_mismatched_objective() -> None:
    summary = summarize_objective_attribution(
        (_finalized_event("event-1"),),
        (
            _observation(
                "event-1",
                observation_id="observation-1",
                recorded_at=NOW,
                evidence_ref="measurement:other",
                objective_ref="objective.unrelated@1.0.0",
            ),
        ),
    )

    assert summary.state is ObjectiveAttributionState.UNATTRIBUTED
    assert summary.attributed_events == 0
    assert summary.unattributed_events == 1


def test_objective_attribution_rejects_duplicate_finalized_event_identity() -> None:
    with pytest.raises(ValueError, match="unique by event_id"):
        summarize_objective_attribution(
            (_finalized_event("event-1"), _finalized_event("event-1")),
            (),
        )


def test_objective_attribution_rejects_observation_outside_finalized_universe() -> None:
    with pytest.raises(ValueError, match="reference a finalized event"):
        summarize_objective_attribution(
            (_finalized_event("event-1"),),
            (
                _observation(
                    "event-2",
                    observation_id="observation-2",
                    recorded_at=NOW,
                    evidence_ref="measurement:event-2",
                ),
            ),
        )


def test_objective_attribution_empty_universe_is_explicitly_unattributed() -> None:
    summary = summarize_objective_attribution((), ())

    assert summary.state is ObjectiveAttributionState.UNATTRIBUTED
    assert summary.finalized_events == 0
    assert summary.coverage == 0.0
