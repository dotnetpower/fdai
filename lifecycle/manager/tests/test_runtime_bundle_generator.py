from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.aks_workload_jobs import prepare_aks_scheduled_jobs
from fdai_deployment_cli.standalone_operational_evidence import aks_workload

from fdai_lifecycle_manager.cli import main
from fdai_lifecycle_manager.preparation import prepare_installation
from fdai_lifecycle_manager.runtime_bundle_generator import (
    generate_fdai_runtime_bundle,
    write_generated_runtime_bundle,
)


def _image(component: str, char: str) -> str:
    return f"registry.example.test/fdai/{component}@sha256:{char * 64}"


def _identity(name: str, index: int) -> dict[str, str]:
    suffix = f"{index:012d}"
    return {
        "resource_id": (
            "/subscriptions/00000000-0000-0000-0000-000000000000"
            "/resourceGroups/rg-fdai-dev-wus3"
            f"/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-{name}"
        ),
        "client_id": f"00000000-0000-0000-0000-{suffix}",
        "principal_id": f"10000000-0000-0000-0000-{suffix}",
    }


def _stewardship_topology_fixture() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    refs = {
        "core-control-plane": _image("core-control-plane", "1"),
        "operator-service": _image("operator-service", "2"),
        "document-ingestion-api": _image("document-ingestion-api", "3"),
        "document-processing-worker": _image("document-processing-worker", "4"),
        "clamav": _image("clamav", "5"),
    }
    core_id = _identity("core", 1)
    operator_id = _identity("operator", 2)
    command_id = _identity("command", 3)
    ingestion_id = _identity("ingestion", 4)
    worker_id = _identity("worker", 5)
    inventory_id = _identity("inventory", 6)
    canary_id = _identity("canary", 7)

    core_env = {
        "RUNTIME_ENV": "dev",
        "AZURE_CLIENT_ID": core_id["client_id"],
        "FDAI_MI_CLIENT_ID": core_id["client_id"],
        "KAFKA_BOOTSTRAP_SERVERS": "eh-fdai-dev.servicebus.windows.net:9093",
        "ENABLE_STEWARDSHIP_GOVERNANCE": "true",
    }
    workloads: dict[str, dict[str, Any]] = {
        "core-control-plane": {
            **aks_workload(
                "core",
                refs,
                core_id,
                core_env,
                {
                    "APPLICATIONINSIGHTS_CONNECTION_STRING": "appinsights-connection-string",
                    "FDAI_STATE_STORE_DSN": "fdai-state-store-dsn",
                },
                "/ready",
                "/live",
            ),
            "source_commit": "a" * 40,
            "identity_bridge_enabled": True,
        },
        "operator-service": {
            **aks_workload(
                "operator",
                refs,
                operator_id,
                {
                    "RUNTIME_ENV": "dev",
                    "AZURE_CLIENT_ID": operator_id["client_id"],
                    "FDAI_MI_CLIENT_ID": operator_id["client_id"],
                    "FDAI_COMMAND_MI_CLIENT_ID": command_id["client_id"],
                },
                {
                    "FDAI_DATABASE_URL": "fdai-state-store-dsn",
                    "FDAI_COST_PSEUDONYM_KEY": "fdai-cost-pseudonym-key",
                },
                "/healthz",
                "/healthz",
                external=True,
                service_port=80,
                additional_identities={"command": command_id},
            ),
            "source_commit": "a" * 40,
        },
        "document-ingestion-api": {
            **aks_workload(
                "ingestion",
                refs,
                ingestion_id,
                {
                    "RUNTIME_ENV": "dev",
                    "FDAI_MI_CLIENT_ID": ingestion_id["client_id"],
                    "FDAI_INGESTION_DEPLOYMENT_ROLE": "api",
                    "FDAI_INGESTION_COHOST_WORKER": "0",
                },
                {"FDAI_DATABASE_URL": "fdai-ingestion-api-dsn"},
                "/healthz",
                "/healthz",
                external=True,
                service_port=80,
            ),
            "source_commit": "a" * 40,
        },
        "document-processing-worker": {
            **aks_workload(
                "worker",
                refs,
                worker_id,
                {
                    "RUNTIME_ENV": "dev",
                    "FDAI_MI_CLIENT_ID": worker_id["client_id"],
                    "FDAI_INGESTION_DEPLOYMENT_ROLE": "worker",
                    "FDAI_CLAMAV_HOST": "127.0.0.1",
                    "FDAI_CLAMAV_PORT": "3310",
                },
                {"FDAI_DATABASE_URL": "fdai-ingestion-worker-dsn"},
                "/ready",
                "/live",
                fs_group=101,
                sidecars={
                    "clamav": {
                        "image": refs["clamav"],
                        "command": ["clamd"],
                        "args": ["--foreground=true"],
                        "cpu": "500m",
                        "memory": "2Gi",
                        "port": 3310,
                        "run_as_user": 100,
                        "run_as_group": 101,
                        "init": {
                            "name": "clamav-database",
                            "command": ["/bin/sh", "-c"],
                            "args": ["cp -a /var/lib/clamav/. /target/"],
                            "image_pull_policy": "IfNotPresent",
                            "run_as_user": 100,
                            "run_as_group": 101,
                            "writable_path": "database",
                            "mount_path": "/target",
                        },
                        "writable_paths": {
                            "database": {"mount_path": "/var/lib/clamav", "size_limit": "1Gi"},
                            "log": {"mount_path": "/var/log/clamav", "size_limit": "64Mi"},
                            "run": {"mount_path": "/run/clamav", "size_limit": "64Mi"},
                            "tmp": {
                                "mount_path": "/tmp",  # noqa: S108 - Pod-local emptyDir
                                "size_limit": "256Mi",
                            },
                        },
                    }
                },
            ),
            "source_commit": "a" * 40,
        },
    }
    scheduled_jobs = prepare_aks_scheduled_jobs(
        refs=refs,
        core_identity=core_id,
        inventory_identity=inventory_id,
        canary_identity=canary_id,
        core_environment=core_env,
        substrate_outputs={
            "operational_kafka": "eh-fdai-dev.servicebus.windows.net:9093",
            "workspace": (
                "/subscriptions/00000000-0000-0000-0000-000000000000"
                "/resourceGroups/rg-fdai-dev-wus3"
                "/providers/Microsoft.OperationalInsights/workspaces/log-fdai-dev-wus3"
            ),
            "catalog_review_gitops_binding": None,
            "operational_history_container_url": "",
        },
        source_revision="a" * 40,
        tenant_id="00000000-0000-0000-0000-000000000000",
        subscription_id="00000000-0000-0000-0000-000000000000",
        catalog_review_selected=False,
        cluster_id=(
            "/subscriptions/00000000-0000-0000-0000-000000000000"
            "/resourceGroups/rg-fdai-dev-wus3"
            "/providers/Microsoft.ContainerService/managedClusters/aks-fdai-dev-wus3"
        ),
        namespace="fdai-runtime",
    ).jobs
    return workloads, scheduled_jobs


