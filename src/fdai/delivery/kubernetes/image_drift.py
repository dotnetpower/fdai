"""UID-grounded Kubernetes image pull drift candidates."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

_PULL_FAILURES: Final = frozenset({"ErrImagePull", "ImagePullBackOff", "InvalidImageName"})
_WORKLOAD_KINDS: Final = frozenset({"DaemonSet", "Deployment", "StatefulSet"})
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")


def image_pull_controller_drift_findings(
    resources: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
) -> tuple[dict[str, Any], ...]:
    """Correlate pull failures with controller template drift over exact UID chains."""

    if not evidence_complete:
        return ()
    index = _resource_index(resources)
    findings: list[dict[str, Any]] = []
    for pod in sorted(resources, key=_identity):
        if pod.get("kind") != "Pod" or not _valid_identity(pod):
            continue
        controller = _controller_template(pod, index)
        pod_spec = pod.get("pod_spec")
        template = controller.get("pod_template") if controller is not None else None
        if (
            controller is None
            or not isinstance(pod_spec, Mapping)
            or pod_spec.get("projection_complete") is not True
            or not isinstance(template, Mapping)
            or template.get("projection_complete") is not True
        ):
            continue
        observed = _container_fingerprints(pod_spec.get("containers"))
        expected_items = _container_fingerprints(template.get("containers"))
        failures = _pull_failures(pod.get("containers"))
        if observed is None or expected_items is None or failures is None:
            continue
        expected = dict(expected_items)
        for source_index, (name, fingerprint) in enumerate(observed):
            controller_fingerprint = expected.get(name)
            waiting_reason = failures.get(name)
            if (
                controller_fingerprint is None
                or waiting_reason is None
                or fingerprint == controller_fingerprint
            ):
                continue
            findings.append(
                {
                    "reason": "pod_image_pull_controller_template_drift_candidate",
                    "resource": _finding_identity(pod),
                    "controller": _finding_identity(controller),
                    "container": name,
                    "waiting_reason": waiting_reason,
                    "source_paths": [
                        f"/spec/containers/{source_index}/image",
                        "/controller/spec/template/spec/containers/image",
                    ],
                    "observed_image_reference_sha256": fingerprint,
                    "controller_image_reference_sha256": controller_fingerprint,
                    "evidence_strength": "exact_uid_chain_and_image_fingerprint",
                    "causality": "candidate_only",
                    "decision": "hold",
                }
            )
    return tuple(findings[:32])


def _resource_index(
    resources: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str, str], tuple[Mapping[str, Any], ...]]:
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for resource in resources:
        if _valid_identity(resource):
            grouped.setdefault(_identity(resource), []).append(resource)
    return {key: tuple(values) for key, values in grouped.items()}


def _controller_template(
    resource: Mapping[str, Any],
    index: Mapping[tuple[str, str, str, str], tuple[Mapping[str, Any], ...]],
) -> Mapping[str, Any] | None:
    current = resource
    visited: set[tuple[str, str, str, str]] = set()
    for _ in range(4):
        if current.get("owner_reference_projection_complete") is not True:
            return None
        references = [
            item
            for item in _mappings(current.get("owner_references"))
            if item.get("controller") is True
        ]
        if len(references) != 1:
            return None
        reference = references[0]
        identity = (
            str(reference.get("kind") or ""),
            str(current.get("namespace") or ""),
            str(reference.get("name") or ""),
            str(reference.get("uid") or ""),
        )
        if not all(identity) or identity in visited:
            return None
        visited.add(identity)
        candidates = index.get(identity, ())
        if len(candidates) != 1:
            return None
        current = candidates[0]
        if current.get("kind") in _WORKLOAD_KINDS:
            return current
    return None


def _container_fingerprints(value: object) -> list[tuple[str, str]] | None:
    containers = _mappings(value)
    result: list[tuple[str, str]] = []
    names: set[str] = set()
    for container in containers:
        name = container.get("name")
        fingerprint = container.get("image_reference_sha256")
        if (
            not isinstance(name, str)
            or not name
            or name in names
            or not isinstance(fingerprint, str)
            or _SHA256.fullmatch(fingerprint) is None
        ):
            return None
        names.add(name)
        result.append((name, fingerprint))
    return result


def _pull_failures(value: object) -> dict[str, str] | None:
    failures: dict[str, str] = {}
    names: set[str] = set()
    for status in _mappings(value):
        name = status.get("name")
        if not isinstance(name, str) or not name or name in names:
            return None
        names.add(name)
        reason = status.get("reason")
        if status.get("state") == "waiting" and reason in _PULL_FAILURES:
            failures[name] = str(reason)
    return failures


def _valid_identity(value: Mapping[str, Any]) -> bool:
    return all(
        isinstance(value.get(key), str) and bool(value.get(key))
        for key in ("kind", "name", "namespace", "uid")
    )


def _identity(value: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(value.get("kind") or ""),
        str(value.get("namespace") or ""),
        str(value.get("name") or ""),
        str(value.get("uid") or ""),
    )


def _finding_identity(value: Mapping[str, Any]) -> dict[str, str]:
    return {
        "kind": str(value.get("kind") or "")[:128],
        "name": str(value.get("name") or "")[:253],
        "namespace": str(value.get("namespace") or "")[:253],
        "uid": str(value.get("uid") or "")[:128],
    }


def _mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["image_pull_controller_drift_findings"]
