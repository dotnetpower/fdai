from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from fdai_lifecycle_agent.agent import LifecycleAgent
from fdai_lifecycle_agent.dry_run import load_current_state
from fdai_lifecycle_agent.journal import WorkloadStore
from fdai_lifecycle_agent.operator_workload import (
    PROFILE,
    render_operator,
    validate_profile,
)
from fdai_lifecycle_agent.workload import Manifest, WorkloadError, check_scope

if TYPE_CHECKING:
    from conftest import FakeCluster, Harness

    from fdai_lifecycle_agent.agent import PollResult
    from fdai_lifecycle_agent.hub_client import PlanReport

VALUES: dict[str, object] = {
    "workload_profile": PROFILE,
    "operator_config_map_name": "operator-config-v1",
    "operator_database": {"secret_name": "operator-database-v1"},
    "schema_database": {"secret_name": "schema-reader-v1"},
    "replicas": 1,
}


def image(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


REPOSITORY = "registry.example.test/fdai"
IMAGES = {("operator-api", "operator-service"): f"{REPOSITORY}/operator@{image('operator')}"}
CORE_IMAGE = f"{REPOSITORY}/core@{image('core')}"


def rendered(**overrides: Any) -> tuple[Manifest, ...]:
    return render_operator(
        "fdai-test",
        IMAGES,
        core_image=CORE_IMAGE,
        values=VALUES,
        plan_digest="a" * 64,
        **overrides,
    )


def test_operator_is_the_real_image_entrypoint_port_and_probe() -> None:
    job, deployment, service = rendered()
    check_scope((job, deployment, service), "fdai-test")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert container["command"] == ["fdai-operator-service"]
    assert container["image"] == IMAGES[("operator-api", "operator-service")]
    assert container["ports"] == [{"name": "http", "containerPort": 8000}]
    assert container["readinessProbe"]["httpGet"] == {"path": "/healthz", "port": "http"}
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "services/operator-service/docker/Dockerfile").read_text()
    assert 'ENTRYPOINT ["fdai-operator-service"]' in dockerfile
    assert "EXPOSE 8000" in dockerfile
    assert "/healthz" in dockerfile
    assert job["spec"]["template"]["spec"]["containers"][0]["image"] == CORE_IMAGE
    assert deployment["metadata"]["name"] == "operator-service"
    assert service["metadata"]["name"] == "operator-service-internal"
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["selector"] == {"app.kubernetes.io/name": "operator-service"}
    assert (
        service["spec"]["selector"].items()
        <= deployment["spec"]["template"]["metadata"]["labels"].items()
    )


def test_render_contains_references_not_secret_or_foundation_objects() -> None:
    job, deployment, _ = rendered()
    pod = deployment["spec"]["template"]["spec"]
    assert pod["serviceAccountName"] == "operator-service"
    assert pod["automountServiceAccountToken"] is False
    container = pod["containers"][0]
    assert container["envFrom"] == [
        {"configMapRef": {"name": "operator-config-v1", "optional": False}}
    ]
    database = next(item for item in container["env"] if item["name"] == "FDAI_DATABASE_URL")
    assert database == {
        "name": "FDAI_DATABASE_URL",
        "valueFrom": {
            "secretKeyRef": {
                "name": "operator-database-v1",
                "key": "FDAI_DATABASE_URL",
                "optional": False,
            }
        },
    }
    assert job["spec"]["backoffLimit"] == 0
    assert job["spec"]["activeDeadlineSeconds"] == 120
    assert job["spec"]["template"]["spec"]["serviceAccountName"] == "fdai-schema-check"
    assert {item["kind"] for item in rendered()} == {"Job", "Deployment", "Service"}
    assert "readOnlyRootFilesystem" in container["securityContext"]
    assert not any("azure.workload.identity" in key for key in pod)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"workload_profile": "unknown"}, "workload_profile_unsupported"),
        ({"operator_config_map_name": "../outside"}, "workload_reference_invalid"),
        ({"operator_database": None}, "workload_reference_invalid"),
        ({"schema_database": {"secret_name": ""}}, "workload_reference_invalid"),
        ({"replicas": True}, "workload_replicas_invalid"),
        ({"replicas": 0}, "workload_replicas_invalid"),
        ({"replicas": 4}, "workload_replicas_invalid"),
    ],
)
def test_profile_rejects_invalid_configuration(changes: dict[str, object], reason: str) -> None:
    with pytest.raises(WorkloadError, match=reason):
        validate_profile(
            VALUES | changes,
            {"operator-api": frozenset({"operator-service"})},
            current_schema=15,
            target_schema=15,
            schema_minimum=12,
            schema_maximum=16,
        )


