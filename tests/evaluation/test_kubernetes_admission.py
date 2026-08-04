"""Evaluation adapter tests for shared Kubernetes admission drift semantics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fdai_evaluation_sdk import EvaluationTask

from fdai.delivery.evaluation.kubernetes_admission import KubectlAdmissionEvidenceProvider


class _Client:
    def __init__(
        self,
        *,
        inventory_truncated: bool = False,
        webhook_truncated: bool = False,
    ) -> None:
        self.inventory_truncated = inventory_truncated
        self.webhook_truncated = webhook_truncated

    async def inventory(self, task: EvaluationTask) -> Mapping[str, Any]:
        del task
        return {
            "cluster": "example-cluster",
            "namespace": "example-app",
            "resources": _resources()[:2],
            "truncated": self.inventory_truncated,
        }

    async def events(self, task: EvaluationTask) -> Mapping[str, Any]:
        del task
        return {"events": [], "truncated": False}

    async def admission_configurations(self, task: EvaluationTask) -> Mapping[str, Any]:
        del task
        return {
            "cluster": "example-cluster",
            "resources": _resources()[2:],
            "truncated": self.webhook_truncated,
        }


async def test_admission_provider_emits_candidate_only_hold_finding() -> None:
    evidence = await KubectlAdmissionEvidenceProvider(_Client()).collect(None)  # type: ignore[arg-type]

    assert evidence["evidence_complete"] is True
    assert evidence["findings"][0]["causality"] == "candidate_only"
    assert evidence["findings"][0]["decision"] == "hold"


async def test_admission_provider_correlates_structured_webhook_failure_candidate() -> None:
    class _EventClient(_Client):
        async def events(self, task: EvaluationTask) -> Mapping[str, Any]:
            del task
            return {
                "events": [
                    {
                        "namespace": "example-app",
                        "reason": "FailedCreate",
                        "code": "admission_webhook_timeout",
                        "webhook_name": "mutate.example.com",
                        "regarding": {"kind": "ReplicaSet", "name": "api-1"},
                    }
                ],
                "truncated": False,
            }

    evidence = await KubectlAdmissionEvidenceProvider(_EventClient()).collect(None)  # type: ignore[arg-type]

    finding = next(
        item
        for item in evidence["findings"]
        if item["reason"] == "admission_webhook_failure_configuration_candidate"
    )
    assert finding["failure_class"] == "timeout"
    assert finding["resource"]["name"] == "resource-defaulting"
    assert finding["causality"] == "candidate_only"


async def test_admission_provider_abstains_when_event_query_is_truncated() -> None:
    class _TruncatedEventClient(_Client):
        async def events(self, task: EvaluationTask) -> Mapping[str, Any]:
            del task
            return {"events": [], "truncated": True}

    evidence = await KubectlAdmissionEvidenceProvider(_TruncatedEventClient()).collect(None)  # type: ignore[arg-type]

    assert evidence["evidence_complete"] is False
    assert evidence["findings"] == []


async def test_admission_provider_prioritizes_no_magic_weight_but_exposes_direct_evidence() -> None:
    client = _Client()
    inventory = await client.inventory(None)  # type: ignore[arg-type]
    resources = list(inventory["resources"])
    resources[0] = {
        "kind": "ReplicaSet",
        "name": "api-1",
        "namespace": "example-app",
        "admission_condition_projection_complete": True,
        "admission_conditions": [
            {
                "type": "ReplicaFailure",
                "status": "True",
                "reason": "FailedCreate",
                "code": "admission_webhook_timeout",
                "webhook_name": "policy.example.io",
                "source_index": 0,
            }
        ],
    }

    class _ConditionClient(_Client):
        async def inventory(self, task: EvaluationTask) -> Mapping[str, Any]:
            del task
            return {**inventory, "resources": resources}

    evidence = await KubectlAdmissionEvidenceProvider(_ConditionClient()).collect(None)  # type: ignore[arg-type]

    finding = evidence["findings"][0]
    assert finding["evidence_strength"] == "direct_resource_condition"
    assert finding["causality"] == "candidate_only"
    assert "priority" not in finding


@pytest.mark.parametrize(
    ("inventory_truncated", "webhook_truncated"),
    [(True, False), (False, True), (True, True)],
)
async def test_admission_provider_abstains_if_either_query_is_truncated(
    inventory_truncated: bool,
    webhook_truncated: bool,
) -> None:
    evidence = await KubectlAdmissionEvidenceProvider(
        _Client(
            inventory_truncated=inventory_truncated,
            webhook_truncated=webhook_truncated,
        )
    ).collect(None)  # type: ignore[arg-type]

    assert evidence["evidence_complete"] is False
    assert evidence["findings"] == []


def _resources() -> list[dict[str, object]]:
    return [
        {
            "kind": "Deployment",
            "name": "api",
            "namespace": "example-app",
            "selector": {
                "projection_complete": True,
                "match_labels": {"app": "api"},
            },
            "pod_template": {
                "projection_complete": True,
                "containers": [
                    {
                        "name": "main",
                        "resource_projection_complete": True,
                        "resources": {"requests": {"memory": "128Mi"}},
                    }
                ],
            },
        },
        {
            "kind": "Pod",
            "name": "api-1",
            "namespace": "example-app",
            "labels": {"projection_complete": True, "values": {"app": "api"}},
            "pod_spec": {
                "projection_complete": True,
                "containers": [
                    {
                        "name": "main",
                        "resource_projection_complete": True,
                        "resources": {"requests": {"memory": "16Mi"}},
                    }
                ],
            },
        },
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
        },
    ]
