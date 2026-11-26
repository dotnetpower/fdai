"""Exact Kubernetes Resource resolver tests."""

from __future__ import annotations

from fdai.delivery.kubernetes_resource_resolver import (
    KubernetesResourceResolutionStatus,
    resolve_kubernetes_resource,
)
from fdai.shared.providers.inventory import ResourceRecord

CLUSTER = "scope-example/resource-group/example/providers/containerservice/aks"


def _pod(*, uid: str, resource_version: str) -> ResourceRecord:
    return ResourceRecord(
        resource_id=f"{CLUSTER}/kubernetes/kubernetes.pod/default/{uid}",
        type="kubernetes.pod",
        props={
            "api_version": "v1",
            "cluster_ref": CLUSTER,
            "kind": "Pod",
            "name": "api",
            "namespace": "default",
            "resource_version": resource_version,
            "uid": uid,
        },
    )


def test_resolves_only_one_exact_uid_and_resource_version() -> None:
    old = _pod(uid="uid-old", resource_version="10")
    current = _pod(uid="uid-current", resource_version="20")

    result = resolve_kubernetes_resource(
        (old, current),
        cluster_ref=CLUSTER,
        resource_type="kubernetes.pod",
        namespace="default",
        name="api",
        uid="uid-current",
        resource_version="20",
        complete=True,
    )

    assert result.status is KubernetesResourceResolutionStatus.RESOLVED
    assert result.resource == current


def test_name_reuse_is_ambiguous_without_uid() -> None:
    result = resolve_kubernetes_resource(
        (
            _pod(uid="uid-old", resource_version="10"),
            _pod(uid="uid-current", resource_version="20"),
        ),
        cluster_ref=CLUSTER,
        resource_type="kubernetes.pod",
        namespace="default",
        name="api",
        complete=True,
    )

    assert result.status is KubernetesResourceResolutionStatus.AMBIGUOUS
    assert result.candidate_count == 2
    assert result.complete is False


def test_incomplete_scope_never_proves_not_found() -> None:
    result = resolve_kubernetes_resource(
        (),
        cluster_ref=CLUSTER,
        resource_type="kubernetes.pod",
        namespace="default",
        name="api",
        complete=False,
    )

    assert result.status is KubernetesResourceResolutionStatus.UNAVAILABLE
    assert result.reason == "inventory_scope_incomplete"


def test_complete_scope_can_prove_not_found() -> None:
    result = resolve_kubernetes_resource(
        (),
        cluster_ref=CLUSTER,
        resource_type="kubernetes.pod",
        namespace="default",
        name="api",
        complete=True,
    )

    assert result.status is KubernetesResourceResolutionStatus.NOT_FOUND
    assert result.complete is True