def test_generator_matches_native_scope_and_terraform_workload_parity() -> None:
    workloads, scheduled_jobs = _stewardship_topology_fixture()
    generated = generate_fdai_runtime_bundle(
        workloads=workloads,
        scheduled_jobs=scheduled_jobs,
        installation_id="installation-fdai-dev-wus3",
        entity_id="fdai-workloads",
        product="fdai",
        namespace="fdai-runtime",
        identity_bridge_config_map="fdai-identity-bridge",
    )

    assert generated.native_scope.components == (
        "core-control-plane",
        "document-ingestion-api",
        "document-processing-worker",
        "operator-service",
    )
    assert generated.native_scope.service_components == (
        "core-control-plane",
        "document-ingestion-api",
        "document-processing-worker",
        "operator-service",
    )
    assert generated.native_scope.scheduled_components == (
        "analyzer",
        "canary",
        "inventory",
        "observation-campaign",
    )
    assert set(generated.component_images) == {
        "clamav",
        "core-control-plane",
        "document-ingestion-api",
        "document-processing-worker",
        "operator-service",
    }
    assert generated.prerequisites.service_accounts == (
        "analyzer-job",
        "canary-job",
        "core-control-plane",
        "document-ingestion-api",
        "document-processing-worker",
        "inventory-job",
        "observation-campaign-job",
        "operator-service",
    )
    assert generated.prerequisites.secret_provider_classes == (
        "analyzer-job",
        "core-control-plane",
        "document-ingestion-api",
        "document-processing-worker",
        "inventory-job",
        "observation-campaign-job",
        "operator-service",
    )
    assert "fdai-identity-bridge" in generated.prerequisites.config_maps

    images = {("fdai-workloads", name): image for name, image in generated.component_images.items()}
    rendered = generated.bundle.render(
        "fdai-runtime",
        frozenset({"fdai-workloads"}),
        images,
    )
    by_kind_name = {(m["kind"], m["metadata"]["name"]): m for m in rendered}
    assert len(rendered) == 12

    # Verify Deployment parity against infra/runtimes/aks/workloads/main.tf
    for name, w_spec in workloads.items():
        dep = by_kind_name[("Deployment", name)]
        assert dep["spec"]["replicas"] == w_spec["replicas"]
        assert dep["spec"]["strategy"] == {
            "type": "RollingUpdate",
            "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0},
        }
        pod = dep["spec"]["template"]["spec"]
        assert pod["serviceAccountName"] == name
        assert pod["automountServiceAccountToken"] is True
        assert pod["terminationGracePeriodSeconds"] == 30
        assert pod["nodeSelector"] == {"fdai.io/pool": "runtime"}
        expected_pod_sec: dict[str, Any] = {
            "runAsNonRoot": True,
            "seccompProfile": {"type": "RuntimeDefault"},
        }
        if w_spec.get("fs_group") is not None:
            expected_pod_sec["fsGroup"] = w_spec["fs_group"]
        assert pod["securityContext"] == expected_pod_sec

        primary = pod["containers"][0]
        assert primary["name"] == name
        assert primary["image"] == w_spec["image"]
        assert primary["imagePullPolicy"] == "Always"
        expected_cpu = "1" if w_spec["cpu"] == "1000m" else w_spec["cpu"]
        assert primary["resources"] == {
            "requests": {"cpu": expected_cpu, "memory": w_spec["memory"]},
            "limits": {"cpu": expected_cpu, "memory": w_spec["memory"]},
        }
        assert primary["securityContext"] == {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
            "capabilities": {"drop": ["ALL"]},
        }
        assert primary["readinessProbe"]["httpGet"]["path"] == w_spec["readiness_path"]
        assert primary["livenessProbe"]["httpGet"]["path"] == w_spec["liveness_path"]
        assert primary["envFrom"] == [{"configMapRef": {"name": f"{name}-env", "optional": False}}]
        secret_keys = {item["name"] for item in primary.get("env", [])}
        assert secret_keys == set(w_spec["secret_environment"])

        svc = by_kind_name[("Service", name)]
        expected_svc_port = w_spec["service_port"] or w_spec["port"]
        assert svc["spec"]["ports"] == [
            {
                "name": "http",
                "port": expected_svc_port,
                "targetPort": w_spec["port"],
                "protocol": "TCP",
            }
        ]

    # Verify ClamAV sidecar and initContainer parity on document-processing-worker
    worker_deployment = by_kind_name[("Deployment", "document-processing-worker")]
    worker_pod = worker_deployment["spec"]["template"]["spec"]
    assert len(worker_pod["containers"]) == 2
    clamav = worker_pod["containers"][1]
    assert clamav["name"] == "clamav"
    assert clamav["image"] == workloads["document-processing-worker"]["sidecars"]["clamav"]["image"]
    assert clamav["command"] == ["clamd"]
    assert clamav["args"] == ["--foreground=true"]
    assert clamav["readinessProbe"]["tcpSocket"] == {"port": 3310}
    assert len(worker_pod["initContainers"]) == 1
    init_c = worker_pod["initContainers"][0]
    assert init_c["name"] == "clamav-database"
    assert init_c["image"] == clamav["image"]
    assert init_c["volumeMounts"] == [{"name": "clamav-database", "mountPath": "/target"}]

    # Verify CronJob parity against infra/runtimes/aks/workloads/main.tf
    assert (
        generated.prerequisites.config_map_data["core-control-plane-env"][
            "FDAI_CANARY_OBSERVER_NAMESPACE"
        ]
        == "fdai-runtime"
    )
    assert (
        generated.prerequisites.config_map_data["core-control-plane-env"][
            "FDAI_CANARY_OBSERVER_CRONJOB"
        ]
        == "canary"
    )
    assert (
        generated.prerequisites.secret_bindings["core-control-plane"]["FDAI_STATE_STORE_DSN"]
        == "fdai-state-store-dsn"
    )
    assert (
        generated.prerequisites.identity_bindings["operator-service"]["additional_identities"][
            "command"
        ]["client_id"]
        == _identity("command", 3)["client_id"]
    )

    for job_name, j_spec in scheduled_jobs.items():
        cron = by_kind_name[("CronJob", job_name)]
        assert cron["spec"]["schedule"] == j_spec["schedule"]
        assert cron["spec"]["concurrencyPolicy"] == "Forbid"
        assert cron["spec"]["timeZone"] == "Etc/UTC"
        assert (
            cron["spec"]["jobTemplate"]["metadata"]["labels"]["app.kubernetes.io/name"] == job_name
        )
        assert (
            cron["spec"]["jobTemplate"]["metadata"]["labels"]["app.kubernetes.io/component"]
            == j_spec["component"]
        )
        job_body = cron["spec"]["jobTemplate"]["spec"]
        assert job_body["activeDeadlineSeconds"] == j_spec["deadline_seconds"]
        assert job_body["backoffLimit"] == 0
        c_pod = job_body["template"]["spec"]
        assert c_pod["serviceAccountName"] == f"{job_name}-job"
        assert c_pod["restartPolicy"] == "Never"
        c_container = c_pod["containers"][0]
        assert c_container["name"] == job_name
        assert c_container["image"] == j_spec["image"]
        assert c_container["command"] == j_spec["command"]
        if job_name == "canary":
            assert any(
                env_item.get("name") == "FDAI_CANARY_JOB_UID"
                and env_item.get("valueFrom", {}).get("fieldRef", {}).get("fieldPath")
                == "metadata.labels['batch.kubernetes.io/controller-uid']"
                for env_item in c_container.get("env", [])
            )


