import copy
import json
import ssl
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai.agents import (
    AnomalyActionCandidate,
    Forseti,
    Heimdall,
    Huginn,
    InMemoryBus,
    load_pantheon,
    read_current_action_approval,
)
from fdai.agents.thor import ActionRun, ActionRunState, Thor
from fdai.agents.var import Var
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.risk_gate.gate import ActionModeRecord, ActionPromotionRegistry, RiskGate
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.delivery.analyzer_tick import AnalyzerTarget
from fdai.delivery.persistence.postgres_analyzer_publication import (
    PostgresAnalyzerPublicationLedger,
)
from fdai.runtime.isolated_executor_client import EventBusDirectApiExecutionClient
from fdai.runtime.safeguard_isolated_executor import SafeguardBoundEventBusDirectApiExecutionClient
from fdai.shared.contracts.models import (
    Action,
    Autonomy,
    CeilingRole,
    Mode,
    OntologyActionType,
    Operation,
    Severity,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.core.executor.test_direct_api_executor import _action as _direct_action
from tests.core.executor.test_executor import _rule
from tests.core.executor.test_safeguard_lifecycle_coordinator import _NOW, _coordinator
from tests.delivery.publication_store import ConditionalStore
from tests.runtime.test_safeguard_lifecycle_wiring import _published_command

from fdai_aks_commerce.acceptance import (
    OrderAcceptanceEvidence,
    OrderAcceptanceIntent,
    OrderAcceptanceProbe,
    evaluate_order_acceptance,
)
from fdai_aks_commerce.acceptance_action import (
    ACCEPTANCE_SIGNAL,
    AcceptanceAnomalyActionSource,
    AcceptanceGuardedExecutor,
)
from fdai_aks_commerce.acceptance_authority import AcceptanceCurrentAuthority
from fdai_aks_commerce.acceptance_dispatch import AcceptanceIsolatedDispatch
from fdai_aks_commerce.acceptance_kubernetes import KubernetesOrderAcceptanceReader
from fdai_aks_commerce.acceptance_material import (
    AcceptanceDispatchMaterial,
    StoredAcceptanceDispatchMaterials,
)
from fdai_aks_commerce.acceptance_preparation import PreparedAcceptanceSource
from fdai_aks_commerce.acceptance_receipts import (
    RECEIPT_PREFIX,
    REVOCATION_PREFIX,
    AcceptanceTrustBinding,
    StoredOrderAcceptanceReceiptVerifier,
    acceptance_receipt_payload,
)
from fdai_aks_commerce.acceptance_runtime import (
    AcceptanceRuntimeConfig,
    build_acceptance_analyzer,
    build_acceptance_runner,
)
from fdai_aks_commerce.acceptance_store import StoredOrderAcceptanceSource, retain_order_acceptance

NOW = datetime(2026, 9, 17, tzinfo=UTC)
REFERENCE = "sha256:" + "a" * 64
DIGEST = "sha256:" + "b" * 64


def _intent() -> OrderAcceptanceIntent:
    return OrderAcceptanceIntent(
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


async def _receipt() -> tuple[
    InMemoryStateStore, StoredOrderAcceptanceReceiptVerifier, dict[str, Any]
]:
    key = Ed25519PrivateKey.generate()
    record: dict[str, Any] = {
        "type": "aks-commerce.acceptance-receipt",
        "schema_version": "1.0.0",
        "verification_ref": REFERENCE,
        "evidence_digest": DIGEST,
        "policy_ref": "policy:example",
        "resource_ref": "resource:deployment",
        "issuer": "observer:verifier",
        "source_identity": "observer:collector",
        "key_id": "example-key",
        "verified_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(seconds=20)).isoformat(),
        "authorization_refs": ["authorization:example"],
        "signature": "",
    }
    record["signature"] = key.sign(acceptance_receipt_payload(record)).hex()
    store = InMemoryStateStore()
    await store.write_state(RECEIPT_PREFIX + REFERENCE, record)
    await store.write_state(
        REVOCATION_PREFIX + "example-key",
        {
            "key_id": "example-key",
            "revoked": False,
            "valid_until": (NOW + timedelta(seconds=20)).isoformat(),
        },
    )
    verifier = StoredOrderAcceptanceReceiptVerifier(
        store=store,
        intent=_intent(),
        executor_identity="identity:executor",
        trust={
            "example-key": AcceptanceTrustBinding(
                "observer:verifier",
                "observer:collector",
                key.public_key(),
            )
        },
        clock=lambda: NOW,
    )
    return store, verifier, record


async def test_retained_signature_requires_exact_evidence_and_current_trust() -> None:
    _, verifier, _ = await _receipt()
    assert await verifier.verify(verification_ref=REFERENCE, evidence_digest=DIGEST)
    assert not await verifier.verify(
        verification_ref=REFERENCE, evidence_digest="sha256:" + "c" * 64
    )


@pytest.mark.parametrize(
    "defect",
    ["signature", "target", "expired", "future", "naive", "extra", "issuer", "authorization"],
)
async def test_invalid_signed_receipt_is_not_trusted(defect: str) -> None:
    store, verifier, record = await _receipt()
    updates = {
        "signature": {"signature": "0" * 128},
        "target": {"resource_ref": "resource:other"},
        "expired": {"expires_at": NOW.isoformat()},
        "future": {"verified_at": (NOW + timedelta(seconds=1)).isoformat()},
        "naive": {"verified_at": NOW.replace(tzinfo=None).isoformat()},
        "extra": {"execution_authority": True},
        "issuer": {"issuer": "identity:executor"},
        "authorization": {"authorization_refs": []},
    }
    await store.write_state(RECEIPT_PREFIX + REFERENCE, {**record, **updates[defect]})
    assert not await verifier.verify(verification_ref=REFERENCE, evidence_digest=DIGEST)


class _Auth:
    async def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer test-only"}


def _resources() -> dict[str, Any]:
    return {
        "deployment": {
            "kind": "Deployment",
            "metadata": {
                "uid": "uid-order",
                "name": "order-api",
                "namespace": "example-store",
                "resourceVersion": "1",
                "generation": 1,
            },
            "spec": {"replicas": 0, "template": {"metadata": {"labels": {"app": "order-api"}}}},
            "status": {"observedGeneration": 1},
        },
        "service": {
            "kind": "Service",
            "metadata": {
                "uid": "uid-service",
                "name": "order-api",
                "namespace": "example-store",
                "resourceVersion": "1",
            },
            "spec": {"selector": {"app": "order-api"}},
        },
        "slices": {"metadata": {}, "items": []},
        "hpas": {"metadata": {}, "items": []},
    }


def _reader(resources: dict[str, Any], calls: list[str]) -> KubernetesOrderAcceptanceReader:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "kubernetes.example.com"
        calls.append(request.url.path)
        if "/deployments/" in request.url.path:
            value = copy.deepcopy(resources["deployment"])
            if resources.get("race") and calls.count(request.url.path) > 1:
                value["metadata"]["resourceVersion"] = "2"
        elif "/services/" in request.url.path:
            value = resources["service"]
        elif request.url.path.endswith("endpointslices"):
            assert request.url.params["labelSelector"] == "kubernetes.io/service-name=order-api"
            value = resources["slices"]
        elif "/pods/" in request.url.path:
            value = resources["pod"]
        elif "/replicasets/" in request.url.path:
            value = resources["replica"]
        else:
            assert request.url.path.endswith("horizontalpodautoscalers")
            value = resources["hpas"]
        return httpx.Response(200, json=value)

    return KubernetesOrderAcceptanceReader(
        api_server="https://kubernetes.example.com",
        intent=_intent(),
        service_name="order-api",
        service_uid="uid-service",
        auth=_Auth(),
        tls=ssl.create_default_context(),
        transport=httpx.MockTransport(handler),
        clock=lambda: NOW,
    )


async def test_exact_zero_replica_snapshot_reads_without_mutating() -> None:
    calls: list[str] = []
    snapshot = await _reader(_resources(), calls).read()
    assert snapshot.desired_replicas == snapshot.ready_replicas == snapshot.ready_endpoints == 0
    assert snapshot.hpa_managed is False
    assert snapshot.resource_version == "1"
    assert snapshot.evidence_ref().startswith("sha256:")
    assert len(calls) == 6


@pytest.mark.parametrize(
    "dispatch_state",
    [
        "current",
        "revoked",
        "changed",
        "shadow",
        "audit_down",
        "expired",
        "source_drift",
        "demoted",
        "safety_held",
        "unpromoted",
        "policy_unavailable",
        "policy_expired",
    ],
)
async def test_signed_observation_survives_store_reconstruction_and_replay(
    dispatch_state: str,
) -> None:
    store, _, template = await _receipt()
    evidence = OrderAcceptanceEvidence(
        resource_ref="resource:deployment",
        service_resource_ref="resource:service",
        cluster_ref="cluster:example",
        namespace="example-store",
        deployment_name="order-api",
        deployment_uid="uid-order",
        resource_version="1",
        observed_at=NOW,
        desired_replicas=0,
        ready_replicas=0,
        ready_endpoints=0,
        probes=tuple(
            OrderAcceptanceProbe(
                evidence_ref=f"probe:example-{index}",
                observed_at=NOW - timedelta(seconds=2 - index),
                accepted=False,
                authorization_ref="authorization:example",
            )
            for index in range(2)
        ),
        kubernetes_evidence_ref="observation:example",
        verification_ref=REFERENCE,
        complete=True,
        sample=False,
        maintenance_active=False,
        hpa_managed=False,
        competing_writer=False,
    )
    assessment = evaluate_order_acceptance(_intent(), evidence, now=NOW, window_seconds=30)
    key = Ed25519PrivateKey.generate()
    receipt = {**template, "evidence_digest": assessment.evidence_digest}
    receipt["signature"] = key.sign(acceptance_receipt_payload(receipt)).hex()
    store = InMemoryStateStore()
    await store.write_state(
        REVOCATION_PREFIX + "example-key",
        {
            "key_id": "example-key",
            "revoked": False,
            "valid_until": (NOW + timedelta(seconds=20)).isoformat(),
        },
    )
    verifier = StoredOrderAcceptanceReceiptVerifier(
        store=store,
        intent=_intent(),
        executor_identity="identity:executor",
        trust={
            "example-key": AcceptanceTrustBinding(
                "observer:verifier", "observer:collector", key.public_key()
            )
        },
        clock=lambda: NOW,
    )
    first = await retain_order_acceptance(
        store=store,
        verifier=verifier,
        intent=_intent(),
        evidence=evidence,
        receipt=receipt,
        now=NOW,
    )
    replay = await retain_order_acceptance(
        store=store,
        verifier=verifier,
        intent=_intent(),
        evidence=evidence,
        receipt=receipt,
        now=NOW,
    )
    assert first == replay == assessment.evidence_digest
    assert await StoredOrderAcceptanceSource(store).observe(_intent()) == evidence
    assert await verifier.verify(verification_ref=REFERENCE, evidence_digest=first)
    config = AcceptanceRuntimeConfig(
        _intent(),
        {
            "example-key": AcceptanceTrustBinding(
                "observer:verifier", "observer:collector", key.public_key()
            )
        },
        "identity:executor",
        Severity.HIGH,
        5,
    )
    provider = InMemoryEventBus()
    current_time = [NOW]
    runner = build_acceptance_runner(
        config=config,
        store=store,
        event_bus=provider,
        publication_ledger=PostgresAnalyzerPublicationLedger(store=ConditionalStore()),
        topic="fdai.events",
        clock=lambda: NOW,
    )
    targets = (
        AnalyzerTarget(resource_ref="resource:deployment", resource_kind="kubernetes.deployment"),
    )
    report = await runner.run_once(targets)
    assert report.published == 1
    assert not report.failed
    assert (await runner.run_once(targets)).duplicates_suppressed == 1
    source = AcceptanceAnomalyActionSource(
        intent=config.intent,
        analyzer=build_acceptance_analyzer(
            config=config, store=store, clock=lambda: current_time[0]
        ),
    )
    calls: list[dict[str, Any]] = []

    async def external_effect(context: dict[str, Any]) -> bool:
        original = await materials.read(context["run"].action_id)
        assert original is not None
        await current_authority(original.action(), context)
        people = await read_current_action_approval(
            store=store,
            action_run=context["run"].to_dict(),
            can_approve=lambda person, action: (
                person in {"reviewer@example.com", "reviewer2@example.com"}
                and action == "ops.scale-out"
            ),
            clock=lambda: current_time[0],
        )
        assert len(people) == 2
        calls.append(dict(context["run"].params))
        return True

    agent_bus = InMemoryBus(registry=load_pantheon())
    thor = Thor(
        bus=agent_bus,
        executor=AcceptanceGuardedExecutor(
            source=source, execute=external_effect, clock=lambda: current_time[0]
        ),
        saga_available=dispatch_state != "audit_down",
    )
    thor.set_shadow(dispatch_state == "shadow")
    var = Var(bus=agent_bus, state_store=store)
    action_type = OntologyActionType.model_validate(
        yaml.safe_load(
            (
                Path(__file__).resolve().parents[3] / "rule-catalog/action-types/ops.scale-out.yaml"
            ).read_text()
        )
    )
    promotions = ActionPromotionRegistry()
    if dispatch_state != "unpromoted":
        promotions.restore("ops.scale-out", ActionModeRecord("ops.scale-out", Mode.ENFORCE))
    materials = StoredAcceptanceDispatchMaterials(store)

    async def refresh_policy() -> None:
        if dispatch_state == "policy_unavailable":
            raise RuntimeError("synthetic policy read is unavailable")
        if dispatch_state == "policy_expired":
            current_time[0] = NOW + timedelta(seconds=31)
        return None

    builder = ActionBuilder({action_type.name: action_type})
    rule = _rule().model_copy(update={"remediates": "ops.scale-out"})
    risk_gate = RiskGate(registry=promotions)
    prepared_source = PreparedAcceptanceSource(
        source=source,
        builder=builder,
        rule=rule,
        risk_gate=risk_gate,
        materials=materials,
        refresh_policy=refresh_policy,
        clock=lambda: current_time[0],
    )
    current_authority = AcceptanceCurrentAuthority(
        store=store,
        builder=builder,
        rule=rule,
        risk_gate=risk_gate,
        risk_table=load_risk_table(
            Path(__file__).resolve().parents[3] / "rule-catalog/risk-classification.yaml"
        ),
        principal_role=CeilingRole.APPROVER,
        can_approve=lambda person, action: (
            person in {"reviewer@example.com", "reviewer2@example.com"}
            and action == "ops.scale-out"
        ),
        refresh_policy=refresh_policy,
        safety_held=lambda: dispatch_state == "safety_held",
        clock=lambda: current_time[0],
    )
    forseti = Forseti(
        bus=agent_bus,
        anomaly_action_sources={ACCEPTANCE_SIGNAL: prepared_source},
        test_context_clock=lambda: NOW,
    )
    heimdall = Heimdall(bus=agent_bus, rate_threshold=1)
    huginn = Huginn(bus=agent_bus)
    agent_bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    agent_bus.subscribe("object.anomaly", "Forseti", forseti.on_typed_message)
    agent_bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    agent_bus.subscribe("object.action-run", "Var", var.on_typed_message)
    agent_bus.subscribe("object.approval", "Thor", thor.on_typed_message)
    async for envelope in provider.subscribe("fdai.events", "acceptance-integration"):
        await huginn.ingest(dict(envelope.payload))
    assert len(thor.action_runs) == 1
    run = next(iter(thor.action_runs.values()))
    assert run.state.value == "hil_pending"
    if dispatch_state in {"policy_unavailable", "policy_expired"}:
        assert run.action_id is None
        assert run.shadow_mode
        assert not calls
        return
    assert run.action_id is not None
    material = await materials.read(run.action_id)
    assert material is not None
    assert material.action().params == run.params
    assert material.correlation_id == run.correlation_id
    assert run.quorum_required == 2
    original_verdict = agent_bus.messages_on("object.verdict")[-1].payload
    repeated = await prepared_source.prepare(original_verdict)
    assert repeated.action_id == run.action_id
    assert await materials.read(run.action_id) == material
    with pytest.raises(ValueError, match="evidence changed"):
        await prepared_source.prepare(
            {**original_verdict, "params": {**run.params, "replica_count": 10}}
        )
    if dispatch_state == "unpromoted":
        assert material.action().mode is Mode.SHADOW
        assert run.shadow_mode
    if dispatch_state == "demoted":
        promotions.restore("ops.scale-out", None)
    assert not calls
    assert assessment.proposal is not None
    assert run.params == dict(assessment.proposal.arguments)
    if dispatch_state == "revoked":
        await store.write_state(
            REVOCATION_PREFIX + "example-key",
            {
                "key_id": "example-key",
                "revoked": True,
                "valid_until": (NOW + timedelta(seconds=20)).isoformat(),
            },
        )
    elif dispatch_state == "changed":
        run.params["replica_count"] = 2
    elif dispatch_state == "expired":
        current_time[0] = NOW + timedelta(seconds=31)
    elif dispatch_state == "source_drift":
        current_time[0] = NOW + timedelta(seconds=1)
        changed_evidence = replace(
            evidence,
            resource_version="2",
            observed_at=current_time[0],
            verification_ref="sha256:" + "c" * 64,
        )
        changed_assessment = evaluate_order_acceptance(
            _intent(),
            changed_evidence,
            now=current_time[0],
            window_seconds=30,
        )
        changed_receipt = {
            **receipt,
            "evidence_digest": changed_assessment.evidence_digest,
            "verification_ref": changed_evidence.verification_ref,
        }
        changed_receipt["signature"] = key.sign(acceptance_receipt_payload(changed_receipt)).hex()
        await retain_order_acceptance(
            store=store,
            verifier=verifier,
            intent=_intent(),
            evidence=changed_evidence,
            receipt=changed_receipt,
            now=current_time[0],
        )
    with pytest.raises(ValueError, match="no self-approval"):
        await var.decide(run.correlation_id, approver="Heimdall", decision="approve")
    approval = await var.decide(
        run.correlation_id, approver="reviewer@example.com", decision="approve"
    )
    assert not calls
    approval = await var.decide(
        run.correlation_id, approver="reviewer2@example.com", decision="approve"
    )
    assert approval is not None
    if dispatch_state == "changed":
        with pytest.raises(ValueError, match="approval identity"):
            await thor.on_typed_message("object.approval", approval)
    else:
        await thor.on_typed_message("object.approval", approval)
    assert len(calls) == (1 if dispatch_state == "current" else 0)
    if calls:
        assert calls[0] == dict(assessment.proposal.arguments)
        assert run.outcome == "command_accepted_verification_pending"
        with pytest.raises(PermissionError, match="no longer eligible"):
            await read_current_action_approval(
                store=store,
                action_run=run.to_dict(),
                can_approve=lambda _person, _action: False,
                clock=lambda: NOW,
            )
        assert approval is not None
        from fdai.agents._framework.var_ticket_identity import approval_state_key

        approval_key = approval_state_key(
            run.correlation_id, "final", approval["action_run_identity"]
        )
        saved = dict(await store.read_state(approval_key) or {})
        for updates in (
            {"state": "rejected"},
            {"approvers": ["reviewer@example.com"]},
            {"approvers": ["reviewer@example.com", "reviewer@example.com"]},
            {"approvers": ["heimdall", "reviewer@example.com"]},
            {"params": {"replica_count": 99}},
            {"producer_principal": "Thor"},
        ):
            await store.write_state(
                approval_key, {**saved, "approval": {**saved["approval"], **updates}}
            )
            with pytest.raises(ValueError):
                await read_current_action_approval(
                    store=store,
                    action_run=run.to_dict(),
                    can_approve=lambda _person, _action: True,
                    clock=lambda: NOW,
                )
        await store.write_state(approval_key, saved)
    if dispatch_state in {"expired", "revoked", "source_drift", "demoted", "safety_held"}:
        assert run.state.value == "failed"
    await store.write_state(RECEIPT_PREFIX + REFERENCE, {**receipt, "signature": "0" * 128})
    assert not await verifier.verify(verification_ref=REFERENCE, evidence_digest=first)
    if dispatch_state != "source_drift":
        assert (await runner.run_once(targets)).failed


@pytest.mark.parametrize("defect", ["uid", "generation", "selector", "truncated", "race", "status"])
async def test_incomplete_or_conflicting_kubernetes_snapshot_is_rejected(defect: str) -> None:
    resources = _resources()
    if defect == "uid":
        resources["deployment"]["metadata"]["uid"] = "another-uid"
    elif defect == "generation":
        resources["deployment"]["status"]["observedGeneration"] = 0
    elif defect == "selector":
        resources["service"]["spec"]["selector"] = {"app": "another"}
    elif defect == "truncated":
        resources["slices"]["metadata"]["continue"] = "next-page"
    elif defect == "status":
        resources["deployment"].pop("status")
    else:
        resources["race"] = True
    with pytest.raises(ValueError):
        await _reader(resources, []).read()


def _ready_resources() -> dict[str, Any]:
    resources = _resources()
    resources["deployment"]["spec"]["replicas"] = 1
    resources["deployment"]["status"]["readyReplicas"] = 1
    resources["slices"]["items"] = [
        {
            "kind": "EndpointSlice",
            "metadata": {
                "namespace": "example-store",
                "labels": {"kubernetes.io/service-name": "order-api"},
                "ownerReferences": [
                    {
                        "kind": "Service",
                        "name": "order-api",
                        "uid": "uid-service",
                        "controller": True,
                    }
                ],
            },
            "endpoints": [
                {
                    "conditions": {"ready": True},
                    "targetRef": {
                        "kind": "Pod",
                        "namespace": "example-store",
                        "name": "order-api-pod",
                        "uid": "uid-pod",
                    },
                }
            ],
        }
    ]
    resources["pod"] = {
        "kind": "Pod",
        "metadata": {
            "namespace": "example-store",
            "name": "order-api-pod",
            "uid": "uid-pod",
            "ownerReferences": [
                {"kind": "ReplicaSet", "name": "order-api-rs", "uid": "uid-rs", "controller": True}
            ],
        },
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }
    resources["replica"] = {
        "kind": "ReplicaSet",
        "metadata": {
            "namespace": "example-store",
            "name": "order-api-rs",
            "uid": "uid-rs",
            "ownerReferences": [
                {"kind": "Deployment", "name": "order-api", "uid": "uid-order", "controller": True}
            ],
        },
    }
    return resources


async def test_ready_endpoint_requires_exact_pod_and_controller_chain() -> None:
    resources = _ready_resources()
    resources["hpas"]["items"] = [
        {"spec": {"scaleTargetRef": {"kind": "Deployment", "name": "order-api"}}}
    ]
    snapshot = await _reader(resources, []).read()
    assert snapshot.ready_replicas == snapshot.ready_endpoints == 1
    assert snapshot.hpa_managed is True


@pytest.mark.parametrize(
    "defect", ["service_owner", "pod_uid", "replica_owner", "not_ready", "unknown_ready"]
)
async def test_ready_endpoint_with_wrong_ownership_never_proves_recovery(defect: str) -> None:
    resources = _ready_resources()
    if defect == "service_owner":
        resources["slices"]["items"][0]["metadata"]["ownerReferences"][0]["uid"] = "other-service"
    elif defect == "pod_uid":
        resources["pod"]["metadata"]["uid"] = "other-pod"
    elif defect == "replica_owner":
        resources["replica"]["metadata"]["ownerReferences"][0]["uid"] = "other-deployment"
    elif defect == "not_ready":
        resources["pod"]["status"]["conditions"][0]["status"] = "False"
    else:
        resources["slices"]["items"][0]["endpoints"][0]["conditions"]["ready"] = None
    with pytest.raises(ValueError):
        await _reader(resources, []).read()


@pytest.mark.parametrize("raw", ["", "{}", '{"intent":{}}', "[]", "x" * 32_769])
def test_runtime_rejects_missing_or_unknown_config(raw: str) -> None:
    with pytest.raises(ValueError):
        AcceptanceRuntimeConfig.from_json(raw)


def test_cli_failure_does_not_disclose_provider_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from fdai_aks_commerce.acceptance_runtime import main

    async def failed_tick() -> None:
        raise RuntimeError("provider-private-diagnostic")

    monkeypatch.setattr("fdai_aks_commerce.acceptance_runtime.run_acceptance_tick", failed_tick)
    assert main() == 1
    captured = capsys.readouterr()
    assert "provider-private-diagnostic" not in captured.out + captured.err
    assert '"failed": true' in captured.out


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "missing",
        "shadow",
        "changed",
        "audit",
        "expired",
        "authority",
        "late_revoked",
        "authority_mutation",
        "transport_error",
    ],
)
async def test_acceptance_isolated_dispatch_rechecks_at_real_safeguard_boundary(
    defect: str | None,
) -> None:
    intent = replace(
        _intent(), valid_from=_NOW - timedelta(seconds=30), valid_until=_NOW + timedelta(seconds=30)
    )
    params = {
        "target_resource_ref": intent.resource_ref,
        "target_platform": "kubernetes",
        "target_kind": "Deployment",
        "cluster_ref": intent.cluster_ref,
        "namespace": intent.namespace,
        "resource_name": intent.deployment_name,
        "target_uid": intent.deployment_uid,
        "resource_version": "1",
        "replica_count": 1,
        "reason": "Restore the reviewed order-acceptance replica floor.",
    }
    candidate = AnomalyActionCandidate(
        event_type=ACCEPTANCE_SIGNAL,
        resource_ref=intent.resource_ref,
        action_type="ops.scale-out",
        arguments_json=json.dumps(params, sort_keys=True, separators=(",", ":")),
        evidence_ref=REFERENCE,
        observed_at=_NOW,
        expires_at=_NOW + timedelta(seconds=30),
    )

    class Source:
        available = True
        reads = 0

        def __init__(self) -> None:
            self.intent = intent

        async def resolve(
            self, *, event_type: str, resource_ref: str
        ) -> AnomalyActionCandidate | None:
            self.reads += 1
            return candidate if self.available else None

    source = Source()
    action_payload = _direct_action(
        target=intent.resource_ref, mode=Mode.ENFORCE, params=params
    ).model_dump(mode="json")
    action_payload.update(
        action_type="ops.scale-out", operation="scale", executor_identity_ref="identity/resilience"
    )
    action = Action.model_validate(action_payload)
    material = AcceptanceDispatchMaterial(
        action_json=action.model_dump_json(),
        correlation_id="analyzer:example",
        action_run_idempotency_key="anomaly:example",
    )
    material_store = StoredAcceptanceDispatchMaterials(InMemoryStateStore())
    await material_store.retain(material)
    await material_store.retain(material)
    with pytest.raises(ValueError, match="different content"):
        await material_store.retain(replace(material, correlation_id="analyzer:other"))
    run = ActionRun(
        correlation_id=material.correlation_id,
        action_type=action.action_type,
        resource_id=action.target_resource_ref,
        state=ActionRunState.EXECUTING,
        verdict="hil",
        action_id=str(action.action_id),
        idempotency_key=material.action_run_idempotency_key,
        params=dict(params),
        resolved_autonomy_ceiling=Autonomy.ENFORCE_HIL,
        rollback_contract=action.rollback_ref.kind.value,
        execution_audit_receipt="audit:example",
        approval_expires_at=_NOW + timedelta(seconds=30),
    )
    calls: list[str] = []
    authority_checks: list[str] = []
    material_reads = 0

    async def read_material(action_id: str) -> AcceptanceDispatchMaterial | None:
        nonlocal material_reads
        material_reads += 1
        if defect == "missing":
            return None
        if defect == "changed" and material_reads > 1:
            return replace(
                material,
                action_json=action.model_copy(
                    update={"executor_identity_ref": "identity/other"}
                ).model_dump_json(),
            )
        return await material_store.read(action_id)

    async def authority(original: Action, context: dict[str, Any]) -> None:
        assert original == action
        assert context["run"] is run
        authority_checks.append(str(original.action_id))
        if defect == "authority":
            raise PermissionError("current authorization unavailable")
        if defect == "authority_mutation":
            run.quorum_required += 1

    async def unused(_context: dict[str, Any]) -> bool:
        pytest.fail("isolated dispatch must not fall back to the unbound executor")

    class Client:
        async def publish_bound(self, **kwargs: Any) -> Any:
            if defect == "late_revoked":
                source.available = False
            await kwargs["pre_publish_guard"]()
            calls.append(str(kwargs["action"].action_id))
            if defect == "transport_error":
                raise OSError("synthetic transport result is unknown")
            return _published_command(kwargs)

    if defect == "shadow":
        run.shadow_mode = True
    elif defect == "audit":
        run.execution_audit_receipt = None
    elif defect == "expired":
        run.approval_expires_at = _NOW
    coordinator, _lock = _coordinator(InMemoryStateStore())
    dispatch = AcceptanceIsolatedDispatch(
        guard=AcceptanceGuardedExecutor(
            source=cast(AcceptanceAnomalyActionSource, source), execute=unused, clock=lambda: _NOW
        ),
        read_material=read_material,
        check_authority=authority,
        client=SafeguardBoundEventBusDirectApiExecutionClient(
            client=cast(EventBusDirectApiExecutionClient, Client()),
            coordinator=coordinator,
        ),
        clock=lambda: _NOW,
    )
    expected_error = (
        TimeoutError
        if defect in {None, "late_revoked", "transport_error"}
        else PermissionError
        if defect == "authority"
        else ValueError
    )
    with pytest.raises(expected_error):
        await dispatch({"run": run})
    assert len(calls) == (1 if defect in {None, "transport_error"} else 0)
    if defect is None:
        assert len(authority_checks) == 2
        assert source.reads == 2


