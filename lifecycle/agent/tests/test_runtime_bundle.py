from __future__ import annotations

import json
import multiprocessing
import re
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_release import APPLICATION_COMPONENT_RELEASE_SCHEMA
from pydantic import ValidationError

from fdai_lifecycle_agent.agent import AgentDependencies, LifecycleAgent
from fdai_lifecycle_agent.cli import load_local_policy
from fdai_lifecycle_agent.dry_run import EntityState, Health, load_current_state
from fdai_lifecycle_agent.inputs import DirectoryArtifactStore
from fdai_lifecycle_agent.journal import WorkloadStore
from fdai_lifecycle_agent.runtime_bundle import RuntimeBundle
from fdai_lifecycle_agent.signatures import Ed25519ArtifactVerifier, Ed25519HubKeyring
from fdai_lifecycle_agent.state import LocalStateStore, write_json_atomically
from fdai_lifecycle_agent.workload import Workload, WorkloadError

if TYPE_CHECKING:
    from conftest import FakeCluster, Harness


def container(component: str) -> dict[str, Any]:
    return {
        "name": component,
        "image_component": component,
        "resources": {
            "requests": {"cpu": "250m", "memory": "512Mi"},
            "limits": {"cpu": "1000m", "memory": "1024Mi"},
        },
        "securityContext": {
            "runAsNonRoot": True,
            "readOnlyRootFilesystem": True,
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
        },
        "ports": [{"name": "http", "containerPort": 8080}],
        "readinessProbe": {"httpGet": {"path": "/healthz", "port": "http"}},
        "envFrom": [{"configMapRef": {"name": f"{component}-config", "optional": False}}],
        "env": [
            {
                "name": "DATABASE_REFERENCE",
                "valueFrom": {"secretKeyRef": {"name": f"{component}-database", "key": "database"}},
            }
        ],
        "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],  # noqa: S108 - Pod-local emptyDir
    }


def template(component: str, *, scheduled: bool = False) -> dict[str, Any]:
    return {
        "metadata": {"labels": {"azure.workload.identity/use": "true"}},
        "spec": {
            "containers": [container(component)],
            "serviceAccountName": component,
            "automountServiceAccountToken": False,
            "securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
            "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": "128Mi"}}],
            **({"restartPolicy": "Never"} if scheduled else {}),
        },
    }


def bundle_document(
    product: str = "example-web",
    components: tuple[str, ...] = ("frontend",),
    *,
    scheduled: bool = False,
) -> dict[str, Any]:
    objects = []
    for component in components:
        objects.extend(
            [
                {
                    "entity_id": "application",
                    "kind": "Deployment",
                    "name": component,
                    "spec": {"replicas": 1, "template": template(component)},
                },
                {
                    "entity_id": "application",
                    "kind": "Service",
                    "name": component,
                    "spec": {"ports": [{"port": 80, "targetPort": "http"}]},
                },
            ]
        )
    if scheduled:
        objects.append(
            {
                "entity_id": "application",
                "kind": "CronJob",
                "name": "analyzer",
                "spec": {
                    "schedule": "*/5 * * * *",
                    "suspend": False,
                    "concurrencyPolicy": "Forbid",
                    "timeZone": "Etc/UTC",
                    "jobTemplate": {
                        "spec": {
                            "activeDeadlineSeconds": 120,
                            "backoffLimit": 0,
                            "template": template(components[0], scheduled=True),
                        }
                    },
                },
            }
        )
    return {
        "format": "fdai.application-runtime-bundle.v1",
        "product": product,
        "namespace": "fdai-demo",
        "objects": objects,
    }


def parse(document: dict[str, Any]) -> RuntimeBundle:
    return RuntimeBundle.model_validate_json(canonical_bytes(document))