@pytest.mark.parametrize(
    ("target", "minimum", "maximum"), [(16, 12, 16), (14, 12, 16), (15, 16, 17)]
)
def test_no_unclassified_schema_upgrade_or_downgrade(
    target: int, minimum: int, maximum: int
) -> None:
    with pytest.raises(WorkloadError, match="schema_transition_unsupported"):
        validate_profile(
            VALUES,
            {"operator-api": frozenset({"operator-service"})},
            current_schema=15,
            target_schema=target,
            schema_minimum=minimum,
            schema_maximum=maximum,
        )


def serve_operator(
    harness: Harness, cluster: FakeCluster, *, sequence: int = 8, schema: int = 15
) -> None:
    harness.configuration_document = {
        "schema": {
            key: {
                "default": value,
                "x-fdai-axis": "installation-path",
                "x-fdai-owner": "customer",
            }
            for key, value in VALUES.items()
        },
        "environment": {},
        "entity_overrides": [{"versions": ">=1.0.0 <2.0.0", "values": {}}],
    }
    harness.configuration_digest = harness.add_configuration(harness.configuration_document)
    release = harness.manifest(version=f"1.{sequence}.0")
    release["schema"] = {"target": schema, "tolerates": {"minimum": 12, "maximum": 16}}
    if not harness.state_file.exists():
        harness.apply_mode(cluster)
    harness.serve(
        harness.plan(
            plan_id=f"operator-{sequence}",
            sequence=sequence,
            target_release_id=f"1.{sequence}.0",
            target_release_digest=harness.add_release(release),
            configuration_revision_digest=harness.configuration_digest,
            source_state_digest=load_current_state(harness.state_file).digest,
            entity_ids=frozenset({"operator-api"}),
        )
    )


def poll_operator(harness: Harness, cluster: FakeCluster) -> PollResult:
    settings = harness.settings(
        component_repositories={
            "operator-service": f"{REPOSITORY}/operator",
            "core-control-plane": f"{REPOSITORY}/core",
        }
    )
    return LifecycleAgent(
        settings,
        harness.dependencies(
            apply=harness.apply_mode(cluster),
            read_current_state=lambda: load_current_state(harness.state_file),
        ),
    ).poll_once()


def test_signed_operator_install_update_and_failed_update_restore(
    harness: Harness, cluster: FakeCluster
) -> None:
    for sequence in (8, 9):
        serve_operator(harness, cluster, sequence=sequence)
        assert poll_operator(harness, cluster).outcome == "applied"
        assert not any(kind == "Job" for kind, _ in cluster.objects)
        state = WorkloadStore(harness.state_store.path.parent).load()
        assert {item["kind"] for item in state.healthy} == {"Deployment", "Service"}
    healthy_image = cluster.image("operator-service")
    assert healthy_image == f"{REPOSITORY}/operator@{image('operator-service-1.9.0')}"
    serve_operator(harness, cluster, sequence=10)
    cluster.broken_images.add(f"{REPOSITORY}/operator@{image('operator-service-1.10.0')}")
    result = poll_operator(harness, cluster)
    assert result.outcome == "rolled-back"
    assert result.reason_code == "health_check_failed"
    assert cluster.image("operator-service") == healthy_image
    assert any(kind == "Job" for kind, _ in cluster.observed)
    assert load_current_state(harness.state_file).entities["operator-api"].release_id == "1.9.0"
    writes = len(cluster.writes())
    assert poll_operator(harness, cluster).outcome == "already-reported"
    assert len(cluster.writes()) == writes


@pytest.mark.parametrize("schema_status", ["Failed", "Pending"])
def test_schema_failure_or_timeout_never_switches_a_workload(
    harness: Harness, cluster: FakeCluster, schema_status: str, caplog: pytest.LogCaptureFixture
) -> None:
    cluster.schema_status = schema_status
    serve_operator(harness, cluster)
    result = poll_operator(harness, cluster)
    assert (result.outcome, result.reason_code) == ("rolled-back", "apply_failed")
    assert "schema_check_failed" in caplog.text
    assert not any(verb == "apply" and kind == "Deployment" for verb, kind, _ in cluster.calls)
    assert cluster.objects == {}


def test_schema_change_rejected_before_any_cluster_call(
    harness: Harness, cluster: FakeCluster
) -> None:
    serve_operator(harness, cluster, schema=16)
    result = poll_operator(harness, cluster)
    assert result.reason_code == "schema_transition_unsupported"
    assert cluster.calls == []