def test_generator_rejects_conflicting_observer_env_and_invalid_inputs() -> None:
    workloads, scheduled_jobs = _stewardship_topology_fixture()

    bad_observer = dict(workloads)
    bad_observer["core-control-plane"] = {
        **workloads["core-control-plane"],
        "environment": {
            **workloads["core-control-plane"]["environment"],
            "FDAI_CANARY_OBSERVER_CRONJOB": "other",
        },
    }
    with pytest.raises(ValueError, match="FDAI_CANARY_OBSERVER_CRONJOB conflicts"):
        generate_fdai_runtime_bundle(
            workloads=bad_observer,
            scheduled_jobs=scheduled_jobs,
            installation_id="installation-fdai-dev-wus3",
        )

    overlap_env = dict(workloads)
    overlap_env["core-control-plane"] = {
        **workloads["core-control-plane"],
        "environment": {
            **workloads["core-control-plane"]["environment"],
            "FDAI_STATE_STORE_DSN": "inline",
        },
    }
    with pytest.raises(ValueError, match="overlap"):
        generate_fdai_runtime_bundle(
            workloads=overlap_env,
            scheduled_jobs=scheduled_jobs,
            installation_id="installation-fdai-dev-wus3",
        )

    bool_replicas = dict(workloads)
    bool_replicas["core-control-plane"] = {
        **workloads["core-control-plane"],
        "replicas": True,
    }
    with pytest.raises(ValueError, match="replicas must be an integer"):
        generate_fdai_runtime_bundle(
            workloads=bool_replicas,
            scheduled_jobs=scheduled_jobs,
            installation_id="installation-fdai-dev-wus3",
        )