def prepare(
    harness: Harness, document: dict[str, Any], *, version: str = "1.5.0", sequence: int = 8
):
    bundle = parse(document)
    components = bundle.components("application")
    if sequence == 8:
        harness.current_state = replace(
            harness.current_state,
            schema_revision=0,
            entities={"application": EntityState(None, frozenset(), Health.UNKNOWN)},
        )
    else:
        harness.current_state = load_current_state(harness.state_file)
    digest = harness.add_release(
        {
            "schema_version": APPLICATION_COMPONENT_RELEASE_SCHEMA,
            "product": bundle.product,
            "release_version": version,
            "source_commit": "a" * 40,
            "platform_tag": "linux-x86_64",
            "components": {
                name: {"image_digest": harness.image(f"{name}-{version}")} for name in components
            },
        }
    )
    config = harness.add_configuration(
        {
            "schema": {
                "runtime_bundle_digest": {
                    "default": bundle.digest,
                    "x-fdai-axis": "installation-path",
                    "x-fdai-owner": "customer",
                },
            },
            "environment": {},
            "entity_overrides": [{"versions": ">=1.0.0 <2.0.0", "values": {}}],
        }
    )
    maximum = harness.maximum_envelope(entity_ids=frozenset({"application"}), capability_modes={})
    harness.serve(
        harness.plan(
            entity_ids=frozenset({"application"}),
            capability_ids=(),
            envelope=maximum,
            target_release_digest=digest,
            configuration_revision_digest=config,
            target_release_id=version,
            sequence=sequence,
            plan_id=f"plan-{sequence:04d}",
        )
    )
    return harness.settings(
        maximum_envelope=maximum,
        product=bundle.product,
        runtime_bundle=bundle,
        entity_components={"application": components},
        component_repositories={
            name: f"registry.example.test/application/{name}" for name in components
        },
    )


@pytest.mark.parametrize(
    ("product", "components", "scheduled"),
    [
        ("example-web", ("frontend",), False),
        (
            "fdai",
            (
                "core-control-plane",
                "operator-service",
                "document-ingestion-api",
                "document-processing-worker",
                "isolated-executor",
                "console",
            ),
            True,
        ),
    ],
)
def test_applications_change_only_inputs_not_the_execution_path(
    harness: Harness,
    cluster: FakeCluster,
    product: str,
    components: tuple[str, ...],
    scheduled: bool,
) -> None:
    document = bundle_document(product, components, scheduled=scheduled)
    if product == "fdai":
        core = document["objects"][0]["spec"]["template"]["spec"]
        core["volumes"].extend(
            [
                {"name": "state", "persistentVolumeClaim": {"claimName": "core-runtime-state"}},
                {"name": "bridge", "configMap": {"name": "identity-bridge", "defaultMode": 0o444}},
            ]
        )
        core["containers"][0]["volumeMounts"].extend(
            [
                {"name": "state", "mountPath": "/app/.fdai"},
                {"name": "bridge", "mountPath": "/opt/fdai-compat", "readOnly": True},
            ]
        )
        worker = document["objects"][6]["spec"]["template"]["spec"]
        sidecar = container("clamav")
        sidecar["readinessProbe"] = {"tcpSocket": {"port": 3310}}
        sidecar["ports"] = [{"name": "scanner", "containerPort": 3310}]
        worker["containers"].append(sidecar)
        initializer = dict(container("clamav"), name="initialize-scanner")
        initializer.pop("readinessProbe")
        worker["initContainers"] = [initializer]
        worker["volumes"].append(
            {
                "name": "provider",
                "csi": {
                    "driver": "secrets-store.csi.k8s.io",
                    "readOnly": True,
                    "volumeAttributes": {"secretProviderClass": "document-processing-worker"},
                },
            }
        )
        document["objects"] = [
            item
            for item in document["objects"]
            if not (item["kind"] == "Service" and item["name"] == "document-processing-worker")
        ]
        for name in ("inventory", "self-review"):
            scheduled_object = deepcopy(document["objects"][-1])
            scheduled_object["name"] = name
            document["objects"].append(scheduled_object)
    settings = prepare(harness, document)
    apply = harness.apply_mode(cluster)
    first = LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once()
    assert first.outcome == "applied"
    assert len(cluster.objects) == len(document["objects"])
    for component in components:
        deployment = cluster.objects["Deployment", component]
        pod = deployment["spec"]["template"]["spec"]
        assert pod["serviceAccountName"] == component
        assert pod["containers"][0]["image"].endswith(harness.image(f"{component}-1.5.0"))
        assert pod["containers"][0]["resources"]["limits"]["memory"] == "1024Mi"
    if scheduled:
        assert cluster.objects["CronJob", "analyzer"]["spec"]["suspend"] is False
        applications = [call for call in cluster.calls if call[0] == "apply"]
        assert {call[1:] for call in applications[:3]} == {
            ("CronJob", name) for name in ("analyzer", "inventory", "self-review")
        }
        assert {call[1:] for call in applications[-3:]} == {
            ("CronJob", name) for name in ("analyzer", "inventory", "self-review")
        }
    before = deepcopy(cluster.objects)
    calls = list(cluster.calls)
    replay = LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once()
    assert replay.outcome == "already-reported"
    assert cluster.objects == before
    assert cluster.calls == calls
    reports = json.dumps([report.summary for _, _, report in harness.hub.reports])
    assert "database" not in reports and "configMap" not in reports


