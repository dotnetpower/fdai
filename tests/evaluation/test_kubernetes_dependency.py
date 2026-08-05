"""Evaluation adapter tests for shared Kubernetes dependency semantics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai_evaluation_sdk import EvaluationTask

from fdai.delivery.evaluation.kubernetes_dependency import KubectlDependencyEvidenceProvider


class _Client:
    def __init__(self, *, truncated: bool = False) -> None:
        self.truncated = truncated

    async def inventory(self, task: EvaluationTask) -> Mapping[str, Any]:
        del task
        return {
            "cluster": "example-cluster",
            "namespace": "example-app",
            "resources": _resources(),
            "truncated": self.truncated,
        }


async def test_dependency_provider_emits_hold_only_finding() -> None:
    evidence = await KubectlDependencyEvidenceProvider(_Client()).collect(None)  # type: ignore[arg-type]

    assert evidence["evidence_complete"] is True
    assert evidence["findings"][0]["reason"] == "workload_endpoint_targets_missing_service"
    assert evidence["findings"][0]["decision"] == "hold"


async def test_dependency_provider_exposes_incomplete_evidence_without_finding() -> None:
    evidence = await KubectlDependencyEvidenceProvider(_Client(truncated=True)).collect(None)  # type: ignore[arg-type]

    assert evidence == {
        "cluster": "example-cluster",
        "namespace": "example-app",
        "evidence_complete": False,
        "findings": [],
    }


def _resources() -> list[dict[str, object]]:
    return [
        {
            "kind": "Deployment",
            "name": "catalog",
            "namespace": "example-app",
            "desired": 1,
            "ready": 1,
            "pod_template": {
                "projection_complete": True,
                "containers": [
                    {
                        "name": "catalog",
                        "port_projection_complete": True,
                        "ports": [{"port": 8080}],
                        "env_projection_complete": True,
                        "env": [],
                    }
                ],
            },
        },
        {
            "kind": "Deployment",
            "name": "frontend",
            "namespace": "example-app",
            "desired": 1,
            "ready": 1,
            "pod_template": {
                "projection_complete": True,
                "containers": [
                    {
                        "name": "frontend",
                        "port_projection_complete": True,
                        "ports": [],
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
            },
        },
    ]
