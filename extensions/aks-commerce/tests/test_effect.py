from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai.core.executor.post_release_closure_store import (
    PostReleaseClosureStoreReceipt,
    PostReleaseClosureWriteDecision,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import AuthoritativeSinkState
from fdai.core.executor.testing_safeguard_lifecycle import (
    InMemoryIdempotencyReservationStore,
    InMemoryPostReleaseClosureStore,
    InMemoryTargetDispatchFenceStore,
)
from fdai.runtime.isolated_executor_receipt_journal import BoundCommandCorrelation
from fdai.shared.contracts.models import (
    Action,
    ExecutionPath,
    ExecutorEffectReceipt,
    Mode,
    Operation,
    SafeguardBoundExecutorCommand,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts import (
    AksCommerceEvidenceState,
    AksCommerceProjection,
    AksCommerceSlo,
    AksCommerceStatus,
    AksCommerceWorkload,
)
from tests.core.executor.test_direct_api_executor import _action
from tests.core.executor.test_post_release_closure import _initial_plan

from fdai_aks_commerce import verify_business_effect
from fdai_aks_commerce.acceptance import (
    OrderAcceptanceEvidence,
    OrderAcceptanceIntent,
    OrderAcceptanceProbe,
    evaluate_order_acceptance,
)
from fdai_aks_commerce.acceptance_closure import (
    CLOSURE_PREFIX,
    AcceptanceClosureReconciler,
    AcceptanceClosureStore,
    AcceptanceEffectObserver,
)
from fdai_aks_commerce.acceptance_material import (
    AcceptanceDispatchMaterial,
    StoredAcceptanceDispatchMaterials,
)
from fdai_aks_commerce.acceptance_receipts import (
    REVOCATION_PREFIX,
    AcceptanceTrustBinding,
    StoredOrderAcceptanceReceiptVerifier,
    acceptance_receipt_payload,
)
from fdai_aks_commerce.acceptance_store import retain_order_acceptance
from fdai_aks_commerce.effect import AcceptanceEffectExpectation, verify_order_acceptance_effect

NOW = datetime(2026, 9, 17, tzinfo=UTC)


class _ClosureStore:
    production_eligible = False

    def __init__(self) -> None:
        self.plans: list[Any] = []

    async def write(self, plan: Any) -> PostReleaseClosureStoreReceipt:
        self.plans.append(plan)
        return PostReleaseClosureStoreReceipt.create(
            decision=PostReleaseClosureWriteDecision.APPLIED,
            record=plan.record,
            persisted_at=plan.record.closed_at,
            read_back_at=plan.record.closed_at,
            store_receipt_digest="sha256:" + "a" * 64,
        )

    async def read(self, closure_key: str) -> Any:
        return next(
            (
                plan.record
                for plan in reversed(self.plans)
                if plan.record.identity.closure_key == closure_key
            ),
            None,
        )

    async def read_receipt(self, closure_key: str) -> None:
        return None


@pytest.mark.parametrize(
    "defect", [None, "other_target", "missing_material", "uid", "different_action", "rebound"]
)
async def test_acceptance_retains_only_original_owned_closure(
    defect: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent, _, _ = _acceptance_inputs()
    at = NOW - timedelta(seconds=10)
    target = "resource:other" if defect == "other_target" else intent.resource_ref
    action = Action.model_validate(
        {
            **_action(target=target, mode=Mode.ENFORCE).model_dump(mode="json"),
            "action_type": "ops.scale-out",
            "operation": Operation.SCALE,
            "created_at": at,
            "params": {"target_uid": intent.deployment_uid, "replica_count": 1},
        }
    )
    monkeypatch.setattr(
        "tests.core.executor.test_safeguard_dispatch_checkpoint._action", lambda **_kwargs: action
    )
    plan = _initial_plan(
        sink_state=AuthoritativeSinkState.ACCEPTED, target_resource_ref=target, now=at
    )
    source = InMemoryStateStore()
    stored = action
    if defect == "uid":
        stored = action.model_copy(update={"params": {**action.params, "target_uid": "other-uid"}})
    if defect == "different_action":
        stored = action.model_copy(update={"executor_identity_ref": "identity:other"})
    if defect != "missing_material":
        await StoredAcceptanceDispatchMaterials(source).retain(
            AcceptanceDispatchMaterial(
                stored.model_dump_json(), "analyzer:example", "anomaly:example"
            )
        )
    delegate = _ClosureStore()
    wrapper = AcceptanceClosureStore(delegate, source, intent)
    key = CLOSURE_PREFIX + plan.record.identity.closure_key
    if defect == "rebound":
        await source.write_state(key, {"plan_json": "different"})
    if defect in {"uid", "different_action", "rebound"}:
        with pytest.raises(ValueError):
            await wrapper.write(plan)
        assert not delegate.plans
        return
    result = await wrapper.write(plan)
    assert result.record == plan.record
    assert delegate.plans == [plan]
    assert wrapper.production_eligible is False
    assert await wrapper.read(plan.record.identity.closure_key) == plan.record
    assert await wrapper.read_receipt(plan.record.identity.closure_key) is None
    retained = await source.read_state(key)
    if defect in {"other_target", "missing_material"}:
        assert retained is None
    else:
        assert retained is not None and retained["action_json"] == action.model_dump_json()
        await wrapper.write(plan)
        assert await source.read_state(key) == retained


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
    [
        None,
        "receipt",
        "not_published",
        "signature",
        "old",
        "uid",
        "orders",
        "missing_context",
        "release_unknown",
    ],
)
async def test_independent_acceptance_effect_reconciles_exact_atomic_closure(
    defect: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fdai.shared.providers.resource_lock import ResourceLockReleaseState

    intent, observed, _ = _acceptance_inputs()
    at = NOW - timedelta(seconds=10)
    action = Action.model_validate(
        {
            **_action(target=intent.resource_ref, mode=Mode.ENFORCE).model_dump(mode="json"),
            "action_type": "ops.scale-out",
            "operation": Operation.SCALE,
            "created_at": at,
            "params": {"target_uid": intent.deployment_uid, "replica_count": 1},
        }
    )
    monkeypatch.setattr(
        "tests.core.executor.test_safeguard_dispatch_checkpoint._action", lambda **_kwargs: action
    )
    plan = _initial_plan(
        sink_state=AuthoritativeSinkState.ACCEPTED,
        target_resource_ref=intent.resource_ref,
        now=at,
        release_state=ResourceLockReleaseState.UNKNOWN
        if defect == "release_unknown"
        else ResourceLockReleaseState.RELEASED,
    )
    store = InMemoryStateStore()
    reservations = InMemoryIdempotencyReservationStore()
    fences = InMemoryTargetDispatchFenceStore()
    reservations._records[plan.prior_reservation_record.identity.idempotency_key] = (
        plan.prior_reservation_record
    )
    fences._records[plan.prior_fence_record.identity.target_digest] = plan.prior_fence_record
    atomic = InMemoryPostReleaseClosureStore(reservation_store=reservations, fence_store=fences)
    material = AcceptanceDispatchMaterial(
        action.model_dump_json(),
        "analyzer:example",
        "anomaly:example",
        evidence_refs=("probe:before", "resource:before"),
    )
    await StoredAcceptanceDispatchMaterials(store).retain(material)
    closures = AcceptanceClosureStore(atomic, store, intent)
    await closures.write(plan)
    command = SafeguardBoundExecutorCommand.from_action(
        command_id=UUID(int=100),
        action=action,
        execution_path=ExecutionPath.DIRECT_API,
        attempt=plan.record.identity.reservation_attempt,
        issued_at=at,
        deadline_at=NOW + timedelta(seconds=30),
        safeguard_proof_bundle_digest=plan.pre_release_record.bundle.bundle_digest,
        source_revision=plan.pre_release_record.bundle.source_revision,
    )
    correlation = BoundCommandCorrelation(
        command=command,
        registration_id=UUID(int=101),
        reservation_identity_digest=plan.record.identity.reservation_identity_digest,
        evidence_identity_digest=plan.record.identity.evidence_identity_digest,
        target_digest=plan.record.identity.target_digest,
        target_fence_generation=plan.record.identity.target_fence_generation,
    )
    receipt = ExecutorEffectReceipt(
        schema_version="1.1.0",
        receipt_id=UUID(int=102),
        command_id=command.command_id,
        action_id=action.action_id,
        idempotency_key=command.idempotency_key,
        attempt=command.attempt,
        action_payload_digest=command.action_payload_digest,
        requested_mode=Mode.ENFORCE,
        status="dispatched",
        executor_instance_id="executor:example",
        received_at=at,
        completed_at=at + timedelta(seconds=2),
        effect_applied=True,
        provider_receipt_ref="provider:example",
        audit_ref=f"action:{action.action_id}",
        safeguard_proof_bundle_digest=command.safeguard_proof_bundle_digest,
    )
    command_key = "runtime:isolated-executor:command:" + str(command.command_id)
    await store.write_state(command_key, correlation.model_dump(mode="json"))
    await StoredAcceptanceDispatchMaterials(store).link_command(action, str(command.command_id))
    receipt_payload = receipt.model_dump(mode="json")
    if defect == "receipt":
        receipt_payload["action_payload_digest"] = "sha256:" + "0" * 64
    await store.write_state(
        "runtime:isolated-executor:terminal-receipt:" + str(command.command_id), receipt_payload
    )
    if defect == "not_published":
        await store.write_state(
            "runtime:isolated-executor:not-published:" + str(command.command_id),
            {"not_published": True},
        )
    if defect == "missing_context":
        await store.write_state(CLOSURE_PREFIX + correlation.closure_key, {})
    key = Ed25519PrivateKey.generate()
    verifier = StoredOrderAcceptanceReceiptVerifier(
        store=store,
        intent=intent,
        executor_identity="executor:example",
        trust={
            "example": AcceptanceTrustBinding(
                "issuer:example", "observer:example", key.public_key()
            )
        },
        clock=lambda: NOW,
    )
    observation = replace(observed, verification_ref="sha256:" + "e" * 64)
    if defect == "old":
        observation = replace(
            observation,
            observed_at=at,
            probes=tuple(
                replace(probe, observed_at=at - timedelta(seconds=3 - index))
                for index, probe in enumerate(observation.probes)
            ),
        )
    if defect == "uid":
        observation = replace(observation, deployment_uid="other-uid")
    if defect == "orders":
        observation = replace(
            observation,
            probes=tuple(replace(probe, accepted=False) for probe in observation.probes),
        )
    assessment = evaluate_order_acceptance(intent, observation, now=NOW, window_seconds=30)
    attestation = {
        "type": "aks-commerce.acceptance-receipt",
        "schema_version": "1.0.0",
        "verification_ref": observation.verification_ref,
        "evidence_digest": assessment.evidence_digest,
        "policy_ref": intent.policy_ref,
        "resource_ref": intent.resource_ref,
        "issuer": "issuer:example",
        "source_identity": "observer:example",
        "key_id": "example",
        "verified_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(seconds=20)).isoformat(),
        "authorization_refs": ["authority:probe"],
        "signature": "",
    }
    attestation["signature"] = key.sign(acceptance_receipt_payload(attestation)).hex()
    await store.write_state(
        REVOCATION_PREFIX + "example",
        {
            "key_id": "example",
            "revoked": False,
            "valid_until": (NOW + timedelta(seconds=20)).isoformat(),
        },
    )
    if assessment.status == "held":
        with pytest.raises(ValueError):
            await retain_order_acceptance(
                store=store,
                verifier=verifier,
                intent=intent,
                evidence=observation,
                receipt=attestation,
                now=NOW,
            )
    else:
        await retain_order_acceptance(
            store=store,
            verifier=verifier,
            intent=intent,
            evidence=observation,
            receipt=attestation,
            now=NOW,
        )
    if defect == "signature":
        await store.write_state(
            REVOCATION_PREFIX + "example",
            {
                "key_id": "example",
                "revoked": True,
                "valid_until": (NOW + timedelta(seconds=20)).isoformat(),
            },
        )
    reconciler = AcceptanceClosureReconciler(closures, store, intent, verifier, lambda: NOW)
    if defect is not None:
        with pytest.raises(ValueError):
            await reconciler.reconcile(str(command.command_id))
        assert (await atomic.read(correlation.closure_key)).outcome.value == "quarantined"
        assert len(atomic.audit_entries) == 1
        return
    resolved_incidents: list[dict[str, object]] = []

    async def resolve_verified_incident(**values: object) -> str:
        resolved_incidents.append(values)
        return "incident:example"

    observer = AcceptanceEffectObserver(reconciler, resolve_verified_incident)
    trigger = {
        "producer_principal": "Thor",
        "state": "execution_unknown",
        "shadow_mode": False,
        "action_id": str(action.action_id),
        "action_type": action.action_type,
        "resource_id": action.target_resource_ref,
        "correlation_id": material.correlation_id,
        "action_idempotency_key": material.action_run_idempotency_key,
        "params": action.params,
    }
    assert not await observer.handle({**trigger, "resource_id": "resource:other"})
    assert not await observer.handle({**trigger, "shadow_mode": True})
    with pytest.raises(ValueError):
        await observer.handle({**trigger, "producer_principal": "Var"})
    with pytest.raises(ValueError):
        await observer.handle({**trigger, "correlation_id": "analyzer:other"})
    verified_event = await observer.handle(trigger)
    assert isinstance(verified_event, Mapping)
    assert await observer.resolve_incident(verified_event)
    digest = (await atomic.read(correlation.closure_key)).record_digest
    assert (await atomic.read(correlation.closure_key)).outcome.value == "resolved"
    assert len(atomic.audit_entries) == 2
    assert (await reconciler.reconcile(str(command.command_id))).record_digest == digest
    replay_event = await observer.handle(trigger)
    assert isinstance(replay_event, Mapping)
    assert await observer.resolve_incident(replay_event)
    assert len(atomic.audit_entries) == 2
    historical = replace(reconciler, clock=lambda: NOW + timedelta(minutes=3))
    assert (await historical.reconcile(str(command.command_id))).record_digest == digest
    assert len(atomic.audit_entries) == 2
    assert resolved_incidents == [
        {
            "action_idempotency_key": material.action_run_idempotency_key,
            "correlation_id": material.correlation_id,
            "resource_id": intent.resource_ref,
            "event_type": "analyzer.aks_commerce.order_acceptance_unavailable.observed",
            "verified_at": observation.observed_at,
        },
        {
            "action_idempotency_key": material.action_run_idempotency_key,
            "correlation_id": material.correlation_id,
            "resource_id": intent.resource_ref,
            "event_type": "analyzer.aks_commerce.order_acceptance_unavailable.observed",
            "verified_at": observation.observed_at,
        },
    ]


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