def test_default_dry_run_does_not_load_or_write_the_cluster(
    harness: Harness, cluster: FakeCluster
) -> None:
    settings = prepare(harness, bundle_document())
    result = LifecycleAgent(settings, harness.dependencies()).poll_once()
    assert result.outcome == "dry-run-admitted"
    assert cluster.calls == []


def test_changed_private_bundle_cannot_reuse_a_signed_configuration_pin(
    harness: Harness,
    cluster: FakeCluster,
) -> None:
    document = bundle_document()
    settings = prepare(harness, document)
    document["objects"][0]["spec"]["template"]["spec"]["serviceAccountName"] = "different-identity"
    settings = replace(settings, runtime_bundle=parse(document))
    result = LifecycleAgent(
        settings, harness.dependencies(apply=harness.apply_mode(cluster))
    ).poll_once()
    assert (result.outcome, result.reason_code) == ("rejected", "runtime_bundle_digest_mismatch")
    assert cluster.calls == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("hostNetwork", True),
        ("hostPID", True),
        ("hostPath", "/"),
        ("nodeName", "unexpected-node"),
        ("automountServiceAccountToken", "true"),
        ("serviceAccountName", "default"),
        ("volumes", [{"name": "host", "hostPath": {"path": "/"}}]),
    ],
)
def test_private_pod_templates_cannot_widen_the_supported_security_boundary(
    key: str,
    value: Any,
) -> None:
    document = bundle_document()
    document["objects"][0]["spec"]["template"]["spec"][key] = value
    with pytest.raises(ValidationError):
        parse(document)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("image", "registry.example.test/unapproved:latest"),
        ("env", [{"name": "LITERAL", "value": "not-a-reference"}]),
        ("env", {"invalid": "shape"}),
        ("securityContext", {"privileged": True}),
        ("resources", {"limits": {"cpu": "64000m", "memory": "1024Mi"}}),
        ("readinessProbe", {"exec": {"command": ["unexpected"]}}),
        ("readinessProbe", {"httpGet": {"host": "other-host", "path": "/", "port": 80}}),
    ],
)
def test_container_templates_reject_unapproved_images_literals_and_probe_targets(
    key: str,
    value: Any,
) -> None:
    document = bundle_document()
    document["objects"][0]["spec"]["template"]["spec"]["containers"][0][key] = value
    with pytest.raises(ValidationError):
        parse(document)


def test_scheduled_failures_do_not_report_unproved_side_effects_as_verified_recovery(
    harness: Harness,
    cluster: FakeCluster,
) -> None:
    settings = prepare(harness, bundle_document(scheduled=True))
    apply = harness.apply_mode(cluster)
    result = LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once()
    assert result.outcome == "applied"
    desired = apply.store.load().healthy
    assert not apply.workload.roll_back(desired, desired)
    assert cluster.objects["CronJob", "analyzer"]["spec"]["suspend"] is True


def test_namespace_mismatch_stops_before_server_dry_run(
    harness: Harness, cluster: FakeCluster
) -> None:
    document = bundle_document()
    document["namespace"] = "other-namespace"
    settings = prepare(harness, document)
    result = LifecycleAgent(
        settings, harness.dependencies(apply=harness.apply_mode(cluster))
    ).poll_once()
    assert (result.outcome, result.reason_code) == ("rejected", "runtime_bundle_namespace_mismatch")
    assert cluster.calls == []


