"""Deterministic Kubernetes endpoint dependency tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from fdai.delivery.kubernetes.dependency import missing_service_dependency_findings


@pytest.mark.parametrize(
    ("namespace", "backend_name", "frontend_name", "port"),
    [
        ("shop", "catalog", "checkout", 8080),
        ("team-b", "inventory-v2", "gateway-v3", 9443),
        ("edge", "pricing", "portal", 31017),
    ],
)
def test_missing_dependency_finding_is_metamorphic(
    namespace: str,
    backend_name: str,
    frontend_name: str,
    port: int,
) -> None:
    resources = _resources(namespace, backend_name, frontend_name, port)

    findings = missing_service_dependency_findings(resources, evidence_complete=True)

    assert len(findings) == 1
    assert findings[0]["resource"] == {
        "kind": "Service",
        "name": backend_name,
        "namespace": namespace,
    }
    assert findings[0]["backend"]["declared_port"] == port
    assert findings[0]["decision"] == "hold"


def test_missing_dependency_abstains_on_truncated_evidence() -> None:
    resources = _resources("shop", "catalog", "checkout", 8080)

    assert not missing_service_dependency_findings(resources, evidence_complete=False)


def test_missing_dependency_abstains_on_present_or_ambiguous_service() -> None:
    resources = _resources("shop", "catalog", "checkout", 8080)
    present = {
        "kind": "Service",
        "name": "catalog",
        "namespace": "shop",
    }

    assert not missing_service_dependency_findings([*resources, present], evidence_complete=True)
    assert not missing_service_dependency_findings(
        [*resources, deepcopy(resources[0])], evidence_complete=True
    )


def test_missing_dependency_abstains_on_incomplete_or_unhealthy_backend() -> None:
    resources = _resources("shop", "catalog", "checkout", 8080)
    incomplete = deepcopy(resources)
    incomplete[0]["pod_template"]["projection_complete"] = False  # type: ignore[index]
    unhealthy = deepcopy(resources)
    unhealthy[0]["ready"] = 0

    assert not missing_service_dependency_findings(incomplete, evidence_complete=True)
    assert not missing_service_dependency_findings(unhealthy, evidence_complete=True)


def test_missing_dependency_abstains_on_external_or_mismatched_endpoint() -> None:
    resources = _resources("shop", "catalog", "checkout", 8080)
    external = deepcopy(resources)
    external[1]["pod_template"]["containers"][0]["env"][0][  # type: ignore[index]
        "endpoint_host"
    ] = "catalog.example.com"
    mismatched = deepcopy(resources)
    mismatched[1]["pod_template"]["containers"][0]["env"][0][  # type: ignore[index]
        "endpoint_port"
    ] = "9090"

    assert not missing_service_dependency_findings(external, evidence_complete=True)
    assert not missing_service_dependency_findings(mismatched, evidence_complete=True)


def _resources(
    namespace: str,
    backend_name: str,
    frontend_name: str,
    port: int,
) -> list[dict[str, object]]:
    return [
        {
            "kind": "Deployment",
            "name": backend_name,
            "namespace": namespace,
            "desired": 3,
            "ready": 2,
            "pod_template": {
                "projection_complete": True,
                "containers": [
                    {
                        "name": backend_name,
                        "port_projection_complete": True,
                        "ports": [{"port": port}],
                        "env_projection_complete": True,
                        "env": [],
                    }
                ],
            },
        },
        {
            "kind": "Deployment",
            "name": frontend_name,
            "namespace": namespace,
            "desired": 2,
            "ready": 2,
            "pod_template": {
                "projection_complete": True,
                "containers": [
                    {
                        "name": frontend_name,
                        "port_projection_complete": True,
                        "ports": [],
                        "env_projection_complete": True,
                        "env": [
                            {
                                "name": "BACKEND_ADDR",
                                "endpoint_host": backend_name,
                                "endpoint_port": str(port),
                            }
                        ],
                    }
                ],
            },
        },
    ]
