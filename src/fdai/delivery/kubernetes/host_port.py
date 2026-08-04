"""UID-grounded Kubernetes host-port conflict candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any


def host_port_conflict_findings(
    resources: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
    evidence_cutoff: datetime,
    window: timedelta = timedelta(minutes=5),
) -> tuple[dict[str, Any], ...]:
    """Correlate recent scheduler port failures to exact Pod hostPort declarations."""

    if not evidence_complete or evidence_cutoff.tzinfo is None or window <= timedelta(0):
        return ()
    pods = _pod_index(resources)
    lower_bound = evidence_cutoff - window
    grouped_events: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for event in events:
        regarding = event.get("regarding")
        observed_at = _timestamp(event.get("last_seen"))
        event_name = event.get("name")
        if (
            event.get("code") != "host_port_conflict"
            or not isinstance(regarding, Mapping)
            or regarding.get("kind") != "Pod"
            or observed_at is None
            or observed_at < lower_bound
            or observed_at > evidence_cutoff
            or not isinstance(event_name, str)
            or not event_name
        ):
            continue
        identity = (
            "Pod",
            str(event.get("namespace") or ""),
            str(regarding.get("name") or ""),
            str(regarding.get("uid") or ""),
        )
        if not all(identity) or len(pods.get(identity, ())) != 1:
            continue
        group = grouped_events.setdefault(
            identity,
            {"event_names": set(), "last_seen": observed_at},
        )
        group["event_names"].add(event_name[:253])
        group["last_seen"] = max(group["last_seen"], observed_at)

    findings: list[dict[str, Any]] = []
    for identity, event_group in sorted(grouped_events.items()):
        pod = pods[identity][0]
        pod_spec = pod.get("pod_spec")
        if not isinstance(pod_spec, Mapping) or pod_spec.get("projection_complete") is not True:
            continue
        requested = _requested_host_ports(pod_spec.get("containers"))
        if requested is None or not requested:
            continue
        findings.append(
            {
                "reason": "pod_host_port_conflict_candidate",
                "resource": {
                    "kind": identity[0],
                    "name": identity[2],
                    "namespace": identity[1],
                    "uid": identity[3],
                },
                "source_paths": [item.pop("source_path") for item in requested],
                "requested_host_ports": requested,
                "event_names": sorted(event_group["event_names"]),
                "last_seen": event_group["last_seen"].isoformat(),
                "evidence_strength": "recent_scheduler_event_and_exact_pod_uid",
                "causality": "candidate_only",
                "decision": "hold",
            }
        )
    return tuple(findings[:32])


def _pod_index(
    resources: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str, str], tuple[Mapping[str, Any], ...]]:
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for resource in resources:
        identity = (
            str(resource.get("kind") or ""),
            str(resource.get("namespace") or ""),
            str(resource.get("name") or ""),
            str(resource.get("uid") or ""),
        )
        if identity[0] == "Pod" and all(identity):
            grouped.setdefault(identity, []).append(resource)
    return {key: tuple(values) for key, values in grouped.items()}


def _requested_host_ports(value: object) -> list[dict[str, Any]] | None:
    containers = _mappings(value)
    requested: list[dict[str, Any]] = []
    names: set[str] = set()
    for container_index, container in enumerate(containers):
        name = container.get("name")
        if not isinstance(name, str) or not name or name in names:
            return None
        names.add(name)
        if "host_ports" not in container:
            continue
        if container.get("host_port_projection_complete") is not True:
            return None
        for port in _mappings(container.get("host_ports")):
            host_port = port.get("host_port")
            protocol = port.get("protocol")
            source_index = port.get("source_index")
            if (
                not isinstance(host_port, int)
                or isinstance(host_port, bool)
                or not 1 <= host_port <= 65_535
                or protocol not in {"TCP", "UDP", "SCTP"}
                or not isinstance(source_index, int)
                or isinstance(source_index, bool)
                or not 0 <= source_index < 32
            ):
                return None
            requested.append(
                {
                    "container": name,
                    "host_port": host_port,
                    "protocol": str(protocol),
                    "source_path": (
                        f"/spec/containers/{container_index}/ports/{source_index}/hostPort"
                    ),
                }
            )
    return requested


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["host_port_conflict_findings"]
