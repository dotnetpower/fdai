"""HorizontalPodAutoscaler in the runtime bundle: pairing, bounds, rendering, and rollout."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from fdai_lifecycle_agent.workload import Workload, rollout_complete

_SPEC = importlib.util.spec_from_file_location(
    "runtime_bundle_fixtures", Path(__file__).with_name("test_runtime_bundle.py")
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURES = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURES)
bundle_document = _FIXTURES.bundle_document
parse = _FIXTURES.parse

METRIC = {
    "type": "Resource",
    "resource": {"name": "cpu", "target": {"type": "Utilization", "averageUtilization": 70}},
}


def autoscaler(**spec: Any) -> dict[str, Any]:
    return {
        "entity_id": "application",
        "kind": "HorizontalPodAutoscaler",
        "name": "frontend",
        "spec": {"minReplicas": 2, "maxReplicas": 4, "metrics": [deepcopy(METRIC)]} | spec,
    }


def autoscaled_document() -> dict[str, Any]:
    document = bundle_document()
    deployment = next(item for item in document["objects"] if item["kind"] == "Deployment")
    del deployment["spec"]["replicas"]
    document["objects"].append(autoscaler())
    return document


def test_autoscaled_bundle_renders_a_target_bound_autoscaler_and_no_pinned_replicas() -> None:
    bundle = parse(autoscaled_document())

    manifests = bundle.render(
        "fdai-demo",
        frozenset({"application"}),
        {("application", "frontend"): "example.azurecr.io/frontend@sha256:" + "a" * 64},
    )

    by_kind = {item["kind"]: item for item in manifests}
    assert "replicas" not in by_kind["Deployment"]["spec"]
    hpa = by_kind["HorizontalPodAutoscaler"]
    assert hpa["apiVersion"] == "autoscaling/v2"
    assert hpa["spec"]["scaleTargetRef"] == {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "name": "frontend",
    }
    assert (hpa["spec"]["minReplicas"], hpa["spec"]["maxReplicas"]) == (2, 4)
    assert bundle.components("application") == frozenset({"frontend"})


def test_the_autoscaler_changes_the_bundle_digest() -> None:
    assert parse(autoscaled_document()).digest != parse(bundle_document()).digest


def test_a_pinned_replica_count_and_an_autoscaler_cannot_coexist() -> None:
    document = autoscaled_document()
    next(item for item in document["objects"] if item["kind"] == "Deployment")["spec"][
        "replicas"
    ] = 2

    with pytest.raises(ValidationError, match="replicas and autoscaler are inconsistent"):
        parse(document)


def test_an_unpinned_deployment_requires_its_autoscaler() -> None:
    document = bundle_document()
    del next(item for item in document["objects"] if item["kind"] == "Deployment")["spec"][
        "replicas"
    ]

    with pytest.raises(ValidationError, match="replicas and autoscaler are inconsistent"):
        parse(document)


def test_an_autoscaler_needs_its_own_entitys_named_deployment() -> None:
    document = bundle_document()
    document["objects"].append(autoscaler() | {"name": "missing"})
    with pytest.raises(ValidationError, match="requires its own Entity's named Deployment"):
        parse(document)

    other_entity = autoscaled_document()
    other_entity["objects"][-1]["entity_id"] = "other"
    with pytest.raises(ValidationError, match="requires its own Entity's named Deployment"):
        parse(other_entity)


@pytest.mark.parametrize(
    "spec",
    [
        {"minReplicas": 4, "maxReplicas": 2},
        {"minReplicas": 0},
        {"maxReplicas": 11},
        {"metrics": []},
        {"metrics": [deepcopy(METRIC)] * 3},
        {"metrics": [{**METRIC, "type": "Pods"}]},
        {"behavior": {}},
        {
            "metrics": [
                {
                    "type": "Resource",
                    "resource": {
                        "name": "ephemeral-storage",
                        "target": {"type": "Utilization", "averageUtilization": 70},
                    },
                }
            ]
        },
        {
            "metrics": [
                {
                    "type": "Resource",
                    "resource": {
                        "name": "cpu",
                        "target": {"type": "Utilization", "averageUtilization": 0},
                    },
                }
            ]
        },
    ],
)
def test_autoscaler_bounds_and_metrics_stay_within_the_supported_contract(
    spec: dict[str, Any],
) -> None:
    document = autoscaled_document()
    document["objects"][-1]["spec"].update(spec)

    with pytest.raises(ValidationError):
        parse(document)


def deployment_state(*, spec: dict[str, Any], **status: int) -> dict[str, Any]:
    return {
        "metadata": {"generation": 3},
        "spec": spec,
        "status": {"observedGeneration": 3} | status,
    }


def test_rollout_without_pinned_replicas_follows_the_controller_reported_count() -> None:
    ready = {"replicas": 3, "updatedReplicas": 3, "availableReplicas": 3, "readyReplicas": 3}

    assert rollout_complete(deployment_state(spec={}, **ready))
    assert not rollout_complete(deployment_state(spec={}, **(ready | {"readyReplicas": 2})))
    assert not rollout_complete(deployment_state(spec={}, **(ready | {"updatedReplicas": 1})))


def test_rollout_without_pinned_replicas_is_never_complete_at_zero() -> None:
    assert not rollout_complete(
        deployment_state(
            spec={}, replicas=0, updatedReplicas=0, availableReplicas=0, readyReplicas=0
        )
    )


def test_a_pinned_replica_count_still_governs_the_rollout() -> None:
    state = deployment_state(
        spec={"replicas": 2}, replicas=1, updatedReplicas=1, availableReplicas=1, readyReplicas=1
    )

    assert not rollout_complete(state)


def test_apply_creates_the_autoscaler_only_after_its_deployment(cluster) -> None:
    cluster = cluster
    bundle = parse(autoscaled_document())
    manifests = list(
        bundle.render(
            "fdai-demo",
            frozenset({"application"}),
            {("application", "frontend"): "example.azurecr.io/frontend@sha256:" + "a" * 64},
        )
    )
    manifests.sort(key=lambda item: item["kind"] != "HorizontalPodAutoscaler")
    for manifest in manifests:
        manifest["metadata"]["namespace"] = cluster.namespace
    workload = Workload(cluster=cluster, namespace=cluster.namespace, health_timeout_seconds=1.0)

    assert workload.apply(manifests)

    kinds = [kind for verb, kind, _ in cluster.writes() if verb == "apply"]
    assert kinds.index("Deployment") < kinds.index("HorizontalPodAutoscaler")
