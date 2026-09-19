from __future__ import annotations

import copy

import pytest

from fdai_deployment_cli.aks_historical_reconciliation import (
    reconciled_variables,
    validate_reconciliation_plan,
)
from fdai_deployment_cli.aks_service_update import SERVICES


COMMIT = "a" * 40
IMAGE = "example.azurecr.io/{name}@sha256:" + "b" * 64
LEGACY_RUNTIME_ARGS = {
    "core-control-plane": "/app/.venv/bin/fdai-core-control-plane",
    "document-ingestion-api": "/app/.venv/bin/fdai-document-ingestion-api",
    "document-processing-worker": "/app/.venv/bin/fdai-document-processing-worker",
    "isolated-executor": "/app/.venv/bin/fdai-isolated-executor-service",
    "operator-service": "/app/.venv/bin/fdai-operator-service",
}


def _variables() -> dict[str, object]:
    return {
        "namespace": "fdai-runtime",
        "oidc_issuer_url": "https://issuer.example/",
        "workloads": {
            name: {
                "image": IMAGE.format(name=name),
                "source_commit": COMMIT,
                "additional_identities": {},
                "sidecars": {},
                "command": ["/app/.venv/bin/python"],
                "args": [
                    "/opt/fdai-compat/identity_bridge.py",
                    "--",
                    LEGACY_RUNTIME_ARGS[name],
                ],
            }
            for name in SERVICES
        },
    }


def _live() -> dict[str, object]:
    items = []
    for name in SERVICES:
        containers: list[dict[str, object]] = [
            {
                "name": name,
                "image": IMAGE.format(name=name),
                "command": ["/app/.venv/bin/python"],
                "args": [
                    "/opt/fdai-compat/identity_bridge.py",
                    "--",
                    LEGACY_RUNTIME_ARGS[name],
                ],
                "env": (
                    [
                        {
                            "name": "FDAI_COMMAND_MI_CLIENT_ID",
                            "value": "00000000-0000-0000-0000-000000000005",
                        }
                    ]
                    if name == "operator-service"
                    else []
                ),
            }
        ]
        volumes: list[dict[str, object]] = []
        if name == "document-processing-worker":
            containers.append(
                {
                    "name": "clamav",
                    "image": IMAGE.format(name="clamav"),
                    "ports": [{"containerPort": 3310, "protocol": "TCP"}],
                    "resources": {
                        "requests": {"cpu": "500m", "memory": "1Gi"},
                        "limits": {"cpu": "500m", "memory": "1Gi"},
                    },
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "readOnlyRootFilesystem": True,
                        "runAsUser": 100,
                        "runAsGroup": 101,
                        "capabilities": {"drop": ["ALL"]},
                    },
                    "volumeMounts": [
                        {"name": "clamav-database", "mountPath": "/var/lib/clamav"},
                        {"name": "clamav-run", "mountPath": "/run/clamav"},
                        {"name": "clamav-tmp", "mountPath": "/tmp"},
                    ],
                }
            )
            volumes = [
                {"name": "clamav-database", "emptyDir": {"sizeLimit": "1Gi"}},
                {"name": "clamav-run", "emptyDir": {"sizeLimit": "64Mi"}},
                {"name": "clamav-tmp", "emptyDir": {"sizeLimit": "256Mi"}},
            ]
        items.append(
            {
                "metadata": {"name": name},
                "spec": {
                    "template": {
                        "spec": {
                            "containers": containers,
                            "initContainers": (
                                [
                                    {
                                        "name": "clamav-database",
                                        "image": IMAGE.format(name="clamav"),
                                        "imagePullPolicy": "IfNotPresent",
                                        "command": ["/bin/sh", "-c"],
                                        "args": ["cp -a /var/lib/clamav/. /target/"],
                                        "securityContext": {
                                            "allowPrivilegeEscalation": False,
                                            "readOnlyRootFilesystem": True,
                                            "runAsUser": 100,
                                            "runAsGroup": 101,
                                            "capabilities": {"drop": ["ALL"]},
                                        },
                                        "volumeMounts": [
                                            {"mountPath": "/target", "name": "clamav-database"}
                                        ],
                                    }
                                ]
                                if name == "document-processing-worker"
                                else []
                            ),
                            "securityContext": (
                                {"fsGroup": 101} if name == "document-processing-worker" else {}
                            ),
                            "volumes": volumes,
                        }
                    }
                },
            }
        )
    return {"apiVersion": "apps/v1", "kind": "DeploymentList", "items": items}


