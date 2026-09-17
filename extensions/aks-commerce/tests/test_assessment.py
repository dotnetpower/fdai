from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts import (
    AksCommerceEvidenceState,
    AksCommerceMetric,
    AksCommerceSlo,
    AksCommerceStatus,
    AksCommerceWorkload,
)

from fdai_aks_commerce import AksCommerceEvidenceFrame, assess_aks_commerce

NOW = datetime(2026, 9, 17, tzinfo=UTC)


def _metric(name: str, current: float, previous: float = 0) -> AksCommerceMetric:
    return AksCommerceMetric(
        name=name,
        unit="count",
        current=current,
        previous=previous,
        source_ref="source:example",
        observed_at=NOW,
        state=AksCommerceEvidenceState.COMPLETE,
    )


def _frame(
    *,
    metrics: tuple[AksCommerceMetric, ...],
    breached: bool = False,
    gaps: tuple[str, ...] = (),
    deployment_changed: bool = False,
    rollout_stalled: bool = False,
    prior_degraded: bool = False,
) -> AksCommerceEvidenceFrame:
    return AksCommerceEvidenceFrame(
        service_id="order-fulfillment",
        observed_at=NOW,
        window_start=NOW - timedelta(minutes=5),
        window_end=NOW,
        dependency_path=("storefront", "order-api", "order-queue", "order-processor"),
        workloads=(
            AksCommerceWorkload(
                workload_id="order-processor",
                display_name="Order processor",
                resource_ref="resource:processor",
                ready=True,
                revision="revision-1",
                evidence_state=AksCommerceEvidenceState.COMPLETE,
            ),
        ),
        slos=(
            AksCommerceSlo(
                slo_id="order-fulfillment.availability",
                objective_ratio=0.99,
                observed_ratio=0.95 if breached else 1,
                budget_remaining_ratio=0 if breached else 1,
                breached=breached,
                state=AksCommerceEvidenceState.COMPLETE,
                source_ref="source:synthetic",
            ),
        ),
        metrics=metrics,
        evidence_refs=("evidence:example",),
        evidence_gaps=gaps,
        deployment_changed=deployment_changed,
        rollout_stalled=rollout_stalled,
        prior_degraded=prior_degraded,
    )


def _required_metrics(
    *,
    active: tuple[float, float] = (0, 0),
    incoming: float = 10,
    completed: float = 10,
    dead_letters: tuple[float, float] = (0, 0),
) -> tuple[AksCommerceMetric, ...]:
    return (
        _metric("synthetic.order.availability", 1, 1),
        _metric("stream.active_messages", active[0], active[1]),
        _metric("stream.incoming_messages", incoming),
        _metric("stream.completed_messages", completed),
        _metric("stream.dead_letter_messages", dead_letters[0], dead_letters[1]),
    )


def test_growing_queue_is_order_backlog() -> None:
    projection = assess_aks_commerce(
        _frame(metrics=_required_metrics(active=(25, 5), incoming=30, completed=10))
    )

    assert projection.status is AksCommerceStatus.ORDER_BACKLOG
    assert projection.complete is True


def test_rollout_failure_with_backlog_is_deployment_regression() -> None:
    projection = assess_aks_commerce(
        _frame(
            metrics=_required_metrics(active=(25, 5), incoming=30, completed=10),
            breached=True,
            deployment_changed=True,
            rollout_stalled=True,
        )
    )

    assert projection.status is AksCommerceStatus.DEPLOYMENT_REGRESSION


def test_dead_letter_growth_has_priority_over_backlog() -> None:
    projection = assess_aks_commerce(
        _frame(
            metrics=_required_metrics(
                active=(25, 5),
                incoming=30,
                completed=10,
                dead_letters=(2, 0),
            )
        )
    )

    assert projection.status is AksCommerceStatus.DEAD_LETTER_GROWTH


def test_missing_required_metric_holds_instead_of_guessing() -> None:
    projection = assess_aks_commerce(
        _frame(metrics=(_metric("synthetic.order.availability", 1, 1),))
    )

    assert projection.status is AksCommerceStatus.HELD
    assert projection.complete is False
    assert "metric_missing.stream.active_messages" in projection.evidence_gaps


def test_prior_degradation_closes_only_on_complete_healthy_evidence() -> None:
    projection = assess_aks_commerce(_frame(metrics=_required_metrics(), prior_degraded=True))

    assert projection.status is AksCommerceStatus.RECOVERED


@pytest.mark.parametrize("prior_degraded", [False, True])
@pytest.mark.parametrize(
    ("availability", "ready", "breached"),
    [
        (0, False, True),
        (0, True, False),
        (1, False, False),
        (1, True, True),
    ],
)
def test_unproven_health_with_idle_queue_never_closes_incident(
    availability: float,
    ready: bool,
    breached: bool,
    prior_degraded: bool,
) -> None:
    frame = _frame(
        metrics=_required_metrics(incoming=0, completed=0), prior_degraded=prior_degraded
    )
    frame = replace(
        frame,
        metrics=(frame.metrics[0].model_copy(update={"current": availability}), *frame.metrics[1:]),
        workloads=(frame.workloads[0].model_copy(update={"ready": ready}),),
        slos=(frame.slos[0].model_copy(update={"breached": breached}),),
    )

    projection = assess_aks_commerce(frame)

    assert projection.status is AksCommerceStatus.HELD
    assert projection.complete is False
    assert projection.evidence_gaps == ("health_not_proven",)
    assert projection.proposed_action is None


def test_complete_healthy_evidence_remains_healthy() -> None:
    projection = assess_aks_commerce(_frame(metrics=_required_metrics()))

    assert projection.status is AksCommerceStatus.HEALTHY
    assert projection.complete is True
    assert projection.evidence_gaps == ()
