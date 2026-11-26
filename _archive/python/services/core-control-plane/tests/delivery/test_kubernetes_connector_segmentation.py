"""Shadow segmentation registration, policy-engine gate, executor recipe, and probes."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fdai.delivery.kubernetes_connector_installation import GatewayPeer
from fdai.delivery.kubernetes_connector_material import material_digest
from fdai.delivery.kubernetes_connector_policy import PodPolicyEndpoint
from fdai.delivery.kubernetes_connector_segmentation import (
    SEGMENTATION_ACTION_TYPE,
    SEGMENTATION_PREFIX,
    ExecutorInstallationInput,
    ManagementDependencyAllowlist,
    SegmentationProbe,
    SegmentationProbeTarget,
    SegmentationRegistrationError,
    SegmentationScenarioCase,
    ShadowSegmentationRegistration,
    assess_segmentation_probes,
    build_segmentation_rollback_plan,
    evaluate_segmentation_scenario,
    inspect_aks_policy_engine,
    register_shadow_segmentation,
    render_executor_installation,
    render_segmentation_network_policy,
    render_segmentation_probe_job,
    verify_executor_documents,
    verify_management_dependencies_allowed,
)
from fdai.shared.providers.testing import InMemoryStateStore

NOW = datetime(2026, 10, 4, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64
IMAGE = "registry.example/fdai/core-control-plane@sha256:" + "c" * 64


def registration(**changes: object) -> ShadowSegmentationRegistration:
    value: dict[str, object] = {
        "target_ref": "cluster-example",
        "namespace": "example",
        "capability_ref": SEGMENTATION_ACTION_TYPE,
        "registered_at": NOW,
        "expires_at": NOW + timedelta(minutes=10),
        "recovery_digest": DIGEST,
        "management_dependency_digests": [DIGEST, OTHER_DIGEST],
        "execution_authority": False,
    }
    value.update(changes)
    return ShadowSegmentationRegistration.model_validate(value)


def probe(kind: str, observed: str, *, observer: str) -> SegmentationProbe:
    return SegmentationProbe.model_validate(
        {
            "target_ref": "cluster-example",
            "namespace": "example",
            "probe_ref": f"{kind}-{observer}",
            "observer_ref": observer,
            "kind": kind,
            "observed": observed,
            "observed_at": NOW,
            "expires_at": NOW + timedelta(minutes=5),
            "evidence_digest": DIGEST if observed != "unknown" else None,
        }
    )


def allowlist() -> ManagementDependencyAllowlist:
    return ManagementDependencyAllowlist(
        gateway_port=8443,
        api_port=443,
        gateway_peer=GatewayPeer(
            namespace="fdai-gateway",
            labels={"app": "fdai-connector-gateway"},
        ),
        api_cidrs=("10.224.0.0/24",),
        dns_cidrs=("10.0.0.0/24",),
    )


async def test_register_shadow_segmentation_is_idempotent_and_no_authority() -> None:
    store = InMemoryStateStore()
    cilium = inspect_aks_policy_engine(
        target_ref="cluster-example",
        cluster={
            "properties": {
                "networkProfile": {
                    "networkPlugin": "azure",
                    "networkPolicy": "cilium",
                    "networkDataplane": "cilium",
                }
            }
        },
        observed_at=NOW,
    )
    assert cilium.state == "allowed"
    assert cilium.policy_engine == "cilium"
    assert await register_shadow_segmentation(
        store, registration(), now=lambda: NOW, policy_engine_fact=cilium
    )
    assert not await register_shadow_segmentation(
        store, registration(), now=lambda: NOW, policy_engine_fact=cilium
    )
    rows = await store.read_states(SEGMENTATION_PREFIX, limit=10)
    assert rows[0]["registration"]["mode"] == "shadow"
    assert rows[0]["registration"]["execution_authority"] is False
    assert len(list(store.audit_entries)) == 1
    with pytest.raises(SegmentationRegistrationError):
        await register_shadow_segmentation(
            store, registration(recovery_digest=OTHER_DIGEST), now=lambda: NOW
        )


async def test_policy_engine_capability_rejects_azure_cni_without_policy_engine() -> None:
    store = InMemoryStateStore()
    no_engine = inspect_aks_policy_engine(
        target_ref="cluster-example",
        cluster={"properties": {"networkProfile": {"networkPlugin": "azure"}}},
        observed_at=NOW,
    )
    assert no_engine.state == "denied"
    assert no_engine.reason == "policy_engine_missing"
    assert no_engine.policy_engine is None
    with pytest.raises(SegmentationRegistrationError, match="policy_engine_missing"):
        await register_shadow_segmentation(
            store, registration(), now=lambda: NOW, policy_engine_fact=no_engine
        )
    unreadable = inspect_aks_policy_engine(
        target_ref="cluster-example", cluster={}, observed_at=NOW
    )
    assert unreadable.state == "unknown"


async def test_corrupt_recovery_checkpoint_is_not_accepted() -> None:
    store = InMemoryStateStore()
    await register_shadow_segmentation(store, registration(), now=lambda: NOW)
    key = next(iter(store._state))  # noqa: SLF001 - white-box corruption for recovery proof.
    broken = dict(store._state[key])  # noqa: SLF001
    broken["registration_digest"] = OTHER_DIGEST
    await store.write_state(key, broken)
    with pytest.raises(SegmentationRegistrationError):
        await register_shadow_segmentation(store, registration(), now=lambda: NOW)


def test_independent_positive_and_negative_probes_gate_review_readiness() -> None:
    result = assess_segmentation_probes(
        registration(),
        (
            probe("positive", "connected", observer="observer-a"),
            probe("negative", "blocked", observer="observer-b"),
        ),
        now=NOW,
    )
    assert result.status == "ready_for_review"
    assert result.execution_authority is False
    not_independent = assess_segmentation_probes(
        registration(),
        (
            probe("positive", "connected", observer="observer-a"),
            probe("negative", "blocked", observer="observer-a"),
        ),
        now=NOW,
    )
    assert not_independent.status == "needs_evidence"
    failed_negative = assess_segmentation_probes(
        registration(),
        (
            probe("positive", "connected", observer="observer-a"),
            probe("negative", "connected", observer="observer-b"),
        ),
        now=NOW,
    )
    assert failed_negative.status == "blocked"


def test_management_allowlist_and_rollback_contract_prevent_self_lockout() -> None:
    deps = allowlist()
    assert len(deps.dependency_digests) == 3
    rendered = render_segmentation_network_policy(
        namespace="example",
        name="isolate-backend",
        pod_selector_labels={"role": "api"},
        allowlist=deps,
        ingress_rules=(
            {
                "from": [{"podSelector": {"matchLabels": {"role": "web"}}}],
                "ports": [{"port": 8080, "protocol": "TCP"}],
            },
        ),
    )
    assert rendered["metadata"]["annotations"]["fdai.dev/mode"] == "shadow"
    assert rendered["metadata"]["annotations"]["fdai.dev/execution-authority"] == "false"
    tampered = json.loads(json.dumps(rendered))
    tampered["spec"]["egress"] = tampered["spec"]["egress"][1:]
    with pytest.raises(SegmentationRegistrationError, match="DNS, Kubernetes API, or gateway"):
        verify_management_dependencies_allowed(tampered, deps)
    created_rollback = build_segmentation_rollback_plan(
        target_ref="cluster-example",
        namespace="example",
        policy_name="isolate-backend",
        proposed_policy=rendered,
        prior_policy=None,
    )
    assert created_rollback.operation == "delete_created_policy"
    restored_rollback = build_segmentation_rollback_plan(
        target_ref="cluster-example",
        namespace="example",
        policy_name="isolate-backend",
        proposed_policy=rendered,
        prior_policy=rendered,
    )
    assert restored_rollback.operation == "restore_prior_policy"
    foreign = json.loads(json.dumps(rendered))
    foreign["metadata"]["annotations"]["fdai.dev/policy-owner"] = "foreign-owner"
    with pytest.raises(SegmentationRegistrationError, match="foreign-owned"):
        build_segmentation_rollback_plan(
            target_ref="cluster-example",
            namespace="example",
            policy_name="isolate-backend",
            proposed_policy=rendered,
            prior_policy=foreign,
        )


def _write_executor_material(directory: Path) -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fdai-executor-test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - dt.timedelta(days=1))
        .not_valid_after(NOW + dt.timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    key_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    principal = (
        "sha256:" + hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    )
    files = {
        "config.json": json.dumps(
            {
                "role": "executor",
                "gateway_origin": "https://gateway.example:8443",
                "api_server": "https://kubernetes.default.svc:443",
                "executor_principal_ref": principal,
            }
        ).encode(),
        "registrations.json": json.dumps(
            [
                {
                    "schema_version": "1.0.0",
                    "scope": {
                        "deployment_ref": "deploy-example",
                        "cluster_ref": "cluster-example",
                        "connector_id": "executor-example",
                        "enrollment_revision": 1,
                    },
                    "principal_ref": principal,
                    "role": "executor",
                    "namespaces": ["example"],
                    "capabilities": ["governed.execute"],
                    "valid_from": (NOW - timedelta(minutes=5)).isoformat(),
                    "expires_at": (NOW + timedelta(hours=1)).isoformat(),
                    "revoked": False,
                }
            ]
        ).encode(),
        "ca.pem": cert_bytes,
        "client.pem": cert_bytes,
        "client.key": key_bytes,
    }
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, content in files.items():
        path = directory / name
        path.write_bytes(content)
        path.chmod(0o600)
    return material_digest(files)


def test_executor_installation_renders_namespace_role_without_secret_reads(tmp_path: Path) -> None:
    mat_dir = tmp_path / "executor-material"
    digest = _write_executor_material(mat_dir)
    inputs = ExecutorInstallationInput(
        target_ref="cluster-example",
        namespace="example",
        name="fdai-executor-example",
        image=IMAGE,
        material_secret="fdai-executor-material",
        material_digest=digest,
        gateway_port=8443,
        api_port=443,
        gateway_cidrs=("10.240.0.0/24",),
        api_cidrs=("10.224.0.0/24",),
        dns_cidrs=("10.0.0.0/24",),
    )
    rendered = render_executor_installation(inputs, now=NOW, material_directory=mat_dir)
    documents = verify_executor_documents(rendered, inputs)
    kinds = {doc["kind"] for doc in documents}
    assert kinds == {"ServiceAccount", "Role", "RoleBinding", "Deployment", "NetworkPolicy"}
    assert "ClusterRole" not in kinds
    assert "ClusterRoleBinding" not in kinds
    role = next(doc for doc in documents if doc["kind"] == "Role")
    for rule in role["rules"]:
        assert "secrets" not in rule["resources"]
        assert "configmaps" not in rule["resources"]
    tampered = json.loads(json.dumps(rendered))
    tampered_role = next(doc for doc in tampered["documents"] if doc["kind"] == "Role")
    tampered_role["rules"].append({"apiGroups": [""], "resources": ["secrets"], "verbs": ["get"]})
    tampered["manifest_digest"] = rendered["manifest_digest"]
    with pytest.raises(ValueError, match="integrity|Secrets"):
        verify_executor_documents(tampered, inputs)


def test_typed_probe_job_and_scenario_agreement_evaluation() -> None:
    job = render_segmentation_probe_job(
        SegmentationProbeTarget(
            target_ref="cluster-example",
            namespace="example",
            probe_ref="allow-web-to-api",
            observer_ref="observer-a",
            kind="positive",
            source_labels={"role": "web"},
            destination_host="backend.example.svc",
            port=8080,
            image=IMAGE,
        )
    )
    assert job["kind"] == "Job"
    assert job["spec"]["template"]["spec"]["automountServiceAccountToken"] is False
    assert job["spec"]["template"]["spec"]["containers"][0]["securityContext"]["runAsNonRoot"]
    deps = allowlist()
    policy = render_segmentation_network_policy(
        namespace="example",
        name="isolate-backend",
        pod_selector_labels={"role": "api"},
        allowlist=deps,
        ingress_rules=(
            {
                "from": [{"podSelector": {"matchLabels": {"role": "web"}}}],
                "ports": [{"port": 8080, "protocol": "TCP"}],
            },
        ),
    )
    policy["metadata"]["uid"] = "policy-1"
    policy["metadata"]["resourceVersion"] = "1"
    web = PodPolicyEndpoint(
        "cluster-example",
        "example",
        "pod-web",
        (("role", "web"),),
        (("kubernetes.io/metadata.name", "example"),),
    )
    intruder = PodPolicyEndpoint(
        "cluster-example",
        "example",
        "pod-intruder",
        (("role", "intruder"),),
        (("kubernetes.io/metadata.name", "example"),),
    )
    api = PodPolicyEndpoint(
        "cluster-example",
        "example",
        "pod-api",
        (("role", "api"),),
        (("kubernetes.io/metadata.name", "example"),),
    )
    reg = registration(management_dependency_digests=list(deps.dependency_digests))
    cilium = inspect_aks_policy_engine(
        target_ref="cluster-example",
        cluster={
            "properties": {"networkProfile": {"networkPlugin": "azure", "networkPolicy": "cilium"}}
        },
        observed_at=NOW,
    )
    cases = (
        SegmentationScenarioCase(
            source=web,
            destination=api,
            policies=(policy,),
            port=8080,
            protocol="TCP",
            observed_at=NOW,
            probe=probe("positive", "connected", observer="observer-a"),
        ),
        SegmentationScenarioCase(
            source=intruder,
            destination=api,
            policies=(policy,),
            port=8080,
            protocol="TCP",
            observed_at=NOW,
            probe=probe("negative", "blocked", observer="observer-b"),
        ),
    )
    evaluation = evaluate_segmentation_scenario(reg, cases, policy_engine_fact=cilium, now=NOW)
    assert evaluation.status == "ready_for_review"
    assert evaluation.agreement_rate == 1.0
    assert evaluation.policy_escapes == 0
    escaped_cases = (
        cases[0],
        SegmentationScenarioCase(
            source=intruder,
            destination=api,
            policies=(policy,),
            port=8080,
            protocol="TCP",
            observed_at=NOW,
            probe=probe("negative", "connected", observer="observer-b"),
        ),
    )
    escaped = evaluate_segmentation_scenario(reg, escaped_cases, policy_engine_fact=cilium, now=NOW)
    assert escaped.status == "blocked"
    assert escaped.reason == "policy_escape_detected"
    assert escaped.policy_escapes == 1
