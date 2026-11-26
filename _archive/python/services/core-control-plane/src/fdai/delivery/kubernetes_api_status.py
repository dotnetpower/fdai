"""Normalize bounded Kubernetes status fields for inventory records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

_MAX_CONTAINER_STATUSES: Final[int] = 128
_MAX_CONDITIONS: Final[int] = 64
_MAX_STATUS_TEXT: Final[int] = 128


class KubernetesApiFailureReason(StrEnum):
    """Sanitized boundary that prevented one complete Kubernetes generation."""

    AUTHENTICATION_FAILED = "kubernetes_authentication_failed"
    AUTHORIZATION_FAILED = "kubernetes_authorization_failed"
    API_UNAVAILABLE = "kubernetes_api_unavailable"
    DNS_UNAVAILABLE = "kubernetes_dns_unavailable"
    NETWORK_UNAVAILABLE = "kubernetes_network_unavailable"
    REQUEST_REJECTED = "kubernetes_request_rejected"
    REQUEST_TIMEOUT = "kubernetes_request_timeout"
    RESPONSE_INVALID = "kubernetes_response_invalid"
    TLS_UNAVAILABLE = "kubernetes_tls_unavailable"


class KubernetesApiInventoryError(RuntimeError):
    """One Kubernetes inventory generation could not complete safely."""

    def __init__(
        self,
        message: str,
        *,
        reason: KubernetesApiFailureReason = KubernetesApiFailureReason.RESPONSE_INVALID,
    ) -> None:
        super().__init__(message)
        self.reason = reason


def node_status_properties(status: Mapping[str, Any]) -> dict[str, object]:
    """Return bounded Node readiness facts without provider-controlled text."""

    return _ready_condition_properties(status, subject="Node")


def pod_status_properties(status: Mapping[str, Any]) -> dict[str, object]:
    """Return bounded Pod phase, readiness, restart, and termination facts."""

    props: dict[str, object] = {}
    phase = _optional_status_text(status, "phase")
    if phase is not None:
        props["phase"] = phase
    props.update(_ready_condition_properties(status, subject="Pod"))

    container_statuses = _bounded_mapping_sequence(
        status.get("containerStatuses"),
        field="containerStatuses",
        limit=_MAX_CONTAINER_STATUSES,
    )
    if container_statuses:
        ready_count = 0
        restart_count = 0
        waiting_reasons: list[str] = []
        termination_records: list[dict[str, object]] = []
        for container_status in container_statuses:
            container_name = _required_status_text(container_status, "name")
            ready = container_status.get("ready")
            if not isinstance(ready, bool):
                raise KubernetesApiInventoryError(
                    "Kubernetes container ready status MUST be boolean"
                )
            ready_count += int(ready)
            restart_count += _required_non_negative_int(container_status, "restartCount")
            state = container_status.get("state")
            if state is not None and not isinstance(state, Mapping):
                raise KubernetesApiInventoryError("Kubernetes container state is malformed")
            waiting = state.get("waiting") if isinstance(state, Mapping) else None
            if waiting is not None and not isinstance(waiting, Mapping):
                raise KubernetesApiInventoryError("Kubernetes container waiting state is malformed")
            if isinstance(waiting, Mapping):
                reason = _optional_status_text(waiting, "reason")
                if reason is not None:
                    waiting_reasons.append(reason)
            termination_records.extend(
                _container_termination_records(
                    container_status,
                    container_name=container_name,
                )
            )
        props["container_count"] = len(container_statuses)
        props["ready_container_count"] = ready_count
        props["restart_count"] = restart_count
        if waiting_reasons:
            props["container_waiting_reasons"] = tuple(sorted(set(waiting_reasons)))
        if termination_records:
            props["container_terminations"] = tuple(
                sorted(
                    termination_records,
                    key=lambda item: (
                        str(item["container_name"]),
                        str(item["observation_kind"]),
                    ),
                )
            )
    return props


def deployment_status_properties(status: Mapping[str, Any]) -> dict[str, object]:
    """Return bounded Deployment generation, replica, and progression facts."""

    field_names = (
        ("observedGeneration", "observed_generation"),
        ("updatedReplicas", "updated_replicas"),
        ("readyReplicas", "ready_replicas"),
        ("availableReplicas", "available_replicas"),
        ("unavailableReplicas", "unavailable_replicas"),
    )
    props: dict[str, object] = {}
    for source_name, output_name in field_names:
        value = optional_non_negative_int(status, source_name)
        if value is not None:
            props[output_name] = value
    conditions = _bounded_mapping_sequence(
        status.get("conditions"),
        field="conditions",
        limit=_MAX_CONDITIONS,
    )
    progressing_conditions = [
        condition
        for condition in conditions
        if _optional_status_text(condition, "type") == "Progressing"
    ]
    if len(progressing_conditions) > 1:
        raise KubernetesApiInventoryError(
            "Kubernetes Deployment Progressing condition is duplicated"
        )
    if progressing_conditions:
        progressing_status = _optional_status_text(progressing_conditions[0], "status")
        if progressing_status not in {"True", "False", "Unknown"}:
            raise KubernetesApiInventoryError(
                "Kubernetes Deployment Progressing condition status is invalid"
            )
        props["progressing_status"] = progressing_status
        progressing_reason = _optional_status_text(progressing_conditions[0], "reason")
        if progressing_reason is not None:
            props["progressing_reason"] = progressing_reason
    return props


def optional_non_negative_int(value: Mapping[str, Any], key: str) -> int | None:
    """Return a bounded optional non-negative status counter."""

    raw = value.get(key)
    if raw is None:
        return None
    return _non_negative_int(raw, key)


def _ready_condition_properties(
    status: Mapping[str, Any],
    *,
    subject: str,
) -> dict[str, object]:
    conditions = _bounded_mapping_sequence(
        status.get("conditions"),
        field="conditions",
        limit=_MAX_CONDITIONS,
    )
    ready_conditions = [
        condition for condition in conditions if _optional_status_text(condition, "type") == "Ready"
    ]
    if len(ready_conditions) > 1:
        raise KubernetesApiInventoryError(f"Kubernetes {subject} Ready condition is duplicated")
    if not ready_conditions:
        return {}
    ready_status = _optional_status_text(ready_conditions[0], "status")
    if ready_status not in {"True", "False", "Unknown"}:
        raise KubernetesApiInventoryError(f"Kubernetes {subject} Ready condition status is invalid")
    props: dict[str, object] = {"ready_status": ready_status}
    if ready_status != "Unknown":
        props["ready"] = ready_status == "True"
    return props


def _container_termination_records(
    container_status: Mapping[str, Any],
    *,
    container_name: str,
) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for state_key, observation_kind in (("state", "current"), ("lastState", "previous")):
        state = container_status.get(state_key)
        if state is None:
            continue
        if not isinstance(state, Mapping):
            raise KubernetesApiInventoryError(f"Kubernetes container {state_key} is malformed")
        terminated = state.get("terminated")
        if terminated is None:
            continue
        if not isinstance(terminated, Mapping):
            raise KubernetesApiInventoryError(
                f"Kubernetes container {state_key}.terminated is malformed"
            )
        record: dict[str, object] = {
            "container_name": container_name,
            "observation_kind": observation_kind,
            "exit_code": _required_non_negative_int(terminated, "exitCode"),
        }
        reason = _optional_status_text(terminated, "reason")
        signal = optional_non_negative_int(terminated, "signal")
        finished_at = _optional_status_time(terminated, "finishedAt")
        if reason is not None:
            record["reason"] = reason
        if signal is not None:
            record["signal"] = signal
        if finished_at is not None:
            record["finished_at"] = finished_at.isoformat()
        records.append(record)
    return tuple(records)


def _bounded_mapping_sequence(
    value: object,
    *,
    field: str,
    limit: int,
) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) > limit:
        raise KubernetesApiInventoryError(f"Kubernetes {field} exceeds its contract")
    if any(not isinstance(item, Mapping) for item in value):
        raise KubernetesApiInventoryError(f"Kubernetes {field} contains a malformed item")
    return tuple(item for item in value if isinstance(item, Mapping))


def _optional_status_text(value: Mapping[str, Any], key: str) -> str | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip() or len(raw) > _MAX_STATUS_TEXT:
        raise KubernetesApiInventoryError(f"Kubernetes status {key!r} is malformed")
    return raw.strip()


def _required_status_text(value: Mapping[str, Any], key: str) -> str:
    result = _optional_status_text(value, key)
    if result is None:
        raise KubernetesApiInventoryError(f"Kubernetes status {key!r} is missing")
    return result


def _optional_status_time(value: Mapping[str, Any], key: str) -> datetime | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise KubernetesApiInventoryError(f"Kubernetes status {key!r} is malformed")
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise KubernetesApiInventoryError(f"Kubernetes status {key!r} is malformed") from exc
    if parsed.tzinfo is None:
        raise KubernetesApiInventoryError(f"Kubernetes status {key!r} MUST include timezone")
    return parsed.astimezone(UTC)


def _required_non_negative_int(value: Mapping[str, Any], key: str) -> int:
    if key not in value:
        raise KubernetesApiInventoryError(f"Kubernetes status {key!r} is missing")
    return _non_negative_int(value[key], key)


def _non_negative_int(value: object, key: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise KubernetesApiInventoryError(
            f"Kubernetes status {key!r} MUST be a non-negative integer"
        )
    return value


__all__ = [
    "KubernetesApiFailureReason",
    "KubernetesApiInventoryError",
    "deployment_status_properties",
    "node_status_properties",
    "optional_non_negative_int",
    "pod_status_properties",
]
