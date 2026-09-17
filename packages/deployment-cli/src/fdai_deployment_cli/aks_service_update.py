"""Validate one digest-pinned AKS service rollout without widening its change scope."""

from __future__ import annotations

import re
from typing import Any

from fdai_deployment_cli.contracts import load_json_object

SERVICES = frozenset(
    {
        "core-control-plane",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
        "operator-service",
    }
)

_IMAGE = re.compile(r"[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}")
_SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}")


def validate_update_request(
    *, service: str, image: str, source_commit: str, current_image: str
) -> None:
    """Require one known service, immutable image, exact revision, and stable repository."""

    if service not in SERVICES:
        raise ValueError("AKS service update names an unsupported service")
    if _IMAGE.fullmatch(image) is None:
        raise ValueError("AKS service update image must be digest-pinned")
    if _SOURCE_COMMIT.fullmatch(source_commit) is None:
        raise ValueError("AKS service update source commit must be an exact lowercase revision")
    if (
        _IMAGE.fullmatch(current_image) is None
        or image.partition("@")[0] != current_image.partition("@")[0]
    ):
        raise ValueError("AKS service update cannot change the service image repository")
    if image == current_image:
        raise ValueError("AKS service update image must differ from the active desired image")


def deployment_snapshot(raw: str, *, expected_services: set[str]) -> dict[str, dict[str, object]]:
    """Return bounded rollout identity for the complete expected Deployment set."""

    document = load_json_object(
        raw.encode("utf-8"), label="AKS Deployment snapshot", max_bytes=16 * 1024 * 1024
    )
    items = document.get("items")
    if document.get("kind") != "DeploymentList" or not isinstance(items, list):
        raise ValueError("AKS Deployment snapshot is invalid")
    result: dict[str, dict[str, object]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("AKS Deployment snapshot item is invalid")
        try:
            metadata = item["metadata"]
            template = item["spec"]["template"]
            labels = template["metadata"]["labels"]
            containers = template["spec"]["containers"]
            name = metadata["name"]
            uid = metadata["uid"]
            generation = metadata["generation"]
        except (KeyError, TypeError) as exc:
            raise ValueError("AKS Deployment snapshot fields are incomplete") from exc
        if (
            not isinstance(name, str)
            or name not in expected_services
            or name in result
            or not isinstance(uid, str)
            or not uid
            or type(generation) is not int
            or generation < 1
            or not isinstance(labels, dict)
            or not isinstance(containers, list)
        ):
            raise ValueError("AKS Deployment snapshot identity is invalid")
        runtime = [
            container
            for container in containers
            if isinstance(container, dict) and container.get("name") == name
        ]
        source_commit = labels.get("fdai.io/source-commit")
        image = runtime[0].get("image") if len(runtime) == 1 else None
        if (
            not isinstance(source_commit, str)
            or _SOURCE_COMMIT.fullmatch(source_commit) is None
            or not isinstance(image, str)
            or _IMAGE.fullmatch(image) is None
        ):
            raise ValueError("AKS Deployment snapshot rollout binding is invalid")
        result[name] = {
            "uid": uid,
            "generation": generation,
            "image": image,
            "source_commit": source_commit,
        }
    if set(result) != expected_services:
        raise ValueError("AKS Deployment snapshot is missing an expected service")
    return dict(sorted(result.items()))


def validate_plan_scope(summary: dict[str, Any], *, service: str) -> None:
    """Accept exactly one in-place Deployment update and no other planned mutation."""

    target = f'kubernetes_deployment_v1.workload["{service}"]'
    changes = summary.get("resource_changes")
    if not isinstance(changes, list):
        raise ValueError("AKS service update plan inventory is invalid")
    updates: list[str] = []
    for item in changes:
        if not isinstance(item, dict):
            raise ValueError("AKS service update plan change is invalid")
        address = item.get("address")
        actions = item.get("actions")
        if not isinstance(address, str) or not isinstance(actions, list):
            raise ValueError("AKS service update plan change is invalid")
        action_set = set(actions)
        if action_set.issubset({"no-op", "read"}):
            continue
        if action_set == {"update"} and address == target:
            updates.append(address)
            continue
        raise ValueError("AKS service update plan contains an out-of-scope mutation")
    if updates != [target]:
        raise ValueError("AKS service update plan must contain one selected Deployment update")


def peers_unchanged(
    *,
    before: dict[str, dict[str, object]],
    after: dict[str, dict[str, object]],
    service: str,
) -> bool:
    """Prove every unselected Deployment retained rollout identity and generation."""

    if set(before) != set(after) or service not in before:
        return False
    return all(before[name] == after[name] for name in before if name != service)
