from dataclasses import replace
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
from fdai_aks_commerce.acceptance import (
    OrderAcceptanceEvidence,
    OrderAcceptanceIntent,
    OrderAcceptanceProbe,
)
from fdai_aks_commerce.effect import AcceptanceEffectExpectation, verify_order_acceptance_effect

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


def _acceptance_inputs() -> tuple[
    OrderAcceptanceIntent, OrderAcceptanceEvidence, AcceptanceEffectExpectation
]:
    intent = OrderAcceptanceIntent(
        policy_ref="policy:example",
        resource_ref="resource:deployment",
        service_resource_ref="resource:service",
        cluster_ref="cluster:example",
        namespace="example-store",
        deployment_name="order-api",
        deployment_uid="uid-order",
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=1),
    )
    evidence = OrderAcceptanceEvidence(
        resource_ref=intent.resource_ref,
        service_resource_ref=intent.service_resource_ref,
        cluster_ref=intent.cluster_ref,
        namespace=intent.namespace,
        deployment_name=intent.deployment_name,
        deployment_uid=intent.deployment_uid,
        resource_version="2",
        observed_at=NOW,
        desired_replicas=1,
        ready_replicas=1,
        ready_endpoints=1,
        probes=tuple(
            OrderAcceptanceProbe(
                f"probe:after-{index}", NOW - timedelta(seconds=2 - index), True, "authority:probe"
            )
            for index in range(2)
        ),
        kubernetes_evidence_ref="resource-observation:after",
        verification_ref="receipt:after",
        complete=True,
        sample=False,
    )
    expectation = AcceptanceEffectExpectation(
        action_run_ref="action-run:example",
        provider_receipt_ref="kubernetes:example",
        target_ref=intent.resource_ref,
        deployment_uid=intent.deployment_uid,
        replica_count=1,
        applied_at=NOW - timedelta(seconds=5),
        before_evidence_refs=("resource-observation:before", "probe:before"),
    )
    return intent, evidence, expectation


class _Source:
    def __init__(self, evidence: OrderAcceptanceEvidence) -> None:
        self.evidence = evidence

    async def observe(self, intent: OrderAcceptanceIntent) -> OrderAcceptanceEvidence:
        return self.evidence


class _Verifier:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted

    async def verify(self, *, verification_ref: str, evidence_digest: str) -> bool:
        assert verification_ref == "receipt:after"
        assert evidence_digest.startswith("sha256:")
        return self.accepted


async def test_acceptance_effect_requires_later_signed_resource_and_order_success() -> None:
    intent, evidence, expectation = _acceptance_inputs()
    result = await verify_order_acceptance_effect(
        expectation=expectation,
        intent=intent,
        source=_Source(evidence),
        verifier=_Verifier(),
        clock=lambda: NOW,
    )
    assert result.status == "verified"
    assert result.execution_authority is False
    assert result.evidence_ref is not None
    assert result.action_run_ref == expectation.action_run_ref


@pytest.mark.parametrize(
    "defect",
    ["early", "reused", "uid", "signature", "sample", "orders_fail", "overscaled", "expired"],
)
async def test_acceptance_effect_holds_or_fails_without_complete_positive_proof(
    defect: str,
) -> None:
    intent, evidence, expectation = _acceptance_inputs()
    now = NOW
    if defect == "early":
        expectation = replace(expectation, applied_at=NOW)
    elif defect == "reused":
        expectation = replace(expectation, before_evidence_refs=("probe:after-0",))
    elif defect == "uid":
        evidence = replace(evidence, deployment_uid="another-uid")
    elif defect == "sample":
        evidence = replace(evidence, sample=True)
    elif defect == "orders_fail":
        evidence = replace(
            evidence,
            desired_replicas=0,
            ready_replicas=0,
            ready_endpoints=0,
            probes=tuple(replace(probe, accepted=False) for probe in evidence.probes),
        )
    elif defect == "overscaled":
        evidence = replace(evidence, desired_replicas=2, ready_replicas=2)
    elif defect == "expired":
        now = intent.valid_until
    result = await verify_order_acceptance_effect(
        expectation=expectation,
        intent=intent,
        source=_Source(evidence),
        verifier=_Verifier(defect != "signature"),
        clock=lambda: now,
    )
    assert result.status == ("not_recovered" if defect in {"orders_fail", "overscaled"} else "held")
    assert result.execution_authority is False
