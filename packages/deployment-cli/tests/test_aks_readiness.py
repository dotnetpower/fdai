"""Realistic Kubernetes observations must prove the complete selected workload set."""

from __future__ import annotations

import copy
import json

import pytest

from fdai_deployment_cli.aks_readiness import verify_workload_health

SOURCE = "c" * 40
IMAGE = "example.com/fdai/service@sha256:" + "a" * 64
NAMES = ("core-control-plane", "operator-service", "isolated-executor")


def _observations():
    deployments, pods = [], []
    for name in NAMES:
        labels = {"app.kubernetes.io/name": name, "fdai.io/source-commit": SOURCE}
        deployments.append(
            {
                "metadata": {"name": name, "generation": 2},
                "spec": {
                    "replicas": 1,
                    "template": {
                        "metadata": {"labels": labels},
                        "spec": {"containers": [{"name": name, "image": IMAGE}]},
                    },
                },
                "status": {
                    "observedGeneration": 2,
                    "replicas": 1,
                    "updatedReplicas": 1,
                    "readyReplicas": 1,
                    "availableReplicas": 1,
                },
            }
        )
        pods.append(
            {
                "metadata": {"name": name + "-pod", "labels": labels},
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                    "containerStatuses": [
                        {
                            "name": name,
                            "image": IMAGE,
                            "imageID": "docker-pullable://" + IMAGE,
                            "ready": True,
                            "state": {"running": {}},
                        }
                    ],
                },
            }
        )
    return {"kind": "DeploymentList", "items": deployments}, {"kind": "PodList", "items": pods}


def _verify(deployments, pods):
    return verify_workload_health(
        deployments=json.dumps(deployments),
        pods=json.dumps(pods),
        source_commit=SOURCE,
        expected={name: {"image": IMAGE, "replicas": 1, "max_replicas": 3} for name in NAMES},
    )


def test_complete_current_workloads_are_healthy() -> None:
    assert _verify(*_observations())


def test_selected_workload_can_use_its_own_source_revision() -> None:
    deployments, pods = _observations()
    deployments["items"] = deployments["items"][:1]
    pods["items"] = pods["items"][:1]
    selected = deployments["items"][0]["metadata"]["name"]

    assert verify_workload_health(
        deployments=json.dumps(deployments),
        pods=json.dumps(pods),
        expected={
            selected: {
                "image": IMAGE,
                "replicas": 1,
                "max_replicas": 3,
                "source_commit": SOURCE,
            }
        },
    )


@pytest.mark.parametrize(
    "defect",
    [
        "empty",
        "missing",
        "duplicate",
        "stale",
        "image",
        "pod-image",
        "pod-source",
        "unready",
        "missing-pod",
        "terminating",
        "generation",
        "boolean-replicas",
    ],
)
def test_incomplete_workloads_are_not_healthy(defect: str) -> None:
    deployments, pods = copy.deepcopy(_observations())
    deployment, pod = deployments["items"][0], pods["items"][0]
    if defect == "empty":
        deployments["items"] = []
    elif defect == "missing":
        deployments["items"].pop()
    elif defect == "duplicate":
        deployments["items"].append(deployment)
    elif defect == "stale":
        deployment["status"]["observedGeneration"] = 1
    elif defect == "image":
        deployment["spec"]["template"]["spec"]["containers"][0]["image"] = (
            "example.com/fdai/service:latest"
        )
    elif defect == "pod-image":
        pod["status"]["containerStatuses"][0]["imageID"] = (
            "docker-pullable://example.com/old@sha256:" + "b" * 64
        )
    elif defect == "pod-source":
        pod["metadata"]["labels"]["fdai.io/source-commit"] = "b" * 40
    elif defect == "unready":
        pod["status"]["conditions"] = []
    elif defect == "missing-pod":
        pods["items"].pop()
    elif defect == "terminating":
        pod["metadata"]["deletionTimestamp"] = "2026-09-14T00:00:00Z"
    elif defect == "generation":
        deployment["metadata"]["generation"] = 0
    else:
        deployment["spec"]["replicas"] = True
    assert not _verify(deployments, pods)


def test_malformed_observation_is_not_healthy() -> None:
    assert not verify_workload_health(
        deployments="{}", pods="{}", expected={}, source_commit=SOURCE
    )


SECRET_ENVIRONMENT = {
    "APPLICATIONINSIGHTS_CONNECTION_STRING": "fdai-application-insights-connection-string",
    "FDAI_STATE_STORE_DSN": "fdai-state-store-dsn",
}


