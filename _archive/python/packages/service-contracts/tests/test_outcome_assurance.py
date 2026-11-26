"""Outcome Assurance shared read-contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts import (
    JsonSchemaContractValidator,
    OutcomeAssuranceAttribution,
    OutcomeAssuranceAttributionState,
    OutcomeAssuranceConfidenceInterval,
    OutcomeAssuranceControlSummary,
    OutcomeAssuranceGuardEvaluation,
    OutcomeAssuranceGuardState,
    OutcomeAssuranceMetric,
    OutcomeAssuranceMetricState,
    OutcomeAssuranceProjection,
    OutcomeAssuranceProvenance,
    OutcomeAssuranceReadState,
    OutcomeAssuranceReadiness,
    OutcomeAssuranceReadinessFacet,
    OutcomeAssuranceReadinessState,
    OutcomeAssuranceScope,
    OutcomeAssuranceSource,
    OutcomeAssuranceSourceState,
    OutcomeAssuranceUnavailableReason,
    OutcomeAssuranceVertical,
    OutcomeAssuranceWindow,
    PackageResourceSchemaRegistry,
)

NOW = datetime(2026, 10, 4, 0, 0, tzinfo=UTC)


def _projection(**overrides: object) -> OutcomeAssuranceProjection:
    values: dict[str, object] = {
        "state": OutcomeAssuranceReadState.COMPLETE,
        "scope": OutcomeAssuranceScope(
            scope_ref="scope.checkout",
            service_refs=("service.checkout",),
            workload_refs=("workload.checkout-api",),
            vertical=OutcomeAssuranceVertical.CHANGE_SAFETY,
        ),
        "window": OutcomeAssuranceWindow(
            start=NOW - timedelta(days=30),
            end=NOW,
            label="30d",
            scenario_set_version="scenario-set-2026-10-04",
        ),
        "sources": (
            OutcomeAssuranceSource(
                name="outcome-assurance-measurement",
                state=OutcomeAssuranceSourceState.COMPLETE,
                observed_at=NOW - timedelta(minutes=5),
                expires_at=NOW + timedelta(hours=1),
                evidence_refs=("measurement:change-safety",),
            ),
        ),
        "readiness": (
            OutcomeAssuranceReadiness(
                facet=OutcomeAssuranceReadinessFacet.MEASUREMENT,
                state=OutcomeAssuranceReadinessState.READY,
                observed_at=NOW - timedelta(minutes=5),
                expires_at=NOW + timedelta(hours=1),
                evidence_refs=("readiness:measurement",),
            ),
        ),
        "alignment": OutcomeAssuranceAttribution(
            state=OutcomeAssuranceAttributionState.PARTIAL,
            finalized_events=4,
            attributed_events=3,
            unattributed_events=1,
            coverage=0.75,
            objective_refs=("objective.change-failure-rate@1.0.0",),
            workflow_refs=("workflow.change-safety",),
            action_type_ids=("kubernetes.rollout.restart",),
            evidence_refs=("audit:action-run",),
        ),
        "outcomes": (
            OutcomeAssuranceMetric(
                objective_ref="objective.change-failure-rate@1.0.0",
                metric="change_failure_rate",
                state=OutcomeAssuranceMetricState.MEASURED,
                current_value=0.02,
                baseline_value=0.03,
                target_value=0.025,
                unit="ratio",
                sample_size=48,
                confidence_interval=OutcomeAssuranceConfidenceInterval(low=0.01, high=0.03),
                source_time=NOW - timedelta(minutes=5),
                evidence_refs=("measurement:change-failure-rate",),
            ),
        ),
        "guards": OutcomeAssuranceControlSummary(
            state=OutcomeAssuranceGuardState.HEALTHY,
            guard_evaluations=(
                OutcomeAssuranceGuardEvaluation(
                    guard_id="policy_escape_zero",
                    threshold=0,
                    observed_value=0,
                    passed=True,
                    evidence_ref="guard:policy-escape-zero",
                ),
            ),
            evidence_refs=("promotion:change-safety",),
        ),
        "provenance": OutcomeAssuranceProvenance(
            as_of=NOW,
            generated_at=NOW,
            source_names=("outcome-assurance-measurement",),
        ),
    }
    values.update(overrides)
    return OutcomeAssuranceProjection.model_validate(values)


def _unavailable(reason: OutcomeAssuranceUnavailableReason) -> OutcomeAssuranceProjection:
    return _projection(
        state=OutcomeAssuranceReadState.UNAVAILABLE,
        reason=reason,
        sources=(
            OutcomeAssuranceSource(
                name="outcome-assurance-measurement",
                state=OutcomeAssuranceSourceState.UNAVAILABLE,
                reason=reason,
            ),
        ),
        readiness=(
            OutcomeAssuranceReadiness(
                facet=OutcomeAssuranceReadinessFacet.MEASUREMENT,
                state=OutcomeAssuranceReadinessState.UNAVAILABLE,
                reason=reason,
            ),
        ),
        alignment=OutcomeAssuranceAttribution(
            state=OutcomeAssuranceAttributionState.UNAVAILABLE,
            finalized_events=0,
            attributed_events=0,
            unattributed_events=0,
            reason=reason,
        ),
        outcomes=(),
        guards=OutcomeAssuranceControlSummary(
            state=OutcomeAssuranceGuardState.UNAVAILABLE,
            reason=reason,
        ),
    )


def test_complete_projection_is_versioned_and_authority_free() -> None:
    projection = _projection()

    assert projection.schema_version == "1.0.0"
    assert projection.execution_authority is False
    assert projection.approval_authority is False
    assert projection.promotion_authority is False
    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
        "outcome-assurance-projection",
        projection.model_dump(mode="json"),
        version="1.0.0",
    )


def test_missing_source_is_explicitly_unavailable_without_values() -> None:
    projection = _unavailable(OutcomeAssuranceUnavailableReason.SOURCE_MISSING)

    assert projection.state is OutcomeAssuranceReadState.UNAVAILABLE
    assert projection.reason is OutcomeAssuranceUnavailableReason.SOURCE_MISSING
    assert projection.sources[0].state is OutcomeAssuranceSourceState.UNAVAILABLE
    assert projection.outcomes == ()


def test_stale_source_cannot_report_complete_projection() -> None:
    stale_source = OutcomeAssuranceSource(
        name="outcome-assurance-measurement",
        state=OutcomeAssuranceSourceState.STALE,
        reason=OutcomeAssuranceUnavailableReason.SOURCE_STALE,
        observed_at=NOW - timedelta(hours=2),
        expires_at=NOW - timedelta(hours=1),
        evidence_refs=("measurement:expired",),
    )

    with pytest.raises(ValueError, match="complete sources"):
        _projection(sources=(stale_source,))

    stale = _projection(
        state=OutcomeAssuranceReadState.STALE,
        reason=OutcomeAssuranceUnavailableReason.SOURCE_STALE,
        sources=(stale_source,),
        outcomes=(
            OutcomeAssuranceMetric(
                objective_ref="objective.change-failure-rate@1.0.0",
                metric="change_failure_rate",
                state=OutcomeAssuranceMetricState.STALE,
                reason=OutcomeAssuranceUnavailableReason.SOURCE_STALE,
            ),
        ),
    )
    assert stale.state is OutcomeAssuranceReadState.STALE
    assert stale.outcomes[0].current_value is None


def test_unavailable_metric_rejects_synthetic_zero_fill() -> None:
    with pytest.raises(ValueError, match="cannot carry values"):
        OutcomeAssuranceMetric(
            objective_ref="objective.change-failure-rate@1.0.0",
            metric="change_failure_rate",
            state=OutcomeAssuranceMetricState.UNAVAILABLE,
            reason=OutcomeAssuranceUnavailableReason.SOURCE_NOT_CONNECTED,
            current_value=0,
        )


def test_schema_resource_matches_contract_model() -> None:
    stored = dict(PackageResourceSchemaRegistry().get("outcome-assurance-projection", "1.0.0"))
    assert stored == OutcomeAssuranceProjection.model_json_schema(mode="serialization")
