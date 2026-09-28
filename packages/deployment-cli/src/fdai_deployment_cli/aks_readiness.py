"""Validate exact AKS Deployment and Pod observations without granting readiness alone."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fdai_deployment_cli.contracts import load_json_object

_IMAGE = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}")
_CONFIG_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REQUIRED = {"core-control-plane", "operator-service", "isolated-executor"}
WORKLOAD_CONTRACT_KEYS = (
    "image",
    "replicas",
    "max_replicas",
    "source_commit",
    "secret_environment",
)


def workload_contract(workload: Mapping[str, Any]) -> dict[str, Any]:
    """Select the readback-relevant fields of one rendered AKS workload."""
    return {key: workload[key] for key in WORKLOAD_CONTRACT_KEYS}


def valid_secret_environment(value: object) -> bool:
    """Accept only a mapping of non-empty environment names to Key Vault object names."""
    return isinstance(value, dict) and all(
        isinstance(name, str) and name and isinstance(item, str) and item
        for name, item in value.items()
    )


def verify_workload_health(
    *,
    deployments: str,
    pods: str,
    expected: dict[str, Any],
    source_commit: str | None = None,
) -> bool:
    """Require complete exact-source workloads, available replicas and running image digests.

    When a workload contract declares ``secret_environment``, the deployed container must
    declare exactly those secret-backed environment bindings, so an out-of-band edit that
    drops or adds one fails closed instead of passing as a healthy rollout.

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
            if not _secret_bindings_match(template, name, contract):
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


def _secret_bindings_match(template: dict[str, Any], name: str, contract: dict[str, Any]) -> bool:
    """Require the deployed container to declare exactly the contracted secret-backed env."""
    required = contract.get("secret_environment")
    if required is None:
        return True
    if not valid_secret_environment(required):
        return False
    container = next(
        (item for item in template["spec"]["containers"] if item.get("name") == name),
        None,
    )
    if container is None:
        return False
    environment = container.get("env", [])
    if not isinstance(environment, list):
        return False
    observed: set[str] = set()
    for entry in environment:
        if not isinstance(entry, dict):
            return False
        reference = entry.get("valueFrom")
        if reference is None:
            continue
        if not isinstance(reference, dict):
            return False
        secret_reference = reference.get("secretKeyRef")
        if not isinstance(secret_reference, dict):
            return False
        env_name = entry.get("name")
        if (
            not isinstance(env_name, str)
            or env_name in observed
            or entry.get("value")
            or secret_reference.get("name") != name
            or secret_reference.get("key") != env_name
        ):
            return False
        observed.add(env_name)
    return observed == set(required)


def _items(raw: str, kind: str) -> list[dict[str, Any]]:
    result = load_json_object(
        raw.encode("utf-8"), label="AKS observation", max_bytes=16 * 1024 * 1024
    )
    items = result.get("items")
    if not isinstance(items, list) or len(items) > 4096:
        raise ValueError("AKS observation list is invalid")
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("AKS observation item is invalid")
    observed = result.get("kind")
    # `kubectl get <resource> --output json` wraps results in a generic `v1.List`
    # and moves the concrete type onto each item, while `kubectl get --raw` returns
    # the typed collection. Accept the generic envelope only when every item
    # declares the expected singular kind, so the type check is never weakened.
    singular = kind.removesuffix("List")
    if observed != kind and not (
        observed == "List" and all(item.get("kind") == singular for item in items)
    ):
        raise ValueError("AKS observation list is invalid")
    return items


def _running_image_matches(container: dict[str, Any], image: str) -> bool:
    """Prove the running container resolves to the exact expected image digest.

    ``imageID`` carries the authoritative pulled reference. The sibling ``image``
    field is runtime dependent: containerd reports the local config digest rather
    than the deployed reference, so a bare ``sha256:`` value is accepted there.
    """
    image_id = container.get("imageID")
    if not isinstance(image_id, str) or not image_id.endswith("@" + image.split("@", 1)[1]):
        return False
    observed = container.get("image")
    if not isinstance(observed, str) or not observed:
        return False
    return observed == image or _CONFIG_DIGEST.fullmatch(observed) is not None


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
    return _running_image_matches(container, image) and isinstance(
        container.get("state", {}).get("running"), dict
    )
