from __future__ import annotations

import hashlib
import itertools
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest

from fdai_lifecycle_agent.workload import (
    FIELD_MANAGER,
    MANAGED_BY_LABEL,
    Cluster,
    Manifest,
    Workload,
    WorkloadError,
    check_scope,
    is_repository,
    render,
    rollout_complete,
)

if TYPE_CHECKING:
    from conftest import FakeCluster

NAMESPACE = "fdai-demo"


def image(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


REFERENCE = f"registry.example.test/fdai/core@{image('v1')}"


def _render(reference: str = REFERENCE) -> tuple[Manifest, ...]:
    return render(NAMESPACE, {("core", "core-control-plane"): reference})


def _workload(cluster: Cluster, **overrides: Any) -> Workload:
    ticks = itertools.count()
    fields: dict[str, Any] = {
        "cluster": cluster,
        "namespace": NAMESPACE,
        "health_timeout_seconds": 5.0,
        "monotonic": lambda: float(next(ticks)),
        "sleep": lambda _seconds: None,
    }
    return Workload(**(fields | overrides))


def test_render_pins_the_image_digest_and_labels_both_objects() -> None:
    deployment, service = _render()

    assert (deployment["kind"], service["kind"]) == ("Deployment", "Service")
    for manifest in (deployment, service):
        assert manifest["metadata"]["namespace"] == NAMESPACE
        assert manifest["metadata"]["name"] == "core-control-plane"
        assert manifest["metadata"]["labels"] == {
            MANAGED_BY_LABEL: FIELD_MANAGER,
            "fdai.io/entity": "core",
            "fdai.io/component": "core-control-plane",
        }
    [container] = deployment["spec"]["template"]["spec"]["containers"]
    assert container["image"] == REFERENCE
    assert service["spec"]["selector"] == deployment["spec"]["selector"]["matchLabels"]


@pytest.mark.parametrize(
    "reference",
    [
        "registry.example.test/fdai/core:1.0",
        "registry.example.test/fdai/core:1.0@" + image("v1"),
        "registry.example.test/fdai/core@sha256:short",
        "Registry.example.test/fdai/core@" + image("v1"),
    ],
)
def test_render_refuses_an_image_that_is_not_repository_at_digest(reference: str) -> None:
    with pytest.raises(WorkloadError, match="workload_render_failed"):
        _render(reference)


def test_render_refuses_one_component_in_two_entities() -> None:
    with pytest.raises(WorkloadError, match="workload_render_failed"):
        render(NAMESPACE, {("core", "shared"): REFERENCE, ("operator-api", "shared"): REFERENCE})


@pytest.mark.parametrize(
    ("repository", "valid"),
    [
        ("nginxinc/nginx-unprivileged", True),
        ("localhost:5000/fdai/core", True),
        ("nginxinc/nginx-unprivileged:1.27", False),
        ("nginxinc/nginx-unprivileged@" + image("v1"), False),
        ("", False),
    ],
)
def test_repository_paths_carry_no_tag_or_digest(repository: str, valid: bool) -> None:
    assert is_repository(repository) is valid


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m["metadata"].update(namespace="kube-system"),
        lambda m: m.update(kind="Secret"),
        lambda m: m.update(apiVersion="apps/v1beta1"),
        lambda m: m["metadata"]["labels"].pop(MANAGED_BY_LABEL),
    ],
    ids=["namespace", "kind", "api-version", "managed-by"],
)
def test_scope_guard_refuses_anything_outside_the_namespace_and_two_kinds(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    deployment, _ = render(NAMESPACE, {("core", "core-control-plane"): REFERENCE})
    manifest: dict[str, Any] = {
        **deployment,
        "metadata": {**deployment["metadata"], "labels": dict(deployment["metadata"]["labels"])},
    }
    mutate(manifest)

    with pytest.raises(WorkloadError, match="workload_outside_scope"):
        check_scope([manifest], NAMESPACE)


@pytest.mark.parametrize(
    ("status", "complete"),
    [
        (
            {
                "observedGeneration": 2,
                "replicas": 1,
                "updatedReplicas": 1,
                "readyReplicas": 1,
                "availableReplicas": 1,
            },
            True,
        ),
        (
            {
                "observedGeneration": 1,
                "replicas": 1,
                "updatedReplicas": 1,
                "readyReplicas": 1,
                "availableReplicas": 1,
            },
            False,
        ),
        (
            {
                "observedGeneration": 2,
                "replicas": 2,
                "updatedReplicas": 1,
                "readyReplicas": 1,
                "availableReplicas": 1,
            },
            False,
        ),
        (
            {
                "observedGeneration": 2,
                "replicas": 1,
                "updatedReplicas": 1,
                "readyReplicas": 0,
                "availableReplicas": 1,
            },
            False,
        ),
        ({}, False),
    ],
    ids=["complete", "stale-generation", "old-replica-left", "not-ready", "no-status"],
)
def test_rollout_is_complete_only_when_every_replica_is_current(
    status: dict[str, int], complete: bool
) -> None:
    deployment = {"metadata": {"generation": 2}, "spec": {"replicas": 1}, "status": status}

    assert rollout_complete(deployment) is complete


def test_preflight_dry_runs_every_object_without_writing(cluster: FakeCluster) -> None:
    _workload(cluster).preflight(_render(), ())

    assert cluster.writes() == []
    assert [call[0] for call in cluster.calls] == ["dry-run", "dry-run"]


def test_preflight_refuses_a_live_object_without_a_recorded_healthy_version(
    cluster: FakeCluster,
) -> None:
    for manifest in _render():
        cluster.apply(manifest)

    with pytest.raises(WorkloadError, match="rollback_target_unknown"):
        _workload(cluster).preflight(_render(), ())


def test_apply_reports_a_rollout_that_never_completes(cluster: FakeCluster) -> None:
    reference = f"registry.example.test/fdai/core@{image('broken')}"
    cluster.broken_images.add(reference)

    assert _workload(cluster).apply(_render(reference)) is False


def test_health_wait_treats_a_failed_read_as_not_yet_healthy(cluster: FakeCluster) -> None:
    reads = iter([WorkloadError("kubernetes_unavailable", retryable=True)])

    class FlakyReads:
        def apply(self, manifest: Manifest, *, dry_run: bool = False) -> None:
            cluster.apply(manifest, dry_run=dry_run)

        def get(self, kind: str, name: str) -> Manifest | None:
            if (error := next(reads, None)) is not None:
                raise error
            return cluster.get(kind, name)

        def delete(self, kind: str, name: str) -> None:
            cluster.delete(kind, name)

    assert _workload(FlakyReads()).apply(_render()) is True


def test_roll_back_restores_recorded_objects_and_deletes_created_ones(
    cluster: FakeCluster,
) -> None:
    workload = _workload(cluster)
    previous = _render()
    workload.apply(previous)
    created = render(
        NAMESPACE,
        {
            ("core", "core-control-plane"): f"registry.example.test/fdai/core@{image('v2')}",
            ("operator-api", "operator-service"): f"registry.example.test/fdai/op@{image('v2')}",
        },
    )
    workload.apply(created)

    assert workload.roll_back(created, previous) is True
    assert cluster.image() == REFERENCE
    assert ("Deployment", "operator-service") not in cluster.objects
    assert ("Service", "operator-service") not in cluster.objects