@pytest.mark.parametrize("drift_kind", ["Job", "Deployment"])
def test_ready_status_cannot_hide_rendered_image_drift(
    harness: Harness,
    cluster: FakeCluster,
    monkeypatch: pytest.MonkeyPatch,
    drift_kind: str,
) -> None:
    serve_operator(harness, cluster)
    original = cluster.get

    changed_image = f"{REPOSITORY}/core@{image('unexpected')}"

    def drift(kind: str, name: str) -> Manifest | None:
        live = original(kind, name)
        if kind == drift_kind and live is not None:
            live["spec"]["template"]["spec"]["containers"][0]["image"] = changed_image
        return live

    monkeypatch.setattr(cluster, "get", drift)
    result = poll_operator(harness, cluster)
    assert result.outcome == "rolled-back"
    assert result.reason_code == ("apply_failed" if drift_kind == "Job" else "health_check_failed")
    assert cluster.objects == {}


def test_unremovable_schema_job_halts_after_failed_recovery(
    harness: Harness, cluster: FakeCluster, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve_operator(harness, cluster)
    original = cluster.delete

    def deny_job_delete(kind: str, name: str) -> None:
        if kind == "Job":
            raise WorkloadError("kubernetes_request_rejected")
        original(kind, name)

    monkeypatch.setattr(cluster, "delete", deny_job_delete)
    result = poll_operator(harness, cluster)
    assert (result.outcome, result.reason_code) == ("rolled-back", "apply_failed")
    store = WorkloadStore(harness.state_store.path.parent)
    assert store.halted_plan_id() == "operator-8"
    writes = list(cluster.writes())
    serve_operator(harness, cluster, sequence=9)
    assert poll_operator(harness, cluster).reason_code == "rollback_failed"
    assert cluster.writes() == writes


def test_expiry_after_schema_check_rolls_back_without_switching(
    harness: Harness,
    cluster: FakeCluster,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    serve_operator(harness, cluster)
    original = cluster.get
    now = harness.dependencies().clock()
    expired = False

    def observe(kind: str, name: str) -> Manifest | None:
        nonlocal expired
        live = original(kind, name)
        if kind == "Job" and live is not None:
            expired = True
        return live

    monkeypatch.setattr(cluster, "get", observe)
    agent = LifecycleAgent(
        harness.settings(
            component_repositories={
                "operator-service": f"{REPOSITORY}/operator",
                "core-control-plane": f"{REPOSITORY}/core",
            }
        ),
        harness.dependencies(
            apply=harness.apply_mode(cluster),
            read_current_state=lambda: load_current_state(harness.state_file),
            clock=lambda: now + timedelta(days=1) if expired else now,
        ),
    )
    result = agent.poll_once()
    assert (result.outcome, result.reason_code) == ("rolled-back", "apply_failed")
    assert "plan_expired" in caplog.text
    assert not any(verb == "apply" and kind == "Deployment" for verb, kind, _ in cluster.calls)
    assert cluster.objects == {}


def test_existing_terraform_deployment_is_not_adopted(
    harness: Harness, cluster: FakeCluster
) -> None:
    serve_operator(harness, cluster)
    deployment = copy.deepcopy(dict(rendered()[1]))
    deployment["metadata"]["namespace"] = cluster.namespace
    cluster.objects[("Deployment", "operator-service")] = deployment
    assert poll_operator(harness, cluster).reason_code == "rollback_target_unknown"
    assert cluster.writes() == []


def test_restart_after_schema_job_does_not_rerun_it(harness: Harness, cluster: FakeCluster) -> None:
    serve_operator(harness, cluster)
    agent = LifecycleAgent(
        harness.settings(
            component_repositories={
                "operator-service": f"{REPOSITORY}/operator",
                "core-control-plane": f"{REPOSITORY}/core",
            }
        ),
        harness.dependencies(apply=harness.apply_mode(cluster)),
    )
    original = harness.hub.submit_report

    def interrupt(installation: str, plan: str, report: PlanReport) -> None:
        original(installation, plan, report)
        if report.outcome == "apply-started":
            raise KeyboardInterrupt

    harness.hub.submit_report = interrupt  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        agent.poll_once()
    store = WorkloadStore(harness.state_store.path.parent)
    state = store.load()
    assert state.journal is not None
    # Simulate a process loss after writing the applying fence and creating the Job.
    store.save(replace(state, journal=replace(state.journal, phase="applying")))
    cluster.apply(state.journal.desired[0])
    harness.hub.submit_report = original  # type: ignore[method-assign]
    assert poll_operator(harness, cluster).outcome == "rolled-back"
    assert sum(verb == "apply" and kind == "Job" for verb, kind, _ in cluster.calls) == 1
    assert cluster.objects == {}