@pytest.mark.parametrize("defect", ["digest", "correlation", "extra", "action"])
async def test_acceptance_material_readback_rejects_corruption(defect: str) -> None:
    action = _direct_action().model_copy(
        update={"action_type": "ops.scale-out", "operation": Operation.SCALE}
    )
    material = AcceptanceDispatchMaterial(
        action.model_dump_json(), "analyzer:example", "anomaly:example"
    )
    store = InMemoryStateStore()
    materials = StoredAcceptanceDispatchMaterials(store)
    action_id = str(action.action_id)
    assert await materials.read(action_id) is None
    await materials.retain(material)
    assert await StoredAcceptanceDispatchMaterials(store).read(action_id) == material
    key = "aks-commerce:acceptance-action:v1:" + action_id
    record = dict(await store.read_state(key) or {})
    if defect == "digest":
        record["digest"] = "sha256:" + "0" * 64
    elif defect == "correlation":
        record["material"]["correlation_id"] = "analyzer:other"
    elif defect == "extra":
        record["execution_authority"] = True
    else:
        record["material"]["action_json"] = "{}"
    await store.write_state(key, record)
    with pytest.raises(ValueError):
        await materials.read(action_id)


@pytest.mark.parametrize("revoked", [True, None, "false"])
async def test_revocation_unknown_or_true_denies(revoked: object) -> None:
    store, verifier, _ = await _receipt()
    await store.write_state(
        REVOCATION_PREFIX + "example-key",
        {
            "key_id": "example-key",
            "revoked": revoked,
            "valid_until": (NOW + timedelta(seconds=20)).isoformat(),
        },
    )
    assert not await verifier.verify(verification_ref=REFERENCE, evidence_digest=DIGEST)