def _secret_observations(environment):
    deployments, pods = copy.deepcopy(_observations())
    deployments["items"] = deployments["items"][:1]
    pods["items"] = pods["items"][:1]
    deployments["items"][0]["spec"]["template"]["spec"]["containers"][0]["env"] = environment
    return deployments, pods


def _verify_secret_contract(environment, secret_environment=SECRET_ENVIRONMENT):
    deployments, pods = _secret_observations(environment)
    name = deployments["items"][0]["metadata"]["name"]
    return verify_workload_health(
        deployments=json.dumps(deployments),
        pods=json.dumps(pods),
        source_commit=SOURCE,
        expected={
            name: {
                "image": IMAGE,
                "replicas": 1,
                "max_replicas": 3,
                "secret_environment": secret_environment,
            }
        },
    )


def _secret_reference(name, secret="core-control-plane", key=None):
    return {
        "name": name,
        "valueFrom": {"secretKeyRef": {"name": secret, "key": key or name}},
    }


def test_contracted_secret_bindings_are_healthy() -> None:
    assert _verify_secret_contract(
        [
            {"name": "RUNTIME_ENV", "value": "dev"},
            _secret_reference("APPLICATIONINSIGHTS_CONNECTION_STRING"),
            _secret_reference("FDAI_STATE_STORE_DSN"),
        ]
    )


def test_dropped_telemetry_secret_binding_fails_closed() -> None:
    assert not _verify_secret_contract(
        [
            {"name": "RUNTIME_ENV", "value": "dev"},
            _secret_reference("FDAI_STATE_STORE_DSN"),
        ]
    )


@pytest.mark.parametrize(
    "defect",
    ["extra", "foreign-secret", "mismatched-key", "duplicate", "literal", "malformed-reference"],
)
def test_drifted_secret_bindings_fail_closed(defect: str) -> None:
    environment = [
        _secret_reference("APPLICATIONINSIGHTS_CONNECTION_STRING"),
        _secret_reference("FDAI_STATE_STORE_DSN"),
    ]
    if defect == "extra":
        environment.append(_secret_reference("FDAI_GITOPS_TOKEN"))
    elif defect == "foreign-secret":
        environment[0] = _secret_reference(
            "APPLICATIONINSIGHTS_CONNECTION_STRING", secret="operator-service"
        )
    elif defect == "mismatched-key":
        environment[0] = _secret_reference(
            "APPLICATIONINSIGHTS_CONNECTION_STRING", key="FDAI_STATE_STORE_DSN"
        )
    elif defect == "duplicate":
        environment.append(_secret_reference("FDAI_STATE_STORE_DSN"))
    elif defect == "literal":
        environment[0] = {
            "name": "APPLICATIONINSIGHTS_CONNECTION_STRING",
            "value": "InstrumentationKey=redacted",
        }
    else:
        environment[0] = {
            "name": "APPLICATIONINSIGHTS_CONNECTION_STRING",
            "valueFrom": {"configMapKeyRef": {"name": "core-control-plane", "key": "x"}},
        }
    assert not _verify_secret_contract(environment)


@pytest.mark.parametrize("contract", [{"APPLICATIONINSIGHTS_CONNECTION_STRING": ""}, {"": "x"}, []])
def test_malformed_secret_contract_fails_closed(contract) -> None:
    assert not _verify_secret_contract(
        [_secret_reference("APPLICATIONINSIGHTS_CONNECTION_STRING")],
        secret_environment=contract,
    )


def test_absent_secret_contract_preserves_existing_readback() -> None:
    assert _verify_secret_contract(
        [_secret_reference("APPLICATIONINSIGHTS_CONNECTION_STRING")],
        secret_environment=None,
    )


@pytest.mark.parametrize(
    "defect", ["null-metadata", "null-container", "boolean-counter", "null-state"]
)
def test_malformed_provider_fields_fail_closed(defect: str) -> None:
    deployments, pods = _observations()
    if defect == "null-metadata":
        pods["items"][0]["metadata"] = None
    elif defect == "null-container":
        deployments["items"][0]["spec"]["template"]["spec"]["containers"] = [None]
    elif defect == "boolean-counter":
        deployments["items"][0]["status"]["availableReplicas"] = True
    else:
        pods["items"][0]["status"]["containerStatuses"][0]["state"] = None
    assert not _verify(deployments, pods)
