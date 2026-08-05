"""Evaluation adapter tests for shared Kubernetes capacity semantics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai_evaluation_sdk import EvaluationTask

from fdai.delivery.evaluation.kubernetes_capacity import KubectlCapacityEvidenceProvider


class _Client:
    def __init__(self, *, truncated: bool = False) -> None:
        self.truncated = truncated

    async def inventory(self, task: EvaluationTask) -> Mapping[str, Any]:
        del task
        return {
            "cluster": "example-cluster",
            "namespace": "example-app",
            "resources": [
                {
                    "kind": "Pod",
                    "name": "worker",
                    "namespace": "example-app",
                    "uid": "pod-uid",
                    "resource_requests": {
                        "projection_complete": True,
                        "source_paths": {
                            "memory": ["/spec/containers/0/resources/requests/memory"]
                        },
                        "memory_base_units": "17179869184",
                    },
                }
            ],
            "truncated": self.truncated,
        }

    async def events(self, task: EvaluationTask) -> Mapping[str, Any]:
        del task
        return {
            "events": [
                {
                    "reason": "FailedScheduling",
                    "last_seen": "2026-08-04T00:00:00Z",
                    "regarding": {
                        "kind": "Pod",
                        "name": "worker",
                        "namespace": "example-app",
                        "uid": "pod-uid",
                    },
                }
            ],
            "truncated": False,
        }

    async def nodes(self, task: EvaluationTask) -> Mapping[str, Any]:
        del task
        return {
            "nodes": [
                {
                    "name": "node-a",
                    "ready": True,
                    "unschedulable": False,
                    "allocatable": {"cpu": "4", "memory": "8Gi"},
                    "allocatable_projection_complete": True,
                },
                {
                    "name": "node-b",
                    "ready": True,
                    "unschedulable": False,
                    "allocatable": {"cpu": "8", "memory": "12Gi"},
                    "allocatable_projection_complete": True,
                },
            ],
            "truncated": False,
        }


async def test_capacity_provider_emits_one_hold_only_finding() -> None:
    evidence = await KubectlCapacityEvidenceProvider(_Client()).collect(None)  # type: ignore[arg-type]

    assert evidence["evidence_complete"] is True
    assert evidence["findings"] == [
        {
            "reason": "pod_resource_request_exceeds_node_capacity",
            "resource": {"kind": "Pod", "name": "worker", "namespace": "example-app"},
            "source_paths": ["/spec/containers/0/resources/requests/memory"],
            "exceeded_resources": [
                {
                    "resource": "memory",
                    "requested_base_units": "17179869184",
                    "largest_node_base_units": "12884901888",
                }
            ],
            "eligible_node_count": 2,
            "event_reason": "FailedScheduling",
            "decision": "hold",
        }
    ]


async def test_capacity_provider_exposes_incomplete_evidence_without_finding() -> None:
    evidence = await KubectlCapacityEvidenceProvider(_Client(truncated=True)).collect(None)  # type: ignore[arg-type]

    assert evidence == {
        "cluster": "example-cluster",
        "namespace": "example-app",
        "evidence_complete": False,
        "findings": [],
    }
