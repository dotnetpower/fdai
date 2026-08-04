"""Namespace and projection tests for kubectl evaluation evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai_evaluation_sdk import EvaluationTask, ResourceLimits, TargetRef

from fdai.delivery.evaluation import KubectlEvidenceClient, KubectlEvidenceConfig
from fdai.delivery.evaluation.kubernetes_evidence import (
    KubectlEventEvidenceProvider,
    KubectlInventoryEvidenceProvider,
)
from fdai.delivery.kubernetes.owners import CustomOwnerQuery

_NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _task(namespace: str = "example-app") -> EvaluationTask:
    return EvaluationTask(
        session_id="session-1",
        task_id="task-1",
        phase="diagnosis",
        objective="Diagnose the synthetic application.",
        target=TargetRef(kind="kubernetes.namespace", value=namespace),
        deadline=_NOW + timedelta(minutes=5),
        resource_limits=ResourceLimits(
            cpu_seconds=60,
            memory_bytes=268_435_456,
            process_count=16,
            output_bytes=1_048_576,
            wall_clock_seconds=120,
        ),
    )


def _config(kubeconfig: Path, **overrides: object) -> KubectlEvidenceConfig:
    values: dict[str, object] = {
        "kubeconfig": kubeconfig,
        "context": "example-context",
        "cluster_name": "example-cluster",
        "allowed_namespaces": frozenset({"example-app"}),
    }
    values.update(overrides)
    return KubectlEvidenceConfig(**values)  # type: ignore[arg-type]


async def test_inventory_uses_explicit_context_and_projects_diagnostic_fields(
    tmp_path: Path,
) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    async def run(command: tuple[str, ...]) -> bytes:
        commands.append(command)
        return json.dumps(
            {
                "items": [
                    {
                        "kind": "Pod",
                        "metadata": {"name": "api-1", "namespace": "example-app"},
                        "spec": {"nodeName": "worker-1", "secretName": "not-exposed"},
                        "status": {
                            "phase": "Pending",
                            "containerStatuses": [
                                {
                                    "name": "api",
                                    "ready": False,
                                    "restartCount": 3,
                                    "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                                    "lastState": {
                                        "terminated": {
                                            "reason": "Error",
                                            "exitCode": 137,
                                            "finishedAt": "2026-07-29T11:59:50Z",
                                        }
                                    },
                                }
                            ],
                        },
                    },
                    {
                        "kind": "Secret",
                        "metadata": {"name": "credential", "namespace": "example-app"},
                        "data": {"password": "must-not-escape"},
                    },
                ]
            }
        ).encode()

    client = KubectlEvidenceClient(
        config=_config(
            kubeconfig,
            allowed_namespaces=frozenset({"example-app", "operator-system"}),
        ),
        run=run,
    )
    evidence = await client.inventory(_task())

    assert len(commands) == 1
    assert commands[0][:7] == (
        "kubectl",
        "--kubeconfig",
        str(kubeconfig),
        "--context",
        "example-context",
        "--namespace",
        "example-app",
    )
    assert evidence["resources"] == [
        {
            "kind": "Pod",
            "name": "api-1",
            "namespace": "example-app",
            "phase": "Pending",
            "node": "worker-1",
            "deleting": False,
            "containers": [
                {
                    "name": "api",
                    "ready": False,
                    "restarts": 3,
                    "state": "waiting",
                    "reason": "CrashLoopBackOff",
                    "last_termination": {
                        "reason": "Error",
                        "exit_code": 137,
                        "finished_at": "2026-07-29T11:59:50Z",
                    },
                }
            ],
        }
    ]
    assert "not-exposed" not in json.dumps(evidence)
    assert "must-not-escape" not in json.dumps(evidence)


async def test_pod_metrics_are_namespace_scoped_and_normalized(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    async def run(command: tuple[str, ...]) -> bytes:
        commands.append(command)
        return json.dumps(
            {
                "items": [
                    {
                        "metadata": {"name": "sub-agent-1", "namespace": "example-app"},
                        "containers": [
                            {
                                "name": "agent",
                                "usage": {"cpu": "925m", "memory": "128Mi"},
                            },
                            {
                                "name": "proxy",
                                "usage": {"cpu": "250000n", "memory": "1024Ki"},
                            },
                        ],
                    }
                ]
            }
        ).encode()

    client = KubectlEvidenceClient(config=_config(kubeconfig), run=run)
    evidence = await client.pod_metrics(_task())

    assert commands == [
        (
            "kubectl",
            "--kubeconfig",
            str(kubeconfig),
            "--context",
            "example-context",
            "--namespace",
            "example-app",
            "get",
            "--raw",
            "/apis/metrics.k8s.io/v1beta1/namespaces/example-app/pods",
            "--request-timeout=15s",
        )
    ]
    assert evidence == {
        "cluster": "example-cluster",
        "namespace": "example-app",
        "pods": [
            {
                "name": "sub-agent-1",
                "namespace": "example-app",
                "containers": [
                    {"name": "agent", "cpu_millicores": 925.0, "memory_bytes": 134_217_728},
                    {"name": "proxy", "cpu_millicores": 0.25, "memory_bytes": 1_048_576},
                ],
            }
        ],
        "truncated": False,
    }


async def test_inventory_projects_pod_request_semantics_and_uid(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")

    async def run(command: tuple[str, ...]) -> bytes:
        del command
        return json.dumps(
            {
                "items": [
                    {
                        "kind": "Pod",
                        "metadata": {
                            "name": "worker-a",
                            "namespace": "example-app",
                            "uid": "pod-uid",
                        },
                        "spec": {
                            "containers": [
                                {
                                    "name": "main",
                                    "image": "must-not-project",
                                    "resources": {"requests": {"cpu": "750m", "memory": "2Gi"}},
                                }
                            ],
                            "initContainers": [
                                {
                                    "name": "init",
                                    "resources": {"requests": {"cpu": "1", "memory": "1Gi"}},
                                }
                            ],
                        },
                        "status": {"phase": "Pending", "containerStatuses": []},
                    }
                ]
            }
        ).encode()

    evidence = await KubectlEvidenceClient(config=_config(kubeconfig), run=run).inventory(_task())

    assert evidence["resources"][0]["uid"] == "pod-uid"
    assert evidence["resources"][0]["resource_requests"] == {
        "projection_complete": True,
        "source_paths": {
            "cpu": [
                "/spec/containers/0/resources/requests/cpu",
                "/spec/initContainers/0/resources/requests/cpu",
            ],
            "memory": [
                "/spec/containers/0/resources/requests/memory",
                "/spec/initContainers/0/resources/requests/memory",
            ],
        },
        "cpu_base_units": "1",
        "memory_base_units": "2147483648",
    }
    assert "must-not-project" not in json.dumps(evidence)


async def test_inventory_projects_bounded_immutable_owner_references(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")

    async def run(command: tuple[str, ...]) -> bytes:
        del command
        return json.dumps(
            {
                "items": [
                    {
                        "kind": "Deployment",
                        "metadata": {
                            "name": "api",
                            "namespace": "example-app",
                            "uid": "deployment-uid",
                            "ownerReferences": [
                                {
                                    "apiVersion": "database.example.io/v1",
                                    "kind": "Database",
                                    "name": "catalog",
                                    "uid": "owner-uid",
                                    "controller": True,
                                    "blockOwnerDeletion": True,
                                }
                            ],
                        },
                        "spec": {"replicas": 1},
                        "status": {"readyReplicas": 1},
                    }
                ]
            }
        ).encode()

    evidence = await KubectlEvidenceClient(config=_config(kubeconfig), run=run).inventory(_task())

    resource = evidence["resources"][0]
    assert resource["uid"] == "deployment-uid"
    assert resource["owner_reference_projection_complete"] is True
    assert resource["owner_references"] == [
        {
            "api_version": "database.example.io/v1",
            "kind": "Database",
            "name": "catalog",
            "uid": "owner-uid",
            "controller": True,
        }
    ]
    assert "blockOwnerDeletion" not in json.dumps(evidence)


async def test_inventory_provider_adds_hold_only_image_drift_candidates() -> None:
    class _InventoryClient:
        async def inventory(self, task: EvaluationTask) -> Mapping[str, Any]:
            del task
            return {
                "resources": _image_drift_resources(),
                "truncated": False,
            }

    evidence = await KubectlInventoryEvidenceProvider(
        _InventoryClient()  # type: ignore[arg-type]
    ).collect(_task())

    assert evidence["evidence_complete"] is True
    assert evidence["findings"][0]["reason"] == (
        "pod_image_pull_controller_template_drift_candidate"
    )
    assert evidence["findings"][0]["decision"] == "hold"


async def test_event_provider_correlates_recent_exact_uid_host_port_conflict() -> None:
    class _SchedulingClient:
        async def inventory(self, task: EvaluationTask) -> Mapping[str, Any]:
            del task
            return {"resources": _host_port_resources(), "truncated": False}

        async def events(self, task: EvaluationTask) -> Mapping[str, Any]:
            del task
            return {"events": _host_port_events(), "truncated": False}

    evidence = await KubectlEventEvidenceProvider(
        _SchedulingClient(),  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    ).collect(_task())

    assert evidence["evidence_complete"] is True
    assert evidence["findings"][0]["reason"] == "pod_host_port_conflict_candidate"
    assert evidence["findings"][0]["resource"]["uid"] == "pod-uid"
    assert evidence["findings"][0]["decision"] == "hold"


async def test_inventory_projects_only_active_admission_conditions(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")

    async def run(command: tuple[str, ...]) -> bytes:
        del command
        return json.dumps(
            {
                "items": [
                    {
                        "kind": "ReplicaSet",
                        "metadata": {"name": "api-1", "namespace": "example-app"},
                        "spec": {"replicas": 1},
                        "status": {
                            "readyReplicas": 0,
                            "conditions": [
                                {
                                    "type": "Progressing",
                                    "status": "True",
                                    "reason": "NewReplicaSetAvailable",
                                    "message": "must-not-project",
                                },
                                {
                                    "type": "ReplicaFailure",
                                    "status": "False",
                                    "reason": "FailedCreate",
                                    "message": (
                                        'failed calling webhook "old.example.io": '
                                        "context deadline exceeded"
                                    ),
                                },
                                {
                                    "type": "ReplicaFailure",
                                    "status": "True",
                                    "reason": "FailedCreate",
                                    "message": (
                                        'failed calling webhook "policy.example.io": '
                                        "context deadline exceeded; token=must-not-project"
                                    ),
                                },
                            ],
                        },
                    }
                ]
            }
        ).encode()

    evidence = await KubectlEvidenceClient(config=_config(kubeconfig), run=run).inventory(_task())

    resource = evidence["resources"][0]
    assert resource["admission_condition_projection_complete"] is True
    assert resource["admission_conditions"] == [
        {
            "type": "ReplicaFailure",
            "status": "True",
            "reason": "FailedCreate",
            "code": "admission_webhook_timeout",
            "source_index": 2,
            "webhook_name": "policy.example.io",
        }
    ]
    assert "must-not-project" not in json.dumps(evidence)
    assert "old.example.io" not in json.dumps(evidence)


async def test_custom_owner_lookup_is_exact_namespaced_and_uid_grounded(
    tmp_path: Path,
) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    async def run(command: tuple[str, ...]) -> bytes:
        commands.append(command)
        return json.dumps(
            {
                "apiVersion": "database.example.io/v1",
                "kind": "Database",
                "metadata": {
                    "name": "catalog",
                    "namespace": "example-app",
                    "uid": "owner-uid",
                    "resourceVersion": "7",
                    "generation": 3,
                },
                "spec": {"password": "must-not-project"},
                "status": {"conditions": []},
            }
        ).encode()

    client = KubectlEvidenceClient(config=_config(kubeconfig), run=run)
    owner = await client.custom_owner(
        _task(),
        CustomOwnerQuery("database.database.example.io/catalog", "owner-uid"),
    )

    assert commands[0][-5:] == (
        "get",
        "database.database.example.io/catalog",
        "--output",
        "json",
        "--request-timeout=15s",
    )
    assert "--namespace" in commands[0]
    assert owner is not None
    assert owner["uid"] == "owner-uid"
    assert "must-not-project" not in json.dumps(owner)


async def test_inventory_projects_only_reviewed_workload_endpoint_structure(
    tmp_path: Path,
) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")

    async def run(command: tuple[str, ...]) -> bytes:
        del command
        return json.dumps(
            {
                "items": [
                    {
                        "kind": "Deployment",
                        "metadata": {"name": "frontend", "namespace": "example-app"},
                        "spec": {
                            "replicas": 2,
                            "template": {
                                "spec": {
                                    "containers": [
                                        {
                                            "name": "frontend",
                                            "image": "must-not-project",
                                            "command": ["must-not-project"],
                                            "ports": [{"containerPort": 8080}],
                                            "env": [
                                                {"name": "BACKEND", "value": "catalog:8080"},
                                                {"name": "TOKEN", "value": "must-not-project"},
                                                {
                                                    "name": "SECRET",
                                                    "valueFrom": {
                                                        "secretKeyRef": {"name": "secret"}
                                                    },
                                                },
                                            ],
                                        }
                                    ]
                                }
                            },
                        },
                        "status": {"readyReplicas": 2},
                    }
                ]
            }
        ).encode()

    evidence = await KubectlEvidenceClient(config=_config(kubeconfig), run=run).inventory(_task())

    assert evidence["resources"][0]["pod_template"] == {
        "projection_complete": True,
        "containers": [
            {
                "name": "frontend",
                "image_reference_sha256": hashlib.sha256(b"must-not-project").hexdigest(),
                "resource_projection_complete": True,
                "resources": {},
                "port_projection_complete": True,
                "ports": [{"port": 8080}],
                "env_projection_complete": True,
                "env": [
                    {
                        "name": "BACKEND",
                        "endpoint_host": "catalog",
                        "endpoint_port": "8080",
                    }
                ],
            }
        ],
    }
    assert "must-not-project" not in json.dumps(evidence)
    assert "secret" not in json.dumps(evidence).casefold()


async def test_nodes_use_cluster_scope_and_project_only_capacity_facts(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    async def run(command: tuple[str, ...]) -> bytes:
        commands.append(command)
        return json.dumps(
            {
                "items": [
                    {
                        "kind": "Node",
                        "metadata": {
                            "name": "worker-a",
                            "labels": {"private.example/owner": "must-not-project"},
                        },
                        "spec": {"unschedulable": False},
                        "status": {
                            "addresses": [{"address": "192.0.2.10"}],
                            "allocatable": {
                                "cpu": "4",
                                "memory": "8Gi",
                                "private.example/device": "2",
                            },
                            "conditions": [{"type": "Ready", "status": "True"}],
                        },
                    },
                    {
                        "kind": "Node",
                        "metadata": {"name": "worker-b"},
                        "spec": {"unschedulable": True},
                        "status": {
                            "allocatable": {"cpu": "invalid", "memory": "16Gi"},
                            "conditions": [{"type": "Ready", "status": "False"}],
                        },
                    },
                ]
            }
        ).encode()

    client = KubectlEvidenceClient(config=_config(kubeconfig), run=run)
    evidence = await client.nodes(_task())

    assert "--namespace" not in commands[0]
    assert commands[0][-5:] == (
        "get",
        "nodes",
        "--output",
        "json",
        "--request-timeout=15s",
    )
    assert evidence == {
        "cluster": "example-cluster",
        "nodes": [
            {
                "name": "worker-a",
                "ready": True,
                "unschedulable": False,
                "allocatable": {"cpu": "4", "memory": "8Gi"},
                "allocatable_projection_complete": True,
            },
            {
                "name": "worker-b",
                "ready": False,
                "unschedulable": True,
                "allocatable": {"memory": "16Gi"},
                "allocatable_projection_complete": False,
            },
        ],
        "truncated": False,
    }


async def test_admission_configurations_are_cluster_scoped_and_bounded(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    async def run(command: tuple[str, ...]) -> bytes:
        commands.append(command)
        return json.dumps(
            {
                "items": [
                    {
                        "kind": "MutatingWebhookConfiguration",
                        "metadata": {
                            "name": "resource-defaulting",
                            "labels": {"private.example/owner": "must-not-project"},
                        },
                        "webhooks": [
                            {
                                "name": "mutate.example.com",
                                "clientConfig": {
                                    "url": "https://must-not-project.example.com",
                                    "caBundle": "must-not-project",
                                },
                                "objectSelector": {},
                                "namespaceSelector": {},
                                "matchConditions": [],
                                "failurePolicy": "Fail",
                                "timeoutSeconds": 10,
                                "rules": [
                                    {
                                        "operations": ["CREATE"],
                                        "apiGroups": [""],
                                        "apiVersions": ["v1"],
                                        "resources": ["pods"],
                                        "scope": "Namespaced",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ).encode()

    client = KubectlEvidenceClient(config=_config(kubeconfig), run=run)
    evidence = await client.admission_configurations(_task())

    assert "--namespace" not in commands[0]
    assert commands[0][-5:] == (
        "get",
        "mutatingwebhookconfigurations,validatingwebhookconfigurations",
        "--output",
        "json",
        "--request-timeout=15s",
    )
    assert evidence == {
        "cluster": "example-cluster",
        "resources": [
            {
                "kind": "MutatingWebhookConfiguration",
                "name": "resource-defaulting",
                "namespace": "",
                "projection_complete": True,
                "webhooks": [
                    {
                        "name": "mutate.example.com",
                        "projection_complete": True,
                        "object_selector": {},
                        "namespace_selector": {},
                        "match_conditions": [],
                        "failure_policy": "Fail",
                        "timeout_seconds": 10,
                        "service": {},
                        "rules": [
                            {
                                "projection_complete": True,
                                "operations": ["CREATE"],
                                "api_groups": [""],
                                "api_versions": ["v1"],
                                "resources": ["pods"],
                                "scope": "Namespaced",
                            }
                        ],
                    }
                ],
            }
        ],
        "truncated": False,
    }
    assert "must-not-project" not in json.dumps(evidence)


async def test_events_are_bounded_and_namespace_scope_fails_closed(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")

    async def run(command: tuple[str, ...]) -> bytes:
        del command
        return json.dumps(
            {
                "items": [
                    {
                        "metadata": {"name": f"event-{index}", "namespace": "example-app"},
                        "type": "Warning",
                        "reason": "Failed",
                        "message": "x" * 2_000,
                        "count": index,
                        "involvedObject": {"kind": "Pod", "name": "api-1"},
                    }
                    for index in range(3)
                ]
            }
        ).encode()

    client = KubectlEvidenceClient(
        config=_config(kubeconfig, max_items=2),
        run=run,
    )
    evidence = await client.events(_task())

    assert [item["name"] for item in evidence["events"]] == ["event-1", "event-2"]
    assert len(evidence["events"][0]["message"]) == 1_024
    assert evidence["truncated"] is True
    with pytest.raises(ValueError, match="outside the configured scope"):
        await client.inventory(_task("other-app"))


@pytest.mark.parametrize(
    ("message", "expected_code", "expected_webhook"),
    [
        (
            'failed calling webhook "policy.example.io": tls: failed to verify certificate: '
            "x509: certificate signed by unknown authority",
            "admission_webhook_tls_failure",
            "policy.example.io",
        ),
        (
            'failed calling webhook "policy.example.io": context deadline exceeded',
            "admission_webhook_timeout",
            "policy.example.io",
        ),
        (
            'pods "api-1" is forbidden: violates PodSecurity "restricted:latest": '
            "allowPrivilegeEscalation != false",
            "pod_security_admission_rejected",
            None,
        ),
    ],
)
async def test_events_structure_admission_failures_without_raw_message(
    tmp_path: Path,
    message: str,
    expected_code: str,
    expected_webhook: str | None,
) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")

    async def run(command: tuple[str, ...]) -> bytes:
        del command
        return json.dumps(
            {
                "items": [
                    {
                        "metadata": {"name": "event-1", "namespace": "example-app"},
                        "type": "Warning",
                        "reason": "FailedCreate",
                        "message": message,
                        "count": 1,
                        "involvedObject": {"kind": "ReplicaSet", "name": "api-1"},
                    }
                ]
            }
        ).encode()

    evidence = await KubectlEvidenceClient(config=_config(kubeconfig), run=run).events(_task())

    event = evidence["events"][0]
    assert event["code"] == expected_code
    assert event.get("webhook_name") == expected_webhook
    assert "message" not in event
    assert message not in json.dumps(evidence)


async def test_events_structure_host_port_conflict_without_raw_message(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")
    raw_message = "3 node(s) didn't have free ports for the requested pod ports"

    async def run(command: tuple[str, ...]) -> bytes:
        del command
        return json.dumps(
            {
                "items": [
                    {
                        "metadata": {
                            "name": "event-1",
                            "namespace": "example-app",
                            "creationTimestamp": "2026-07-29T11:59:00Z",
                        },
                        "reason": "FailedScheduling",
                        "message": raw_message,
                        "involvedObject": {
                            "kind": "Pod",
                            "name": "api-1",
                            "uid": "pod-uid",
                        },
                    }
                ]
            }
        ).encode()

    evidence = await KubectlEvidenceClient(config=_config(kubeconfig), run=run).events(_task())

    assert evidence["events"][0]["code"] == "host_port_conflict"
    assert evidence["events"][0]["regarding"]["uid"] == "pod-uid"
    assert "message" not in evidence["events"][0]
    assert raw_message not in json.dumps(evidence)


async def test_inventory_projects_bounded_host_ports(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")

    async def run(command: tuple[str, ...]) -> bytes:
        del command
        return json.dumps(
            {
                "items": [
                    {
                        "kind": "Pod",
                        "metadata": {
                            "name": "api-1",
                            "namespace": "example-app",
                            "uid": "pod-uid",
                        },
                        "spec": {
                            "containers": [
                                {
                                    "name": "api",
                                    "ports": [
                                        {"containerPort": 8080},
                                        {"containerPort": 9090, "hostPort": 9100},
                                    ],
                                }
                            ]
                        },
                        "status": {"containerStatuses": []},
                    }
                ]
            }
        ).encode()

    evidence = await KubectlEvidenceClient(config=_config(kubeconfig), run=run).inventory(_task())

    container = evidence["resources"][0]["pod_spec"]["containers"][0]
    assert container["host_port_projection_complete"] is True
    assert container["host_ports"] == [{"host_port": 9100, "protocol": "TCP", "source_index": 1}]


async def test_invalid_or_oversized_kubectl_payload_is_rejected(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")

    async def invalid(command: tuple[str, ...]) -> bytes:
        del command
        return b"not-json"

    client = KubectlEvidenceClient(config=_config(kubeconfig), run=invalid)
    with pytest.raises(RuntimeError, match="invalid evidence JSON"):
        await client.inventory(_task())

    async def oversized(command: tuple[str, ...]) -> bytes:
        del command
        return b"x" * 1_025

    limited = KubectlEvidenceClient(
        config=_config(kubeconfig, max_output_bytes=1_024),
        run=oversized,
    )
    with pytest.raises(RuntimeError, match="exceeded"):
        await limited.inventory(_task())


def _image_drift_resources() -> list[dict[str, Any]]:
    observed = hashlib.sha256(b"registry.example/api:broken").hexdigest()
    expected = hashlib.sha256(b"registry.example/api:v1").hexdigest()
    return [
        {
            "kind": "Pod",
            "name": "api-1-abc",
            "namespace": "example-app",
            "uid": "pod-uid",
            "owner_reference_projection_complete": True,
            "owner_references": [
                {
                    "kind": "ReplicaSet",
                    "name": "api-1",
                    "uid": "rs-uid",
                    "controller": True,
                }
            ],
            "containers": [{"name": "api", "state": "waiting", "reason": "ImagePullBackOff"}],
            "pod_spec": {
                "projection_complete": True,
                "containers": [{"name": "api", "image_reference_sha256": observed}],
            },
        },
        {
            "kind": "ReplicaSet",
            "name": "api-1",
            "namespace": "example-app",
            "uid": "rs-uid",
            "owner_reference_projection_complete": True,
            "owner_references": [
                {
                    "kind": "Deployment",
                    "name": "api",
                    "uid": "deployment-uid",
                    "controller": True,
                }
            ],
        },
        {
            "kind": "Deployment",
            "name": "api",
            "namespace": "example-app",
            "uid": "deployment-uid",
            "pod_template": {
                "projection_complete": True,
                "containers": [{"name": "api", "image_reference_sha256": expected}],
            },
        },
    ]


def _host_port_resources() -> list[dict[str, Any]]:
    return [
        {
            "kind": "Pod",
            "name": "api-1",
            "namespace": "example-app",
            "uid": "pod-uid",
            "pod_spec": {
                "projection_complete": True,
                "containers": [
                    {
                        "name": "api",
                        "host_port_projection_complete": True,
                        "host_ports": [{"host_port": 9100, "protocol": "TCP", "source_index": 0}],
                    }
                ],
            },
        }
    ]


def _host_port_events() -> list[dict[str, Any]]:
    return [
        {
            "name": "scheduler-1",
            "namespace": "example-app",
            "code": "host_port_conflict",
            "last_seen": "2026-08-04T11:59:00Z",
            "regarding": {"kind": "Pod", "name": "api-1", "uid": "pod-uid"},
        }
    ]
