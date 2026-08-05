"""Tests for Kubernetes evidence to ontology topology projection."""

from __future__ import annotations

import pytest

from fdai.delivery.kubernetes.ontology_projection import build_kubernetes_ontology_projection

_CLUSTER_REF = "kubernetes.cluster:test"
_NAMESPACE_REF = f"{_CLUSTER_REF}/namespace/example"


def _resource_ref(uid: str) -> str:
    return f"{_CLUSTER_REF}/resource/{uid}"


def _resources() -> list[dict[str, object]]:
    return [
        {
            "kind": "Deployment",
            "namespace": "example",
            "name": "frontend",
            "uid": "deployment-uid",
            "owner_reference_projection_complete": True,
            "owner_references": [],
            "pod_template": {
                "projection_complete": True,
                "containers": [
                    {
                        "env_projection_complete": True,
                        "env": [{"endpoint_host": "backend", "endpoint_port": "8080"}],
                    }
                ],
            },
        },
        {
            "kind": "Service",
            "namespace": "example",
            "name": "backend",
            "uid": "service-uid",
            "selector": {"app": "backend"},
        },
        {
            "kind": "Endpoints",
            "namespace": "example",
            "name": "backend",
            "uid": "endpoints-uid",
        },
        {
            "kind": "Pod",
            "namespace": "example",
            "name": "backend-a",
            "uid": "pod-uid",
            "labels": {"app": "backend"},
            "owner_reference_projection_complete": True,
            "owner_references": [
                {
                    "kind": "Deployment",
                    "name": "frontend",
                    "uid": "deployment-uid",
                }
            ],
        },
    ]


def test_projects_exact_kubernetes_relationships() -> None:
    projection = build_kubernetes_ontology_projection(
        _resources(),
        evidence_complete=True,
        expected_namespace="example",
        cluster_ref=_CLUSTER_REF,
    )

    assert len(projection.objects) == 4
    assert {(item.link_type, item.from_id, item.to_id) for item in projection.links} == {
        ("contains", _resource_ref("deployment-uid"), _NAMESPACE_REF),
        ("contains", _resource_ref("endpoints-uid"), _NAMESPACE_REF),
        ("contains", _resource_ref("pod-uid"), _NAMESPACE_REF),
        ("contains", _resource_ref("service-uid"), _NAMESPACE_REF),
        ("depends_on", _resource_ref("deployment-uid"), _resource_ref("service-uid")),
        (
            "kubernetes_exposes_endpoints",
            _resource_ref("service-uid"),
            _resource_ref("endpoints-uid"),
        ),
        (
            "kubernetes_owned_by",
            _resource_ref("pod-uid"),
            _resource_ref("deployment-uid"),
        ),
        ("kubernetes_selects", _resource_ref("service-uid"), _resource_ref("pod-uid")),
    }


def test_incomplete_evidence_projects_objects_without_relationship_claims() -> None:
    projection = build_kubernetes_ontology_projection(
        _resources(),
        evidence_complete=False,
        expected_namespace="example",
        cluster_ref=_CLUSTER_REF,
    )

    assert len(projection.objects) == 4
    assert projection.links == ()


def test_skips_resources_without_exact_uid() -> None:
    projection = build_kubernetes_ontology_projection(
        [*_resources(), {"kind": "Service", "namespace": "example", "name": "unknown"}],
        evidence_complete=True,
        expected_namespace="example",
        cluster_ref=_CLUSTER_REF,
    )

    assert len(projection.objects) == 4


def test_rejects_duplicate_uid() -> None:
    duplicate = {**_resources()[0], "name": "other"}

    with pytest.raises(ValueError, match="duplicate Kubernetes resource UID"):
        build_kubernetes_ontology_projection(
            [*_resources(), duplicate],
            evidence_complete=True,
            expected_namespace="example",
            cluster_ref=_CLUSTER_REF,
        )


def test_rejects_cross_namespace_resource() -> None:
    resource = {**_resources()[0], "namespace": "other"}

    with pytest.raises(ValueError, match="crossed the target namespace"):
        build_kubernetes_ontology_projection(
            [resource],
            evidence_complete=True,
            expected_namespace="example",
            cluster_ref=_CLUSTER_REF,
        )


def test_rejects_resource_count_above_store_refresh_ceiling() -> None:
    with pytest.raises(ValueError, match="resource count exceeds limit"):
        build_kubernetes_ontology_projection(
            [{}] * 1001,
            evidence_complete=False,
            expected_namespace="example",
            cluster_ref=_CLUSTER_REF,
        )