def test_renderer_cannot_select_an_image_outside_its_entity() -> None:
    bundle = parse(bundle_document())
    with pytest.raises(WorkloadError, match="runtime_bundle_component_mismatch"):
        bundle.render(bundle.namespace, frozenset({"application"}), {})


@pytest.mark.parametrize("scheduled", [False, True])
def test_fresh_process_updates_and_failed_image_recovery_preserve_local_state(
    harness: Harness, cluster: FakeCluster, scheduled: bool
) -> None:
    document = bundle_document(scheduled=scheduled)
    apply = harness.apply_mode(cluster)
    settings = prepare(harness, document)
    assert (
        LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once().outcome == "applied"
    )
    settings = prepare(harness, document, version="1.6.0", sequence=9)
    assert (
        LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once().outcome == "applied"
    )
    healthy = deepcopy(cluster.objects)
    settings = prepare(harness, document, version="1.7.0", sequence=10)
    cluster.broken_images.add(
        f"registry.example.test/application/frontend@{harness.image('frontend-1.7.0')}"
    )
    outcome = LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once()
    assert outcome.outcome == "rolled-back"
    if scheduled:
        assert apply.store.halted_plan_id() == "plan-0010"
        assert cluster.objects["CronJob", "analyzer"]["spec"]["suspend"] is True
        assert (
            LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once().outcome
            == "halted"
        )
    else:
        assert apply.store.halted_plan_id() is None
        assert {key: value["spec"] for key, value in cluster.objects.items()} == {
            key: value["spec"] for key, value in healthy.items()
        }
        assert load_current_state(harness.state_file).entities["application"].release_id == "1.6.0"
        assert LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once().outcome == (
            "already-reported"
        )


def test_suspended_readback_is_not_proof_that_an_active_schedule_never_ran(
    harness: Harness, cluster: FakeCluster
) -> None:
    settings = prepare(harness, bundle_document(scheduled=True))
    apply = harness.apply_mode(cluster)
    assert (
        LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once().outcome == "applied"
    )
    desired = apply.store.load().healthy
    cluster.objects["CronJob", "analyzer"]["spec"]["suspend"] = True
    assert not apply.workload.roll_back(desired, desired)


@pytest.mark.parametrize("value", [None, {}, False])
@pytest.mark.parametrize("key", ["imagePullPolicy", "env", "ports", "readinessProbe", "resources"])
def test_malformed_optional_container_fields_raise_validation_errors(key: str, value: Any) -> None:
    document = bundle_document()
    document["objects"][0]["spec"]["template"]["spec"]["containers"][0][key] = value
    with pytest.raises(ValidationError):
        parse(document)