def _state() -> dict[str, object]:
    return {
        "resources": [
            {
                "mode": "managed",
                "type": "kubernetes_config_map_v1",
                "name": "identity_bridge",
                "instances": [
                    {
                        "attributes": {
                            "metadata": [{"name": "fdai-identity-bridge"}],
                            "data": {"identity_bridge.py": "print('bridge')\n"},
                        }
                    }
                ],
            },
            {
                "mode": "managed",
                "type": "azurerm_federated_identity_credential",
                "name": "identity",
                "instances": [
                    {
                        "index_key": "workload-operator-service-command",
                        "attributes": {
                            "audience": ["api://AzureADTokenExchange"],
                            "issuer": "https://issuer.example/",
                            "parent_id": (
                                "/subscriptions/00000000-0000-0000-0000-000000000001/"
                                "resourceGroups/example/providers/Microsoft.ManagedIdentity/"
                                "userAssignedIdentities/command"
                            ),
                            "subject": "system:serviceaccount:fdai-runtime:operator-service",
                        },
                    }
                ],
            },
        ]
    }


def test_reconciled_variables_restore_only_command_identity_and_clamav() -> None:
    original = _variables()
    result = reconciled_variables(state=_state(), variables=original, live=_live())

    assert result is not original
    assert original["workloads"]["operator-service"]["additional_identities"] == {}
    command = result["workloads"]["operator-service"]["additional_identities"]["command"]
    assert command["client_id"] == "00000000-0000-0000-0000-000000000005"
    assert command["resource_id"].endswith("/userAssignedIdentities/command")
    assert all(
        workload["command"] == ["/app/.venv/bin/python"]
        for workload in result["workloads"].values()
    )
    assert all(workload["identity_bridge_enabled"] for workload in result["workloads"].values())
    assert result["identity_bridge"] == {
        "config_map_name": "fdai-identity-bridge",
        "script": "print('bridge')\n",
        "runtime_state_size_limit": "256Mi",
    }
    clamav = result["workloads"]["document-processing-worker"]["sidecars"]["clamav"]
    assert clamav == {
        "image": IMAGE.format(name="clamav"),
        "command": [],
        "args": [],
        "cpu": "500m",
        "memory": "1Gi",
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
            "run": {"mount_path": "/run/clamav", "size_limit": "64Mi"},
            "tmp": {"mount_path": "/tmp", "size_limit": "256Mi"},
        },
    }
    assert result["workloads"]["document-processing-worker"]["fs_group"] == 101


@pytest.mark.parametrize(
    "change", ["generic-list", "fic-subject", "command-client", "runtime-command", "clamav"]
)
def test_reconciled_variables_reject_untrusted_live_safety_input(change: str) -> None:
    state = _state()
    live = _live()
    if change == "generic-list":
        live["kind"] = "List"
    elif change == "fic-subject":
        credential = next(
            resource
            for resource in state["resources"]
            if resource["type"] == "azurerm_federated_identity_credential"
        )
        credential["instances"][0]["attributes"]["subject"] += "-other"
    elif change == "command-client":
        operator = next(
            item for item in live["items"] if item["metadata"]["name"] == "operator-service"
        )
        operator["spec"]["template"]["spec"]["containers"][0]["env"][0]["value"] = "invalid"
    elif change == "runtime-command":
        live["items"][0]["spec"]["template"]["spec"]["containers"][0]["args"][-1] = (
            "/app/.venv/bin/untrusted"
        )
    else:
        worker = next(
            item
            for item in live["items"]
            if item["metadata"]["name"] == "document-processing-worker"
        )
        worker["spec"]["template"]["spec"]["containers"][1]["image"] = "clamav:latest"

    with pytest.raises(ValueError):
        reconciled_variables(state=state, variables=_variables(), live=live)


