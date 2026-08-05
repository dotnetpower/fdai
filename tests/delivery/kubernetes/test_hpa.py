"""Ineffective HPA metric candidate tests."""

from __future__ import annotations

from copy import deepcopy

from fdai.delivery.kubernetes.hpa import hpa_missing_cpu_request_findings


def test_hpa_missing_cpu_requires_inactive_utilization_metric_and_exact_target() -> None:
    finding = hpa_missing_cpu_request_findings(_resources(), evidence_complete=True)[0]
    assert finding["reason"] == "hpa_cpu_utilization_missing_request_candidate"
    assert finding["missing_requests"][0]["container"] == "api"
    assert finding["decision"] == "hold"


def test_hpa_missing_cpu_abstains_on_truncated_or_valid_request() -> None:
    valid = deepcopy(_resources())
    valid[1]["pod_template"]["containers"][0]["resources"] = {"requests": {"cpu": "100m"}}  # type: ignore[index]
    assert not hpa_missing_cpu_request_findings(_resources(), evidence_complete=False)
    assert not hpa_missing_cpu_request_findings(valid, evidence_complete=True)


def test_hpa_missing_cpu_abstains_on_active_or_non_cpu_metric() -> None:
    active = deepcopy(_resources())
    active[0]["conditions"][0]["status"] = "True"  # type: ignore[index]
    memory = deepcopy(_resources())
    memory[0]["metrics"][0]["resource"] = "memory"  # type: ignore[index]
    assert not hpa_missing_cpu_request_findings(active, evidence_complete=True)
    assert not hpa_missing_cpu_request_findings(memory, evidence_complete=True)


def test_hpa_missing_cpu_abstains_on_ambiguous_or_incomplete_target() -> None:
    ambiguous = deepcopy(_resources())
    ambiguous.append(deepcopy(ambiguous[1]))
    incomplete = deepcopy(_resources())
    incomplete[1]["pod_template"]["containers"][0]["resource_projection_complete"] = False  # type: ignore[index]
    assert not hpa_missing_cpu_request_findings(ambiguous, evidence_complete=True)
    assert not hpa_missing_cpu_request_findings(incomplete, evidence_complete=True)


def test_hpa_missing_cpu_is_metamorphic_to_order_and_namespace_rename() -> None:
    expected = hpa_missing_cpu_request_findings(_resources(), evidence_complete=True)
    renamed = deepcopy(_resources())
    for resource in renamed:
        resource["namespace"] = "renamed-app"
    assert (
        hpa_missing_cpu_request_findings(list(reversed(_resources())), evidence_complete=True)
        == expected
    )
    assert (
        hpa_missing_cpu_request_findings(renamed, evidence_complete=True)[0]["resource"][
            "namespace"
        ]
        == "renamed-app"
    )


def _resources() -> list[dict[str, object]]:
    return [
        {
            "kind": "HorizontalPodAutoscaler",
            "namespace": "example-app",
            "name": "api",
            "projection_complete": True,
            "metrics_projection_complete": True,
            "metrics": [{"type": "Resource", "resource": "cpu", "target_type": "Utilization"}],
            "conditions": [
                {"type": "ScalingActive", "status": "False", "reason": "FailedGetResourceMetric"}
            ],
            "scale_target": {"kind": "Deployment", "name": "api"},
        },
        {
            "kind": "Deployment",
            "namespace": "example-app",
            "name": "api",
            "pod_template": {
                "projection_complete": True,
                "containers": [
                    {"name": "api", "resource_projection_complete": True, "resources": {}}
                ],
            },
        },
    ]
