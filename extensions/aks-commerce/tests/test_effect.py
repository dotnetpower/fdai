from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts import (
    AksCommerceEvidenceState,
    AksCommerceProjection,
    AksCommerceSlo,
    AksCommerceStatus,
    AksCommerceWorkload,
)

from fdai_aks_commerce import verify_business_effect

NOW = datetime(2026, 9, 17, tzinfo=UTC)


def _projection(
    status: AksCommerceStatus,
    *,
    at: datetime,
    evidence_ref: str,
) -> AksCommerceProjection:
    return AksCommerceProjection(
        assessment_id=f"sha256:{'a' * 64}" if at == NOW else f"sha256:{'b' * 64}",
        service_id="order-fulfillment",
        status=status,
        summary=f"Order fulfillment state is {status.value}.",
        observed_at=at,
        window_start=at - timedelta(minutes=5),
        window_end=at,
        complete=True,
        synthetic=False,
        dependency_path=("order-processor",),
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
                observed_ratio=0.95 if status is AksCommerceStatus.ORDER_BACKLOG else 1,
                budget_remaining_ratio=0 if status is AksCommerceStatus.ORDER_BACKLOG else 1,
                breached=status is AksCommerceStatus.ORDER_BACKLOG,
                state=AksCommerceEvidenceState.COMPLETE,
                source_ref="source:synthetic",
            ),
        ),
        evidence_refs=(evidence_ref,),
    )


def test_distinct_later_recovery_evidence_closes_effect() -> None:
    before = _projection(AksCommerceStatus.ORDER_BACKLOG, at=NOW, evidence_ref="evidence:before")
    after = _projection(
        AksCommerceStatus.RECOVERED,
        at=NOW + timedelta(minutes=1),
        evidence_ref="evidence:after",
    )

    action = verify_business_effect(
        action_type="ops.scale-out",
        target_ref="resource:processor",
        action_run_ref="action-run:one",
        before=before,
        after=after,
    )

    assert action.effect_verified is True
    assert action.execution_authority is False


def test_reused_evidence_cannot_verify_effect() -> None:
    before = _projection(AksCommerceStatus.ORDER_BACKLOG, at=NOW, evidence_ref="evidence:one")
    after = _projection(
        AksCommerceStatus.RECOVERED,
        at=NOW + timedelta(minutes=1),
        evidence_ref="evidence:one",
    )

    with pytest.raises(ValueError, match="distinct"):
        verify_business_effect(
            action_type="ops.scale-out",
            target_ref="resource:processor",
            action_run_ref="action-run:one",
            before=before,
            after=after,
        )
