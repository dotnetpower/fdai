"""Validate exact AKS Deployment and Pod observations without granting readiness alone."""

from __future__ import annotations

import re
from typing import Any

from fdai_deployment_cli.contracts import load_json_object

_IMAGE = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}")
_REQUIRED = {"core-control-plane", "operator-service", "isolated-executor"}


def verify_workload_health(
    *,
    deployments: str,
    pods: str,
    expected: dict[str, Any],
    source_commit: str | None = None,
) -> bool:
    """Require complete exact-source workloads, available replicas and running image digests.

    Empty, duplicate, stale, malformed or partially healthy observations return false.
    This proves only workload health, not transport, migrations, jobs or application readiness.
    """
    if not expected or (
        source_commit is not None and re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
    ):
        return False
    try:
        deployment_items = _items(deployments, "DeploymentList")
        pod_items = _items(pods, "PodList")
        names = [item["metadata"]["name"] for item in deployment_items]
        if len(names) != len(set(names)) or set(names) != set(expected):
            return False
        for item in deployment_items:
            name = item["metadata"]["name"]
            contract = expected[name]
            image = contract["image"]
            expected_source = contract.get("source_commit", source_commit)
            if not isinstance(image, str) or _IMAGE.fullmatch(image) is None:
                return False
            if (
                not isinstance(expected_source, str)
                or re.fullmatch(r"[0-9a-f]{40}", expected_source) is None
            ):
                return False
            replicas = item["spec"]["replicas"]
            minimum, maximum = contract["replicas"], contract["max_replicas"]
            if any(type(value) is not int for value in (replicas, minimum, maximum)):
                return False
            if not 1 <= minimum <= replicas <= maximum:
                return False
            generation = item["metadata"]["generation"]
            status = item["status"]
            if type(generation) is not int or generation < 1:
                return False
            if (
                type(status.get("observedGeneration")) is not int
                or status.get("observedGeneration") != generation
            ):
                return False
            if any(
                type(status.get(key)) is not int or status.get(key) != replicas
                for key in ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas")
            ):
                return False
            if status.get("unavailableReplicas", 0) != 0:
                return False
            template = item["spec"]["template"]
            if template["metadata"]["labels"].get("fdai.io/source-commit") != expected_source:
                return False
            if not any(
                container.get("name") == name and container.get("image") == image
                for container in template["spec"]["containers"]
            ):
                return False
            selected = [
                pod
                for pod in pod_items
                if pod["metadata"].get("labels", {}).get("app.kubernetes.io/name") == name
            ]
            active = [pod for pod in selected if not pod["metadata"].get("deletionTimestamp")]
            if len(active) != replicas or not all(
                _healthy_pod(pod, name, image, expected_source) for pod in active
            ):
                return False
        return True
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _items(raw: str, kind: str) -> list[dict[str, Any]]:
    result = load_json_object(
        raw.encode("utf-8"), label="AKS observation", max_bytes=16 * 1024 * 1024
    )
    items = result.get("items")
    if result.get("kind") != kind or not isinstance(items, list) or len(items) > 4096:
        raise ValueError("AKS observation list is invalid")
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("AKS observation item is invalid")
    return items


def _healthy_pod(pod: dict[str, Any], name: str, image: str, source_commit: str) -> bool:
    labels = pod["metadata"].get("labels", {})
    if (
        labels.get("fdai.io/source-commit") != source_commit
        or pod["status"].get("phase") != "Running"
    ):
        return False
    conditions = pod["status"].get("conditions", [])
    if not any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in conditions
    ):
        return False
    containers = pod["status"].get("containerStatuses", [])
    runtime = [container for container in containers if container.get("name") == name]
    if len(runtime) != 1 or not all(container.get("ready") is True for container in containers):
        return False
    container = runtime[0]
    image_id = container.get("imageID", "")
    return (
        container.get("image") == image
        and isinstance(image_id, str)
        and image_id.endswith("@" + image.split("@", 1)[1])
        and isinstance(container.get("state", {}).get("running"), dict)
    )
