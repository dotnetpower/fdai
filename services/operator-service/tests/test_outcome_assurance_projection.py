"""Focused Operator tests for Outcome Assurance projection builder and drill-downs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_operator_service.families.operations import ProjectionQuery
from fdai_operator_service.outcome_assurance_projection import (
    OutcomeAssuranceOperatorProjection,
    build_outcome_assurance_operator_projection,
    read_outcome_assurance_operator_projection,
)
from fdai_service_contracts import (
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
    OutcomeAssuranceReadiness,
    OutcomeAssuranceReadinessFacet,
    OutcomeAssuranceReadinessState,
    OutcomeAssuranceReadState,
    OutcomeAssuranceScope,
    OutcomeAssuranceSource,
    OutcomeAssuranceSourceState,
    OutcomeAssuranceUnavailableReason,
    OutcomeAssuranceVertical,
    OutcomeAssuranceWindow,
)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _complete_projection(
    *,
    observed_at: datetime = NOW - timedelta(hours=2),
    expires_at: datetime = NOW + timedelta(hours=1),
    source_state: OutcomeAssuranceSourceState = OutcomeAssuranceSourceState.COMPLETE,
    source_reason: OutcomeAssuranceUnavailableReason | None = None,
    guard_state: OutcomeAssuranceGuardState = OutcomeAssuranceGuardState.HEALTHY,
    guard_passed: bool = True,
    policy_escapes: int = 0,
) -> OutcomeAssuranceProjection:
    is_unavail = source_state is OutcomeAssuranceSourceState.UNAVAILABLE
    read_state = (
        OutcomeAssuranceReadState.UNAVAILABLE if is_unavail else OutcomeAssuranceReadState.COMPLETE
    )
    return OutcomeAssuranceProjection(
        state=read_state,
        reason=source_reason if is_unavail else None,
        scope=OutcomeAssuranceScope(
            scope_ref="scope.payments",
            service_refs=("svc.payments-api",),
            workload_refs=("wl.payments-worker",),
            vertical=OutcomeAssuranceVertical.CHANGE_SAFETY,
        ),
        window=OutcomeAssuranceWindow(
            start=NOW - timedelta(days=30),
            end=NOW,
            label="30d",
            scenario_set_version="scenarios-v1",
        ),
        sources=(
            OutcomeAssuranceSource(
                name="outcome-assurance-measurement",
                state=source_state,
                reason=source_reason,
                observed_at=None if is_unavail else observed_at,
                expires_at=None if is_unavail else expires_at,
                evidence_refs=() if is_unavail else ("measurement:payments-window",),
            ),
        ),
        readiness=(
            OutcomeAssuranceReadiness(
                facet=OutcomeAssuranceReadinessFacet.MEASUREMENT,
                state=OutcomeAssuranceReadinessState.UNAVAILABLE
                if is_unavail
                else OutcomeAssuranceReadinessState.READY,
                reason=source_reason if is_unavail else None,
                observed_at=None if is_unavail else observed_at,
                expires_at=None if is_unavail else expires_at,
                evidence_refs=() if is_unavail else ("readiness:measurement-ready",),
            ),
            OutcomeAssuranceReadiness(
                facet=OutcomeAssuranceReadinessFacet.ACTION_SAFETY,
                state=OutcomeAssuranceReadinessState.UNAVAILABLE
                if is_unavail
                else OutcomeAssuranceReadinessState.READY,
                reason=source_reason if is_unavail else None,
                observed_at=None if is_unavail else observed_at,
                expires_at=None if is_unavail else expires_at,
                evidence_refs=() if is_unavail else ("readiness:action-safety-ready",),
            ),
        ),
        alignment=OutcomeAssuranceAttribution(
            state=OutcomeAssuranceAttributionState.UNAVAILABLE
            if is_unavail
            else OutcomeAssuranceAttributionState.PARTIAL,
            finalized_events=0 if is_unavail else 20,
            attributed_events=0 if is_unavail else 19,
            unattributed_events=0 if is_unavail else 1,
            coverage=None if is_unavail else 0.95,
            objective_refs=() if is_unavail else ("objective.change-failure-rate@1.0.0",),
            workflow_refs=() if is_unavail else ("workflow.canary-rollout@1.0.0",),
            action_type_ids=() if is_unavail else ("ops.rollback-kubernetes-rollout",),
            evidence_refs=() if is_unavail else ("audit:decision-case-101",),
            reason=source_reason if is_unavail else None,
        ),
        outcomes=()
        if is_unavail
        else (
            OutcomeAssuranceMetric(
                objective_ref="objective.change-failure-rate@1.0.0",
                metric="change_failure_rate",
                state=OutcomeAssuranceMetricState.MEASURED,
                current_value=0.015,
                baseline_value=0.03,
                target_value=0.02,
                unit="ratio",
                sample_size=60,
                confidence_interval=OutcomeAssuranceConfidenceInterval(low=0.01, high=0.02),
                source_time=NOW,
                evidence_refs=("measurement:cfr-obs-1",),
            ),
        ),
        guards=OutcomeAssuranceControlSummary(
            state=OutcomeAssuranceGuardState.UNAVAILABLE if is_unavail else guard_state,
            reason=source_reason if is_unavail else None,
            guard_evaluations=()
            if is_unavail
            else (
                OutcomeAssuranceGuardEvaluation(
                    guard_id="rollback_rate_ceiling",
                    threshold=0.05,
                    observed_value=0.02 if guard_passed else 0.08,
                    passed=guard_passed,
                    evidence_ref="guard:rollback-rate",
                ),
            ),
            policy_escape_count=0 if is_unavail else policy_escapes,
            evidence_refs=() if is_unavail else ("promotion:change-safety-gate",),
        ),
        provenance=OutcomeAssuranceProvenance(
            as_of=NOW,
            generated_at=NOW,
            source_names=("outcome-assurance-measurement",),
        ),
    )


def test_requires_authenticated_principal() -> None:
    with pytest.raises(PermissionError, match="authenticated principal"):
        build_outcome_assurance_operator_projection(
            principal_id="",
            projection=_complete_projection(),
            now=NOW,
        )

    with pytest.raises(PermissionError, match="authenticated principal"):
        build_outcome_assurance_operator_projection(
            principal_id=None,
            projection=_complete_projection(),
            now=NOW,
        )


def test_complete_projection_builds_read_only_cards_and_objective_drilldown() -> None:
    operator_proj = build_outcome_assurance_operator_projection(
        principal_id="operator-reader-1",
        projection=_complete_projection(),
        now=NOW,
    )

    assert operator_proj.read_only is True
    assert operator_proj.authority == "none"
    assert operator_proj.state is OutcomeAssuranceReadState.COMPLETE
    assert operator_proj.reason is None

    cards = {card.card_id: card for card in operator_proj.summary_cards}
    assert cards["operational_readiness"].available is True
    assert cards["operational_readiness"].state == "ready"
    assert cards["operational_readiness"].headline_metric == pytest.approx(1.0)
    assert cards["objective_alignment"].available is True
    assert cards["objective_alignment"].state == "partial"
    assert cards["objective_alignment"].headline_metric == pytest.approx(0.95)
    assert cards["control_assurance"].available is True
    assert cards["control_assurance"].state == "healthy"
    assert cards["control_assurance"].headline_metric == pytest.approx(1.0)

    assert len(operator_proj.objective_drilldowns) == 1
    drilldown = operator_proj.objective_drilldowns[0]
    assert drilldown.objective_ref == "objective.change-failure-rate@1.0.0"
    assert drilldown.finalized_events == 20
    assert drilldown.attributed_events == 19
    assert drilldown.unattributed_events == 1
    assert drilldown.coverage == pytest.approx(0.95)
    assert drilldown.workflow_refs == ("workflow.canary-rollout@1.0.0",)
    assert drilldown.action_type_ids == ("ops.rollback-kubernetes-rollout",)
    assert len(drilldown.metrics) == 1
    assert drilldown.metrics[0].current_value == pytest.approx(0.015)
    assert set(drilldown.evidence_refs) == {
        "audit:decision-case-101",
        "measurement:cfr-obs-1",
    }


def test_guard_violation_surfaces_blocked_control_assurance() -> None:
    operator_proj = build_outcome_assurance_operator_projection(
        principal_id="operator-reader-1",
        projection=_complete_projection(
            guard_state=OutcomeAssuranceGuardState.BLOCKED,
            guard_passed=False,
            policy_escapes=1,
        ),
        now=NOW,
    )

    assert operator_proj.guard_status.state is OutcomeAssuranceGuardState.BLOCKED
    assert operator_proj.guard_status.policy_escape_count == 1
    assert operator_proj.guard_status.guard_evaluations[0].passed is False

    cards = {card.card_id: card for card in operator_proj.summary_cards}
    control_card = cards["control_assurance"]
    assert control_card.available is True
    assert control_card.state == "blocked"
    assert control_card.headline_metric == pytest.approx(0.0)
    assert "guard:rollback-rate" in control_card.evidence_refs


@pytest.mark.parametrize(
    ("projection", "expected_reason"),
    [
        (None, OutcomeAssuranceUnavailableReason.PROJECTION_MISSING),
        (
            _complete_projection(expires_at=NOW - timedelta(minutes=1)),
            OutcomeAssuranceUnavailableReason.SOURCE_STALE,
        ),
        (
            _complete_projection(
                source_state=OutcomeAssuranceSourceState.UNAVAILABLE,
                source_reason=OutcomeAssuranceUnavailableReason.SOURCE_NOT_CONNECTED,
            ),
            OutcomeAssuranceUnavailableReason.SOURCE_NOT_CONNECTED,
        ),
    ],
)
def test_missing_stale_or_unverified_sources_fail_closed_to_unavailable(
    projection: OutcomeAssuranceProjection | None,
    expected_reason: OutcomeAssuranceUnavailableReason,
) -> None:
    operator_proj = build_outcome_assurance_operator_projection(
        principal_id="operator-reader-1",
        projection=projection,
        scope_ref="scope.payments",
        vertical="change_safety",
        window_label="30d",
        now=NOW,
    )

    assert operator_proj.read_only is True
    assert operator_proj.authority == "none"
    assert operator_proj.state is OutcomeAssuranceReadState.UNAVAILABLE
    assert operator_proj.reason is expected_reason
    assert operator_proj.objective_drilldowns == ()
    assert operator_proj.guard_status.state is OutcomeAssuranceGuardState.UNAVAILABLE
    for card in operator_proj.summary_cards:
        assert card.available is False
        assert card.state == "unavailable"
        assert card.headline_metric is None


@pytest.mark.anyio
async def test_read_outcome_assurance_operator_projection_round_trip() -> None:
    stored = _complete_projection(expires_at=datetime(2099, 1, 1, tzinfo=UTC))

    async def fetch_all(
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del statement, parameters
        return [{"value": stored.model_dump(mode="json")}]

    payload = await read_outcome_assurance_operator_projection(
        fetch_all=fetch_all,
        query=ProjectionQuery(
            operation="outcome_assurance",
            path={},
            limit=50,
            cursor=None,
            principal_id="operator-reader-1",
            params={"scope_ref": ("scope.payments",), "vertical": ("change_safety",)},
        ),
    )
    decoded = OutcomeAssuranceOperatorProjection.model_validate(payload)
    assert decoded.read_only is True
    assert decoded.authority == "none"
    assert decoded.state is OutcomeAssuranceReadState.COMPLETE
    assert len(decoded.objective_drilldowns) == 1


def test_rejects_non_finite_metrics_negative_sample_size_and_inverted_ci() -> None:
    from fdai_operator_service.outcome_assurance_projection import OutcomeAssuranceSummaryCard

    for bad_val in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite"):
            OutcomeAssuranceSummaryCard(
                card_id="operational_readiness",
                state="ready",
                available=True,
                headline_metric=bad_val,
            )

    with pytest.raises(ValueError, match="sample_size"):
        OutcomeAssuranceSummaryCard(
            card_id="operational_readiness",
            state="ready",
            available=True,
            headline_metric=0.5,
            sample_size=-1,
        )

    for ci_low, val, ci_high in ((0.6, 0.5, 0.8), (0.2, 0.9, 0.8)):
        with pytest.raises(ValueError, match="confidence interval"):
            OutcomeAssuranceSummaryCard(
                card_id="operational_readiness",
                state="ready",
                available=True,
                headline_metric=val,
                ci_low=ci_low,
                ci_high=ci_high,
            )
        base = _complete_projection()
        bad_metric = base.outcomes[0].model_copy(
            update={
                "current_value": val,
                "confidence_interval": OutcomeAssuranceConfidenceInterval(low=ci_low, high=ci_high),
            }
        )
        bad_proj = base.model_copy(update={"outcomes": (bad_metric,)})
        with pytest.raises(ValueError, match="confidence interval"):
            build_outcome_assurance_operator_projection(
                principal_id="operator-reader-1",
                projection=bad_proj,
                now=NOW,
            )
