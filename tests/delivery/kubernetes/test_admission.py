"""Deterministic Kubernetes admission mutation tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from fdai.delivery.kubernetes.admission import mutating_webhook_resource_drift_findings


@pytest.mark.parametrize(
    ("namespace", "workload_name", "pod_name"),
    [
        ("shop", "api", "api-1"),
        ("team-b", "worker-v2", "worker-v2-7"),
        ("edge", "proxy", "proxy-a"),
    ],
)
def test_resource_drift_finding_is_metamorphic(
    namespace: str,
    workload_name: str,
    pod_name: str,
) -> None:
    resources = _resources(namespace, workload_name, pod_name)

    findings = mutating_webhook_resource_drift_findings(resources, evidence_complete=True)

    assert len(findings) == 1
    assert findings[0]["resource"]["name"] == "resource-defaulting"
    assert findings[0]["drifts"] == [
        {"workload": workload_name, "pod": pod_name, "containers": ["main"]}
    ]
    assert findings[0]["decision"] == "hold"


def test_resource_drift_abstains_on_truncated_or_ambiguous_evidence() -> None:
    resources = _resources("shop", "api", "api-1")

    assert not mutating_webhook_resource_drift_findings(resources, evidence_complete=False)
    assert not mutating_webhook_resource_drift_findings(
        [*resources, deepcopy(resources[0])], evidence_complete=True
    )


def test_resource_drift_abstains_for_scoped_mutator() -> None:
    resources = _resources("shop", "api", "api-1")
    webhook = resources[0]["webhooks"][0]  # type: ignore[index]
    webhook["namespace_selector"] = {"matchLabels": {"team": "a"}}

    assert not mutating_webhook_resource_drift_findings(resources, evidence_complete=True)


def test_resource_drift_compares_semantic_quantity_equivalence() -> None:
    resources = _resources("shop", "api", "api-1")
    pod_resources = resources[2]["pod_spec"]["containers"][0]["resources"]  # type: ignore[index]
    pod_resources["requests"]["memory"] = "128Mi"
    pod_resources["limits"]["memory"] = "256Mi"

    assert not mutating_webhook_resource_drift_findings(resources, evidence_complete=True)


def test_resource_drift_abstains_on_incomplete_selector_or_container_projection() -> None:
    resources = _resources("shop", "api", "api-1")
    incomplete_selector = deepcopy(resources)
    incomplete_selector[1]["selector"]["projection_complete"] = False  # type: ignore[index]
    incomplete_container = deepcopy(resources)
    incomplete_container[2]["pod_spec"]["projection_complete"] = False  # type: ignore[index]

    assert not mutating_webhook_resource_drift_findings(incomplete_selector, evidence_complete=True)
    assert not mutating_webhook_resource_drift_findings(
        incomplete_container, evidence_complete=True
    )


def _resources(namespace: str, workload_name: str, pod_name: str) -> list[dict[str, object]]:
    return [
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
                    "rules": [{"operations": ["CREATE"], "resources": ["pods"]}],
                }
            ],
        },
        {
            "kind": "Deployment",
            "name": workload_name,
            "namespace": namespace,
            "selector": {
                "projection_complete": True,
                "match_labels": {"app": workload_name},
            },
            "pod_template": {
                "projection_complete": True,
                "containers": [
                    {
                        "name": "main",
                        "resources": {
                            "requests": {"memory": "128Mi"},
                            "limits": {"memory": "256Mi"},
                        },
                    }
                ],
            },
        },
        {
            "kind": "Pod",
            "name": pod_name,
            "namespace": namespace,
            "labels": {
                "projection_complete": True,
                "values": {"app": workload_name},
            },
            "pod_spec": {
                "projection_complete": True,
                "containers": [
                    {
                        "name": "main",
                        "resources": {
                            "requests": {"memory": "16Mi"},
                            "limits": {"memory": "16Mi"},
                        },
                    }
                ],
            },
        },
    ]
