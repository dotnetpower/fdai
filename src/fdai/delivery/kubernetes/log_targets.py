"""Bounded, starvation-resistant Kubernetes log target selection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any


def select_bounded_log_targets(
    resources: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
    max_pods: int,
    max_containers_per_pod: int,
) -> tuple[dict[str, Any], ...]:
    """Select exact Pod targets while reserving capacity for recent workloads."""

    if not evidence_complete or not 1 <= max_pods <= 64 or not 1 <= max_containers_per_pod <= 8:
        return ()
    targets = _targets(resources, max_containers_per_pod=max_containers_per_pod)
    priority = sorted(
        targets,
        key=lambda item: (
            item["ready"],
            not item["active_failure"],
            not item["restarted"],
            -item["created_at"].timestamp(),
            item["namespace"],
            item["name"],
            item["uid"],
        ),
    )
    recent = sorted(
        targets,
        key=lambda item: (
            -item["created_at"].timestamp(),
            item["namespace"],
            item["name"],
            item["uid"],
        ),
    )
    selected = priority[: (max_pods + 1) // 2]
    selected_identities = {_identity(item) for item in selected}
    for candidate in [*recent, *priority]:
        if len(selected) >= max_pods:
            break
        identity = _identity(candidate)
        if identity in selected_identities:
            continue
        selected.append(candidate)
        selected_identities.add(identity)
    return tuple(
        {
            "kind": "Pod",
            "namespace": item["namespace"],
            "name": item["name"],
            "uid": item["uid"],
            "containers": item["containers"],
            "selection_reasons": [
                reason
                for reason, matched in (
                    ("active_failure", item["active_failure"]),
                    ("restarted", item["restarted"]),
                    ("not_ready", not item["ready"]),
                )
                if matched
            ],
        }
        for item in selected
    )


def _targets(
    resources: Sequence[Mapping[str, Any]],
    *,
    max_containers_per_pod: int,
) -> list[dict[str, Any]]:
    identities: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for resource in resources:
        if resource.get("kind") != "Pod":
            continue
        identity = (
            str(resource.get("namespace") or ""),
            str(resource.get("name") or ""),
            str(resource.get("uid") or ""),
        )
        if all(identity):
            identities.setdefault(identity, []).append(resource)
    targets: list[dict[str, Any]] = []
    for identity, candidates in identities.items():
        if len(candidates) != 1:
            continue
        pod = candidates[0]
        if pod.get("container_status_projection_complete") is not True:
            continue
        created_at = _timestamp(pod.get("created_at"))
        statuses = _statuses(pod.get("containers"))
        if created_at is None or statuses is None or not statuses:
            continue
        ordered_statuses = sorted(
            statuses,
            key=lambda item: (
                not _active_failure(item),
                not _restarted(item),
                str(item.get("name") or ""),
            ),
        )
        targets.append(
            {
                "namespace": identity[0],
                "name": identity[1],
                "uid": identity[2],
                "containers": [
                    str(item.get("name"))[:253]
                    for item in ordered_statuses[:max_containers_per_pod]
                ],
                "ready": all(item.get("ready") is True for item in statuses),
                "active_failure": any(_active_failure(item) for item in statuses),
                "restarted": any(_restarted(item) for item in statuses),
                "created_at": created_at,
            }
        )
    return targets


def _statuses(value: object) -> list[Mapping[str, Any]] | None:
    if not isinstance(value, list):
        return None
    names: set[str] = set()
    statuses: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        name = item.get("name")
        if not isinstance(name, str) or not name or name in names:
            return None
        names.add(name)
        statuses.append(item)
    return statuses


def _active_failure(value: Mapping[str, Any]) -> bool:
    return value.get("state") in {"waiting", "terminated"} and bool(value.get("reason"))


def _restarted(value: Mapping[str, Any]) -> bool:
    restarts = value.get("restarts")
    return isinstance(restarts, int) and not isinstance(restarts, bool) and restarts > 0


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _identity(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(value["namespace"]), str(value["name"]), str(value["uid"])


__all__ = ["select_bounded_log_targets"]
