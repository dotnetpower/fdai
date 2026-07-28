from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdai.delivery.read_api.dev.kubernetes_workloads import (
    KubectlWorkloadConfig,
    KubectlWorkloadProvider,
    kubectl_workload_provider_from_env,
)


async def test_kubectl_provider_projects_deployments_and_pods(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("test", encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    async def run(command: tuple[str, ...]) -> str:
        commands.append(command)
        return json.dumps(
            {
                "items": [
                    {
                        "kind": "Deployment",
                        "metadata": {"namespace": "benchmark", "name": "runner"},
                        "spec": {"replicas": 2},
                        "status": {"readyReplicas": 2, "availableReplicas": 2},
                    },
                    {
                        "kind": "Pod",
                        "metadata": {"namespace": "benchmark", "name": "runner-abc"},
                        "status": {
                            "phase": "Running",
                            "containerStatuses": [{"ready": True}, {"ready": False}],
                        },
                    },
                ]
            }
        )

    provider = KubectlWorkloadProvider(
        config=KubectlWorkloadConfig(
            kubeconfig=kubeconfig,
            context="fdai-dev",
            cluster_name="aks-app",
        ),
        run=run,
    )

    result = await provider()

    assert result["status"] == "matched"
    assert result["cluster_name"] == "aks-app"
    assert result["deployments"] == [
        {
            "namespace": "benchmark",
            "name": "runner",
            "desired": 2,
            "ready": 2,
            "available": 2,
        }
    ]
    assert result["pods"] == [
        {
            "namespace": "benchmark",
            "name": "runner-abc",
            "phase": "Running",
            "ready": 1,
            "containers": 2,
        }
    ]
    assert commands == [
        (
            "kubectl",
            "--kubeconfig",
            str(kubeconfig),
            "--context",
            "fdai-dev",
            "get",
            "deployments,pods",
            "--all-namespaces",
            "--output",
            "json",
        )
    ]


def test_kubectl_provider_rejects_partial_environment(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be configured together"):
        kubectl_workload_provider_from_env(
            {
                "FDAI_LOCAL_KUBECONFIG": str(tmp_path / "config"),
                "FDAI_LOCAL_KUBERNETES_CONTEXT": "fdai-dev",
            }
        )