def test_scheduled_batch_container_needs_no_http_server() -> None:
    document = bundle_document(scheduled=True)
    pod = document["objects"][-1]["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    pod["containers"][0].pop("readinessProbe")
    pod["containers"][0].pop("ports")
    assert parse(document).objects[-1].kind == "CronJob"


def test_private_policy_requires_owner_only_storage_and_redacts_invalid_templates(
    tmp_path: Path,
) -> None:
    document = bundle_document()
    policy = {
        "schema": "fdai.lifecycle-local-policy.v1",
        "entity_ids": ["application"],
        "regions": ["korea-central"],
        "capability_modes": {},
        "destructive_allowed": False,
        "max_duration_minutes": 60,
        "entity_components": {"application": ["frontend"]},
        "product": "example-web",
        "component_images": {"frontend": "registry.example.test/application/frontend"},
        "runtime_bundle": document,
    }
    path = tmp_path / "local-policy.json"
    write_json_atomically(path, policy)
    assert load_local_policy(path)["runtime_bundle"].digest == parse(document).digest
    path.chmod(0o644)
    with pytest.raises(ValueError):
        load_local_policy(path)
    document["objects"][0]["spec"]["template"]["spec"]["serviceAccountName"] = {
        "private-reference": "not-public"
    }
    write_json_atomically(path, policy)
    with pytest.raises(ValueError, match="private local runtime bundle is invalid") as caught:
        load_local_policy(path)
    assert "private-reference" not in str(caught.value)


def test_bilingual_handoff_example_is_an_executable_runtime_contract() -> None:
    runbooks = Path(__file__).resolve().parents[3] / "docs" / "runbooks"
    examples = [
        re.findall(r"```json\n(.*?)\n```", (runbooks / name).read_text(), re.DOTALL)
        for name in (
            "hub-lifecycle-deployment-handoff.md",
            "hub-lifecycle-deployment-handoff-ko.md",
        )
    ]
    assert len(examples[0]) == 1
    assert examples[0] == examples[1]
    assert RuntimeBundle.model_validate_json(examples[0][0]).product == "example-web"


def test_removing_a_previously_healthy_object_is_not_a_silent_partial_update(
    harness: Harness, cluster: FakeCluster
) -> None:
    document = bundle_document()
    settings = prepare(harness, document)
    apply = harness.apply_mode(cluster)
    assert (
        LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once().outcome == "applied"
    )
    document["objects"].pop()
    settings = prepare(harness, document, version="1.6.0", sequence=9)
    before = deepcopy(cluster.objects)
    result = LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once()
    assert (result.outcome, result.reason_code) == (
        "rejected",
        "runtime_bundle_topology_removal_unsupported",
    )
    assert cluster.objects == before


def test_component_release_cannot_authorize_a_schema_transition(
    harness: Harness, cluster: FakeCluster
) -> None:
    settings = prepare(harness, bundle_document())
    harness.current_state = replace(harness.current_state, schema_revision=1)
    result = LifecycleAgent(
        settings, harness.dependencies(apply=harness.apply_mode(cluster))
    ).poll_once()
    assert (result.outcome, result.reason_code) == ("rejected", "schema_transition_unsupported")
    assert cluster.calls == []


def _replay_in_process(settings, plan, state_dir, cluster, public_keys, sending) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from lifecycle.agent.tests.conftest import FakeHubClient

    from fdai_lifecycle_agent.agent import ApplyMode

    hub = FakeHubClient()
    hub.plan = plan
    state_file = state_dir.parent / "current-state.json"
    cluster.calls.clear()
    dependencies = AgentDependencies(
        hub=hub,
        state_store=LocalStateStore(state_dir),
        artifact_store=DirectoryArtifactStore(state_dir.parent / "inputs"),
        verify_plan_signature=Ed25519HubKeyring(
            {"hub-key-active": Ed25519PublicKey.from_public_bytes(public_keys[0])}
        ),
        verify_release_signature=Ed25519ArtifactVerifier(
            Ed25519PublicKey.from_public_bytes(public_keys[1])
        ),
        verify_configuration_signature=Ed25519ArtifactVerifier(
            Ed25519PublicKey.from_public_bytes(public_keys[2])
        ),
        read_current_state=lambda: load_current_state(state_file),
        clock=lambda: load_current_state(state_file).observed_at,
        apply=ApplyMode(
            workload=Workload(
                cluster=cluster, namespace=cluster.namespace, health_timeout_seconds=5
            ),
            store=WorkloadStore(state_dir),
            write_current_state=lambda document: write_json_atomically(state_file, document),
        ),
    )
    sending.send((LifecycleAgent(settings, dependencies).poll_once().outcome, cluster.calls))
    sending.close()


def test_runtime_bundle_replay_reads_durable_state_in_another_os_process(
    harness: Harness, cluster: FakeCluster
) -> None:
    settings = prepare(harness, bundle_document(scheduled=True))
    assert (
        LifecycleAgent(settings, harness.dependencies(apply=harness.apply_mode(cluster)))
        .poll_once()
        .outcome
        == "applied"
    )
    context = multiprocessing.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(
        target=_replay_in_process,
        args=(
            settings,
            harness.hub.plan,
            harness.state_store.path.parent,
            cluster,
            tuple(
                key.public_key().public_bytes_raw()
                for key in (
                    harness.hub_keys["hub-key-active"],
                    harness.release_key,
                    harness.configuration_key,
                )
            ),
            sending,
        ),
    )
    try:
        process.start()
        sending.close()
        process.join(timeout=60)
        assert process.exitcode == 0
        assert receiving.poll(0)
        assert receiving.recv() == ("already-reported", [])
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        receiving.close()
        sending.close()
