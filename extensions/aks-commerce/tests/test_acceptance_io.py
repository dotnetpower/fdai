import copy
import ssl
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai.delivery.analyzer_tick import AnalyzerTarget
from fdai.delivery.persistence.postgres_analyzer_publication import (
    PostgresAnalyzerPublicationLedger,
)
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.delivery.publication_store import ConditionalStore

from fdai_aks_commerce.acceptance import (
    OrderAcceptanceEvidence,
    OrderAcceptanceIntent,
    OrderAcceptanceProbe,
    evaluate_order_acceptance,
)
from fdai_aks_commerce.acceptance_kubernetes import KubernetesOrderAcceptanceReader
from fdai_aks_commerce.acceptance_receipts import (
    RECEIPT_PREFIX,
    REVOCATION_PREFIX,
    AcceptanceTrustBinding,
    StoredOrderAcceptanceReceiptVerifier,
    acceptance_receipt_payload,
)
from fdai_aks_commerce.acceptance_runtime import AcceptanceRuntimeConfig, build_acceptance_runner
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


async def test_signed_observation_survives_store_reconstruction_and_replay() -> None:
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
    runner = build_acceptance_runner(
        config=config,
        store=store,
        event_bus=InMemoryEventBus(),
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
    await store.write_state(RECEIPT_PREFIX + REFERENCE, {**receipt, "signature": "0" * 128})
    assert not await verifier.verify(verification_ref=REFERENCE, evidence_digest=first)
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
