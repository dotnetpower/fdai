"""UID-grounded Kubernetes liveness probe failure candidates."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Final

_LIVENESS_FAILURE: Final = re.compile(r"\bliveness probe failed\b", re.IGNORECASE)
_READINESS_FAILURE: Final = re.compile(r"\breadiness probe failed\b", re.IGNORECASE)
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")


def is_liveness_probe_failure(*, reason: str, message: str) -> bool:
    """Recognize one reviewed kubelet liveness failure phrase."""

    return reason == "Unhealthy" and _LIVENESS_FAILURE.search(message) is not None


def is_readiness_probe_failure(*, reason: str, message: str, reporter: str) -> bool:
    """Recognize one reviewed kubelet readiness failure phrase."""

    return (
        reason == "Unhealthy"
        and reporter in {"kubelet", "kubernetes.io/kubelet"}
        and _READINESS_FAILURE.search(message) is not None
    )


def liveness_probe_failure_findings(
    resources: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
    evidence_cutoff: datetime,
    window: timedelta = timedelta(minutes=5),
) -> tuple[dict[str, Any], ...]:
    """Join recent liveness failures to one immutable workload probe chain."""

    return _probe_failure_findings(
        resources,
        events,
        evidence_complete=evidence_complete,
        evidence_cutoff=evidence_cutoff,
        window=window,
        event_code="liveness_probe_failed",
        probe_key="liveness_probe",
        reason="workload_liveness_probe_failure_candidate",
        source_path="/spec/template/spec/containers/livenessProbe",
    )


def readiness_probe_failure_findings(
    resources: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
    evidence_cutoff: datetime,
    window: timedelta = timedelta(minutes=5),
) -> tuple[dict[str, Any], ...]:
    """Join recent readiness failures to one immutable workload probe chain."""

    return _probe_failure_findings(
        resources,
        events,
        evidence_complete=evidence_complete,
        evidence_cutoff=evidence_cutoff,
        window=window,
        event_code="readiness_probe_failed",
        probe_key="readiness_probe",
        reason="workload_readiness_probe_failure_candidate",
        source_path="/spec/template/spec/containers/readinessProbe",
    )


def _probe_failure_findings(
    resources: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
    evidence_cutoff: datetime,
    window: timedelta,
    event_code: str,
    probe_key: str,
    reason: str,
    source_path: str,
) -> tuple[dict[str, Any], ...]:

    if not evidence_complete or evidence_cutoff.tzinfo is None or window <= timedelta(0):
        return ()
    lower_bound = evidence_cutoff - window
    index = _index(resources)
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for event in events:
        regarding = event.get("regarding")
        observed_at = _timestamp(event.get("last_seen"))
        if (
            event.get("code") != event_code
            or not isinstance(regarding, Mapping)
            or regarding.get("kind") != "Pod"
            or observed_at is None
            or observed_at < lower_bound
            or observed_at > evidence_cutoff
        ):
            continue
        pod_identity = (
            "Pod",
            str(event.get("namespace") or ""),
            str(regarding.get("name") or ""),
            str(regarding.get("uid") or ""),
        )
        pods = index.get(pod_identity, ())
        if len(pods) != 1:
            continue
        chain = _controller_chain(pods[0], index)
        if chain is None:
            continue
        replica, workload = chain
        workload_identity = _identity(workload)
        if workload_identity in seen or not _degraded(workload):
            continue
        common = _common_probe(pods[0], replica, workload, probe_key=probe_key)
        if common is None:
            continue
        seen.add(workload_identity)
        container, probe = common
        findings.append(
            {
                "reason": reason,
                "resource": _finding_identity(workload_identity),
                "affected_pod": _finding_identity(pod_identity),
                "container": container,
                "probe": probe,
                **(
                    {
                        "aggressive_schedule": (
                            probe.get("initial_delay_seconds") == 0
                            and probe.get("period_seconds") == 1
                            and probe.get("startup_probe_present") is False
                        )
                    }
                    if probe_key == "liveness_probe"
                    else {}
                ),
                "source_paths": [source_path],
                "last_seen": observed_at.isoformat(),
                "evidence_strength": "recent_event_exact_uid_chain_and_probe_fingerprint",
                "causality": "candidate_only",
                "decision": "hold",
            }
        )
    return tuple(findings[:32])


def _controller_chain(
    pod: Mapping[str, Any],
    index: Mapping[tuple[str, str, str, str], tuple[Mapping[str, Any], ...]],
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    replica = _single_controller(pod, index, expected_kind="ReplicaSet")
    if replica is None:
        return None
    workload = _single_controller(replica, index, expected_kind="Deployment")
    return (replica, workload) if workload is not None else None


def _single_controller(
    resource: Mapping[str, Any],
    index: Mapping[tuple[str, str, str, str], tuple[Mapping[str, Any], ...]],
    *,
    expected_kind: str,
) -> Mapping[str, Any] | None:
    if resource.get("owner_reference_projection_complete") is not True:
        return None
    owners = [
        item
        for item in _mappings(resource.get("owner_references"))
        if item.get("controller") is True
    ]
    if len(owners) != 1 or owners[0].get("kind") != expected_kind:
        return None
    identity = (
        expected_kind,
        str(resource.get("namespace") or ""),
        str(owners[0].get("name") or ""),
        str(owners[0].get("uid") or ""),
    )
    candidates = index.get(identity, ())
    return candidates[0] if len(candidates) == 1 else None


def _common_probe(
    pod: Mapping[str, Any],
    replica: Mapping[str, Any],
    workload: Mapping[str, Any],
    *,
    probe_key: str,
) -> tuple[str, dict[str, Any]] | None:
    groups = [
        _probes(pod.get("pod_spec"), probe_key=probe_key),
        _probes(replica.get("pod_template"), probe_key=probe_key),
        _probes(workload.get("pod_template"), probe_key=probe_key),
    ]
    if any(group is None for group in groups):
        return None
    complete_groups = [group for group in groups if group is not None]
    identities = [set(group) for group in complete_groups]
    if len(identities[0]) != 1 or any(group != identities[0] for group in identities[1:]):
        return None
    identity = next(iter(identities[0]))
    return identity[0], complete_groups[-1][identity]


def _probes(
    value: object,
    *,
    probe_key: str,
) -> dict[tuple[str, str, bool], dict[str, Any]] | None:
    if not isinstance(value, Mapping) or value.get("projection_complete") is not True:
        return None
    probes: dict[tuple[str, str, bool], dict[str, Any]] = {}
    for container in _mappings(value.get("containers")):
        name = container.get("name")
        probe = container.get(probe_key)
        if not isinstance(name, str) or not name or not isinstance(probe, Mapping) or not probe:
            continue
        digest = probe.get("definition_sha256")
        mechanism = probe.get("mechanism")
        if (
            not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
            or mechanism not in {"httpGet", "tcpSocket", "exec", "grpc"}
        ):
            return None
        startup_probe_present = (
            probe.get("startup_probe_present") is True if probe_key == "liveness_probe" else False
        )
        identity = (name, digest, startup_probe_present)
        if identity in probes:
            return None
        probes[identity] = {
            "mechanism": str(mechanism),
            "definition_sha256": digest,
            **(
                {"startup_probe_present": startup_probe_present}
                if probe_key == "liveness_probe"
                else {}
            ),
            **{
                key: probe[key]
                for key in ("initial_delay_seconds", "period_seconds", "failure_threshold")
                if isinstance(probe.get(key), int) and not isinstance(probe.get(key), bool)
            },
        }
    return probes


def _degraded(value: Mapping[str, Any]) -> bool:
    desired = value.get("desired")
    ready = value.get("ready")
    return (
        isinstance(desired, int)
        and not isinstance(desired, bool)
        and isinstance(ready, int)
        and not isinstance(ready, bool)
        and desired > ready
    )


def _index(
    resources: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str, str], tuple[Mapping[str, Any], ...]]:
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for resource in resources:
        identity = _identity(resource)
        if all(identity):
            grouped.setdefault(identity, []).append(resource)
    return {key: tuple(values) for key, values in grouped.items()}


def _identity(value: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(value.get("kind") or ""),
        str(value.get("namespace") or ""),
        str(value.get("name") or ""),
        str(value.get("uid") or ""),
    )


def _finding_identity(identity: tuple[str, str, str, str]) -> dict[str, str]:
    return {"kind": identity[0], "namespace": identity[1], "name": identity[2], "uid": identity[3]}


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


__all__ = [
    "is_liveness_probe_failure",
    "is_readiness_probe_failure",
    "liveness_probe_failure_findings",
    "readiness_probe_failure_findings",
]