def test_cli_generates_bundle_and_prepares_fourteen_day_development_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workloads, scheduled_jobs = _stewardship_topology_fixture()
    topology_path = tmp_path / "topology.json"
    topology_path.write_text(
        json.dumps(
            {
                "workloads": workloads,
                "scheduled_jobs": scheduled_jobs,
                "identity_bridge_config_map": "fdai-identity-bridge",
            }
        ),
        encoding="utf-8",
    )
    topology_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    bundle_dir = tmp_path / "generated"
    exit_code = main(
        [
            "generate-runtime-bundle",
            "--topology-input",
            str(topology_path),
            "--destination",
            str(bundle_dir),
            "--installation-id",
            "installation-fdai-dev-wus3",
            "--entity-id",
            "fdai-workloads",
            "--product",
            "fdai",
            "--namespace",
            "fdai-runtime",
        ]
    )
    assert exit_code == 0

    hub_key = Ed25519PrivateKey.generate()
    release_key = Ed25519PrivateKey.generate()
    hub_pub = tmp_path / "hub-public.pem"
    release_pub = tmp_path / "release-public.pem"
    for path, key in ((hub_pub, hub_key), (release_pub, release_key)):
        path.write_bytes(
            key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    monkeypatch.setattr(
        "fdai_lifecycle_manager.preparation.inspect_source",
        lambda root: type("Source", (), {"commit": "a" * 40})(),
    )
    now = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    prepared_dir = tmp_path / "prepared"
    receipt = prepare_installation(
        source_root=tmp_path,
        destination=prepared_dir,
        runtime_bundle_path=bundle_dir / "runtime-bundle.json",
        component_images_path=bundle_dir / "component-images.json",
        hub_public_key_path=hub_pub,
        release_public_key_path=release_pub,
        installation_id="installation-fdai-dev-wus3",
        entity_id="fdai-workloads",
        product="fdai",
        release_id="0.4.0",
        channel="DEV",
        region="westus3",
        actor="owner@example.com",
        now=now,
    )
    native_scope = json.loads((bundle_dir / "native-scope.json").read_text(encoding="utf-8"))
    approval = json.loads((prepared_dir / "native-approval.json").read_text(encoding="utf-8"))
    assert approval["scope"] == native_scope
    assert approval["profile"] == "full-authority-development"
    assert approval["expires_at"] == "2026-10-24T16:00:00Z"
    assert receipt.runtime_bundle_digest.startswith("sha256:")
    assert receipt.native_scope_digest.startswith("sha256:")

    with pytest.raises(ValueError, match="digest-pinned image"):
        bad_workloads = dict(workloads)
        bad_workloads["core-control-plane"] = {
            **workloads["core-control-plane"],
            "image": "registry.example.test/fdai/core-control-plane:latest",
        }
        generate_fdai_runtime_bundle(
            workloads=bad_workloads,
            scheduled_jobs=scheduled_jobs,
            installation_id="installation-fdai-dev-wus3",
        )
    _ = write_generated_runtime_bundle