def _terraform_workload(name: str, *, legacy: bool) -> dict[str, object]:
    legacy_runtime = name in LEGACY_RUNTIME_ARGS
    containers = [
        {
            "name": name,
            "image": IMAGE.format(name=name),
            "command": ["/app/.venv/bin/python"] if legacy_runtime else [],
            "args": (
                [
                    "/opt/fdai-compat/identity_bridge.py",
                    "--",
                    LEGACY_RUNTIME_ARGS[name],
                ]
                if legacy_runtime
                else []
            ),
            "volume_mount": (
                [
                    {"name": "identity-bridge"},
                    {"name": "runtime-state"},
                ]
                if legacy_runtime
                else []
            ),
        }
    ]
    if name == "document-processing-worker":
        containers.append({"name": "clamav", "image": IMAGE.format(name="clamav")})
    return {
        "spec": [
            {
                "template": [
                    {
                        "metadata": [
                            {
                                "annotations": (
                                    {"kubectl.kubernetes.io/restartedAt": "retained"}
                                    if legacy
                                    else {}
                                ),
                                "labels": {
                                    "fdai.io/source-commit": COMMIT,
                                    **(
                                        {"fdai.io/identity-bridge-sha": "retained"}
                                        if legacy
                                        else {}
                                    ),
                                },
                            }
                        ],
                        "spec": [
                            {
                                "container": containers,
                                "init_container": ([{"name": "identity-bridge"}] if legacy else []),
                                "volume": (
                                    [
                                        {"name": "identity-bridge"},
                                        {"name": "runtime-state"},
                                    ]
                                    if legacy_runtime
                                    else []
                                ),
                            }
                        ],
                    }
                ]
            }
        ]
    }


def _terraform_cron_job(*, legacy: bool) -> dict[str, object]:
    workload = _terraform_workload("analyzer", legacy=legacy)
    workload["spec"][0]["template"][0]["spec"][0]["volume"].append(
        {
            "name": "secrets",
            "csi": [{"driver": "secrets-store.csi.k8s.io", "fs_type": None if legacy else ""}],
        }
    )
    return {
        "spec": [
            {
                "job_template": [
                    {
                        "spec": [
                            {"template": workload["spec"][0]["template"]},
                        ]
                    }
                ]
            }
        ]
    }


def test_reconciliation_plan_accepts_only_legacy_normalization() -> None:
    variables = reconciled_variables(state=_state(), variables=_variables(), live=_live())
    changes: list[dict[str, object]] = [
        {
            "address": (
                "azurerm_federated_identity_credential.identity["
                '"workload-operator-service-command"]'
            ),
            "change": {"actions": ["no-op"], "before": {}, "after": {}},
        },
        *[
            {
                "address": address,
                "change": {"actions": ["create"], "before": {}, "after": {"id": "planned"}},
            }
            for address in (
                "kubernetes_cluster_role_v1.inventory_reader[0]",
                "kubernetes_cluster_role_binding_v1.inventory_reader[0]",
            )
        ],
        {
            "address": 'kubernetes_cron_job_v1.job["analyzer"]',
            "change": {
                "actions": ["update"],
                "before": _terraform_cron_job(legacy=True),
                "after": _terraform_cron_job(legacy=False),
            },
        },
        *[
            {
                "address": f'kubernetes_deployment_v1.workload["{name}"]',
                "change": {
                    "actions": ["update"],
                    "before": _terraform_workload(name, legacy=True),
                    "after": _terraform_workload(name, legacy=False),
                },
            }
            for name in sorted(SERVICES)
        ],
    ]
    plan = {"errored": False, "applyable": True, "resource_changes": changes}

    mutations = validate_reconciliation_plan(plan, variables=variables)

    assert "kubernetes_config_map_v1.identity_bridge" not in mutations
    assert len(mutations) == 8

    unsafe = copy.deepcopy(plan)
    unsafe["resource_changes"][0]["change"]["actions"] = ["delete"]
    with pytest.raises(ValueError, match="command identity"):
        validate_reconciliation_plan(unsafe, variables=variables)

    unsafe_bridge = copy.deepcopy(plan)
    unsafe_bridge["resource_changes"].append(
        {
            "address": "kubernetes_config_map_v1.identity_bridge",
            "change": {"actions": ["delete"], "before": {"id": "legacy"}, "after": {}},
        }
    )
    with pytest.raises(ValueError, match="out-of-scope mutation"):
        validate_reconciliation_plan(unsafe_bridge, variables=variables)

    unsafe_command = copy.deepcopy(plan)
    deployment = next(
        change
        for change in unsafe_command["resource_changes"]
        if change["address"] == 'kubernetes_deployment_v1.workload["operator-service"]'
    )
    deployment["change"]["after"]["spec"][0]["template"][0]["spec"][0]["container"][0][
        "command"
    ] = ["/bin/sh"]
    with pytest.raises(ValueError, match="workload contract"):
        validate_reconciliation_plan(unsafe_command, variables=variables)
