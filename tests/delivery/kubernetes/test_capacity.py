"""Deterministic Kubernetes capacity finding tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from fdai.delivery.kubernetes.capacity import (
    capacity_exceeds_ceiling_findings,
    project_pod_resource_requests,
)


@pytest.mark.parametrize(
    ("namespace", "pod_name", "requested_quantity", "capacities"),
    [
        ("team-a", "worker-a", "16Gi", ("8Gi", "12Gi")),
        ("team-b", "worker-b", "9500m", ("4", "8")),
        ("edge", "worker-c", "33Gi", ("16Gi", "32Gi")),
    ],
)
def test_capacity_finding_is_metamorphic(
    namespace: str,
    pod_name: str,
    requested_quantity: str,
    capacities: tuple[str, str],
) -> None:
    resource_name = "cpu" if requested_quantity.endswith("m") else "memory"
    resources, events, nodes = _evidence(
        namespace,
        pod_name,
        resource_name,
        requested_quantity,
        capacities,
    )

    findings = capacity_exceeds_ceiling_findings(
        resources,
        events=events,
        nodes=nodes,
        evidence_complete=True,
    )

    assert len(findings) == 1
    assert findings[0]["reason"] == "pod_resource_request_exceeds_node_capacity"
    assert findings[0]["resource"] == {
        "kind": "Pod",
        "name": pod_name,
        "namespace": namespace,
    }
    assert findings[0]["decision"] == "hold"


@pytest.mark.parametrize("evidence_complete", [False])
def test_capacity_finding_abstains_on_truncated_evidence(evidence_complete: bool) -> None:
    resources, events, nodes = _evidence("team-a", "worker", "memory", "16Gi", ("8Gi", "12Gi"))

    assert not capacity_exceeds_ceiling_findings(
        resources,
        events=events,
        nodes=nodes,
        evidence_complete=evidence_complete,
    )


def test_capacity_finding_abstains_on_stale_or_conflicting_identity() -> None:
    resources, events, nodes = _evidence("team-a", "worker", "memory", "16Gi", ("8Gi", "12Gi"))
    stale_events = deepcopy(events)
    stale_events[0]["regarding"]["uid"] = "stale"  # type: ignore[index]

    assert not capacity_exceeds_ceiling_findings(
        resources,
        events=stale_events,
        nodes=nodes,
        evidence_complete=True,
    )
    assert not capacity_exceeds_ceiling_findings(
        [*resources, deepcopy(resources[0])],
        events=events,
        nodes=nodes,
        evidence_complete=True,
    )


def test_capacity_finding_abstains_when_one_node_fits_or_is_incomplete() -> None:
    resources, events, nodes = _evidence("team-a", "worker", "memory", "16Gi", ("8Gi", "12Gi"))
    larger_nodes = deepcopy(nodes)
    larger_nodes[-1]["allocatable"]["memory"] = "32Gi"  # type: ignore[index]
    incomplete_nodes = deepcopy(nodes)
    incomplete_nodes[-1]["allocatable_projection_complete"] = False

    assert not capacity_exceeds_ceiling_findings(
        resources,
        events=events,
        nodes=larger_nodes,
        evidence_complete=True,
    )
    assert not capacity_exceeds_ceiling_findings(
        resources,
        events=events,
        nodes=incomplete_nodes,
        evidence_complete=True,
    )


def test_capacity_finding_groups_cpu_and_memory_without_case_collision() -> None:
    requests = project_pod_resource_requests(
        {
            "containers": [{"resources": {"requests": {"cpu": "9", "memory": "17Gi"}}}],
            "initContainers": [],
        }
    )
    assert requests is not None
    resources, events, nodes = _evidence("team-c", "worker", "memory", "17Gi", ("8Gi", "16Gi"))
    resources[0]["resource_requests"] = requests

    findings = capacity_exceeds_ceiling_findings(
        resources,
        events=events,
        nodes=nodes,
        evidence_complete=True,
    )

    assert len(findings) == 1
    assert [item["resource"] for item in findings[0]["exceeded_resources"]] == [
        "cpu",
        "memory",
    ]


def test_pod_request_projection_uses_sum_regular_max_init_semantics() -> None:
    projection = project_pod_resource_requests(
        {
            "containers": [
                {"resources": {"requests": {"cpu": "250m", "memory": "1Gi"}}},
                {"resources": {"requests": {"cpu": "750m", "memory": "1Gi"}}},
            ],
            "initContainers": [{"resources": {"requests": {"cpu": "2", "memory": "3Gi"}}}],
        }
    )

    assert projection == {
        "projection_complete": True,
        "source_paths": {
            "cpu": [
                "/spec/containers/0/resources/requests/cpu",
                "/spec/containers/1/resources/requests/cpu",
                "/spec/initContainers/0/resources/requests/cpu",
            ],
            "memory": [
                "/spec/containers/0/resources/requests/memory",
                "/spec/containers/1/resources/requests/memory",
                "/spec/initContainers/0/resources/requests/memory",
            ],
        },
        "cpu_base_units": "2",
        "memory_base_units": "3221225472",
    }


def _evidence(
    namespace: str,
    pod_name: str,
    resource_name: str,
    request: str,
    capacities: tuple[str, str],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    uid = f"{pod_name}-uid"
    requests = project_pod_resource_requests(
        {
            "containers": [{"resources": {"requests": {resource_name: request}}}],
            "initContainers": [],
        }
    )
    assert requests is not None
    resources: list[dict[str, object]] = [
        {
            "kind": "Pod",
            "name": pod_name,
            "namespace": namespace,
            "uid": uid,
            "resource_requests": requests,
        }
    ]
    events: list[dict[str, object]] = [
        {
            "reason": "FailedScheduling",
            "last_seen": "2026-08-04T00:00:00Z",
            "regarding": {
                "kind": "Pod",
                "name": pod_name,
                "namespace": namespace,
                "uid": uid,
            },
        }
    ]
    nodes: list[dict[str, object]] = [
        {
            "name": f"node-{index}",
            "ready": True,
            "unschedulable": False,
            "allocatable": {resource_name: capacity},
            "allocatable_projection_complete": True,
        }
        for index, capacity in enumerate(capacities)
    ]
    for node in nodes:
        allocatable = node["allocatable"]
        assert isinstance(allocatable, dict)
        allocatable.setdefault("cpu", "8")
        allocatable.setdefault("memory", "16Gi")
    return resources, events, nodes
