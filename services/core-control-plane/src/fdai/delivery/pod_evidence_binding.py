"""Bind typed Kubernetes Pod lifecycle evidence into the analyzer tick.

A Pod lifecycle conclusion is only replayable when the observations that
produced it are typed and validated at the boundary. This module decodes one
strictly shaped, bounded JSON document into the canonical observation types the
Pod reducers require, so a malformed or partially observed document fails at
composition time with the environment key named, instead of reaching a reducer
as a plausible-looking but unverified conclusion.

The binding is the same shape ``FDAI_TRACE_TOPOLOGIES_JSON`` uses: a venue that
resolves Pod evidence ahead of the tick declares it here, and a venue that
declares nothing simply runs without a Pod analyzer. It carries no credential,
no endpoint, and no tenant value.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from fdai.core.investigation import (
    PodLifecycleEvidence,
    StaticPodLifecycleEvidenceSource,
)
from fdai.core.ontology_platform.kubernetes_pod_recovery_evidence import (
    PodOwnerDeploymentObservation,
    PodRecoveryObservation,
    PodRestartHistoryObservation,
)
from fdai.core.ontology_platform.kubernetes_pod_replacement_evidence import (
    DeploymentReplicaObservation,
    PodLifecycleObservation,
    PodReplacementDeploymentObservation,
    PodTerminationObservation,
)
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactMetadata,
)

POD_EVIDENCE_ENV = "FDAI_POD_LIFECYCLE_EVIDENCE_JSON"

_MAX_DOCUMENT_CHARS = 512 * 1024
_MAX_EVIDENCE_ITEMS = 32
_MAX_CANDIDATES = 32
_MAX_REPLICA_HISTORY = 64
_MAX_STRINGS = 32

_EVIDENCE_KEYS = frozenset(
    {
        "resource_ref",
        "old_pod",
        "candidates",
        "termination",
        "deployment",
        "recovery_pod",
        "restart_history",
        "owner_deployment",
        "correlation_window_start",
        "cutoff",
        "graph_complete",
        "ownership_complete",
        "detected_at",
    }
)
_LIFECYCLE_KEYS = frozenset(
    {
        "pod_id",
        "pod_uid",
        "cluster_id",
        "namespace",
        "owner_uid",
        "root_controller_uid",
        "root_controller_kind",
        "owner_link",
        "root_controller_link",
        "created_at",
        "phase",
        "ready",
        "container_count",
        "ready_container_count",
        "restart_count",
        "waiting_reasons",
        "workload_revision",
        "metadata",
        "evidence_refs",
    }
)
_TERMINATION_KEYS = frozenset(
    {
        "pod_uid",
        "cluster_id",
        "namespace",
        "event_type",
        "reason",
        "exit_code",
        "event_time",
        "recorded_at",
        "source_identity",
        "source_revision",
        "evidence_refs",
    }
)
_DEPLOYMENT_KEYS = frozenset(
    {
        "deployment_id",
        "deployment_uid",
        "cluster_id",
        "namespace",
        "desired_replicas_before",
        "desired_replicas_after",
        "desired_replica_history",
        "replica_history_complete",
        "ready_replicas",
        "available_replicas",
        "unavailable_replicas",
        "metadata",
        "evidence_refs",
    }
)
_RECOVERY_POD_KEYS = frozenset(
    {
        "pod_id",
        "phase",
        "ready",
        "container_count",
        "ready_container_count",
        "restart_count",
        "waiting_reasons",
        "metadata",
    }
)
_RESTART_HISTORY_KEYS = frozenset(
    {
        "pod_id",
        "start",
        "end",
        "restart_delta",
        "complete",
        "missing_reason",
        "evidence_refs",
    }
)
_OWNER_DEPLOYMENT_KEYS = frozenset(
    {
        "deployment_id",
        "desired_replicas",
        "ready_replicas",
        "available_replicas",
        "unavailable_replicas",
        "metadata",
    }
)


class PodEvidenceBindingError(ValueError):
    """One Pod lifecycle evidence document could not be decoded as declared."""


def build_pod_lifecycle_evidence_source(
    environ: Mapping[str, str] | None = None,
) -> StaticPodLifecycleEvidenceSource | None:
    """Return the declared Pod evidence source, or ``None`` when unbound.

    An unbound source is a supported posture: the tick simply carries no Pod
    analyzer, and any configured Pod target is reported as an unsupported
    target rather than assessed from evidence nothing observed.
    """

    raw = (environ if environ is not None else os.environ).get(POD_EVIDENCE_ENV, "").strip()
    if not raw:
        return None
    return StaticPodLifecycleEvidenceSource(parse_pod_lifecycle_evidence(raw))


def parse_pod_lifecycle_evidence(raw: str) -> tuple[PodLifecycleEvidence, ...]:
    """Decode the declared JSON document into canonical typed evidence."""

    if len(raw) > _MAX_DOCUMENT_CHARS:
        raise PodEvidenceBindingError(f"{POD_EVIDENCE_ENV} exceeds its size bound")
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PodEvidenceBindingError(f"{POD_EVIDENCE_ENV} MUST be a JSON array: {exc}") from exc
    if not isinstance(decoded, list) or not decoded:
        raise PodEvidenceBindingError(f"{POD_EVIDENCE_ENV} MUST be a non-empty JSON array")
    if len(decoded) > _MAX_EVIDENCE_ITEMS:
        raise PodEvidenceBindingError(
            f"{POD_EVIDENCE_ENV} MUST carry at most {_MAX_EVIDENCE_ITEMS} items"
        )
    evidence: list[PodLifecycleEvidence] = []
    for index, item in enumerate(decoded):
        try:
            evidence.append(_evidence(item))
        except (ValueError, TypeError, KeyError) as exc:
            raise PodEvidenceBindingError(f"{POD_EVIDENCE_ENV}[{index}]: {exc}") from exc
    return tuple(evidence)


def _evidence(value: Any) -> PodLifecycleEvidence:
    item = _mapping(value, _EVIDENCE_KEYS, "pod lifecycle evidence")
    candidates_raw = item["candidates"]
    if not isinstance(candidates_raw, list) or not 1 <= len(candidates_raw) <= _MAX_CANDIDATES:
        raise ValueError("candidates MUST be a bounded non-empty array")
    return PodLifecycleEvidence(
        resource_ref=_text(item["resource_ref"], "resource_ref"),
        old_pod=_lifecycle_observation(item["old_pod"]),
        candidates=tuple(_lifecycle_observation(entry) for entry in candidates_raw),
        termination=_optional(item["termination"], _termination_observation),
        deployment=_optional(item["deployment"], _deployment_observation),
        recovery_pod=_recovery_observation(item["recovery_pod"]),
        restart_history=_restart_history(item["restart_history"]),
        owner_deployment=_owner_deployment(item["owner_deployment"]),
        correlation_window_start=_time(item["correlation_window_start"]),
        cutoff=_time(item["cutoff"]),
        graph_complete=_flag(item["graph_complete"], "graph_complete"),
        ownership_complete=_flag(item["ownership_complete"], "ownership_complete"),
        detected_at=_optional(item["detected_at"], _time),
    )


def _lifecycle_observation(value: Any) -> PodLifecycleObservation:
    item = _mapping(value, _LIFECYCLE_KEYS, "pod lifecycle observation")
    return PodLifecycleObservation(
        pod_id=_text(item["pod_id"], "pod_id"),
        pod_uid=_text(item["pod_uid"], "pod_uid"),
        cluster_id=_text(item["cluster_id"], "cluster_id"),
        namespace=_text(item["namespace"], "namespace"),
        owner_uid=_optional_text(item["owner_uid"], "owner_uid"),
        root_controller_uid=_optional_text(item["root_controller_uid"], "root_controller_uid"),
        root_controller_kind=_optional_text(item["root_controller_kind"], "root_controller_kind"),
        owner_link=_optional(item["owner_link"], _link_metadata),
        root_controller_link=_optional(item["root_controller_link"], _link_metadata),
        created_at=_optional(item["created_at"], _time),
        phase=_optional_text(item["phase"], "phase"),
        ready=_optional_flag(item["ready"], "ready"),
        container_count=_optional_count(item["container_count"], "container_count"),
        ready_container_count=_optional_count(
            item["ready_container_count"], "ready_container_count"
        ),
        restart_count=_optional_count(item["restart_count"], "restart_count"),
        waiting_reasons=_texts(item["waiting_reasons"], "waiting_reasons"),
        workload_revision=_optional_text(item["workload_revision"], "workload_revision"),
        metadata=_state_fact(item["metadata"]),
        evidence_refs=_texts(item["evidence_refs"], "evidence_refs"),
    )


def _termination_observation(value: Any) -> PodTerminationObservation:
    item = _mapping(value, _TERMINATION_KEYS, "pod termination observation")
    return PodTerminationObservation(
        pod_uid=_text(item["pod_uid"], "pod_uid"),
        cluster_id=_text(item["cluster_id"], "cluster_id"),
        namespace=_text(item["namespace"], "namespace"),
        event_type=_optional_text(item["event_type"], "event_type"),
        reason=_optional_text(item["reason"], "reason"),
        exit_code=_optional_count(item["exit_code"], "exit_code"),
        event_time=_optional(item["event_time"], _time),
        recorded_at=_optional(item["recorded_at"], _time),
        source_identity=_optional_text(item["source_identity"], "source_identity"),
        source_revision=_optional_text(item["source_revision"], "source_revision"),
        evidence_refs=_texts(item["evidence_refs"], "evidence_refs"),
    )


def _deployment_observation(value: Any) -> PodReplacementDeploymentObservation:
    item = _mapping(value, _DEPLOYMENT_KEYS, "pod replacement deployment observation")
    history_raw = item["desired_replica_history"]
    if not isinstance(history_raw, list) or not 1 <= len(history_raw) <= _MAX_REPLICA_HISTORY:
        raise ValueError("desired_replica_history MUST be a bounded non-empty array")
    history: list[DeploymentReplicaObservation] = []
    for entry in history_raw:
        replica = _mapping(entry, frozenset({"observed_at", "desired_replicas"}), "replica history")
        history.append(
            DeploymentReplicaObservation(
                observed_at=_time(replica["observed_at"]),
                desired_replicas=_count(replica["desired_replicas"], "desired_replicas"),
            )
        )
    return PodReplacementDeploymentObservation(
        deployment_id=_text(item["deployment_id"], "deployment_id"),
        deployment_uid=_text(item["deployment_uid"], "deployment_uid"),
        cluster_id=_text(item["cluster_id"], "cluster_id"),
        namespace=_text(item["namespace"], "namespace"),
        desired_replicas_before=_optional_count(
            item["desired_replicas_before"], "desired_replicas_before"
        ),
        desired_replicas_after=_optional_count(
            item["desired_replicas_after"], "desired_replicas_after"
        ),
        desired_replica_history=tuple(history),
        replica_history_complete=_flag(
            item["replica_history_complete"], "replica_history_complete"
        ),
        ready_replicas=_optional_count(item["ready_replicas"], "ready_replicas"),
        available_replicas=_optional_count(item["available_replicas"], "available_replicas"),
        unavailable_replicas=_optional_count(item["unavailable_replicas"], "unavailable_replicas"),
        metadata=_state_fact(item["metadata"]),
        evidence_refs=_texts(item["evidence_refs"], "evidence_refs"),
    )


def _recovery_observation(value: Any) -> PodRecoveryObservation:
    item = _mapping(value, _RECOVERY_POD_KEYS, "pod recovery observation")
    return PodRecoveryObservation(
        pod_id=_text(item["pod_id"], "pod_id"),
        phase=_optional_text(item["phase"], "phase"),
        ready=_optional_flag(item["ready"], "ready"),
        container_count=_optional_count(item["container_count"], "container_count"),
        ready_container_count=_optional_count(
            item["ready_container_count"], "ready_container_count"
        ),
        restart_count=_optional_count(item["restart_count"], "restart_count"),
        waiting_reasons=_texts(item["waiting_reasons"], "waiting_reasons"),
        metadata=_state_fact(item["metadata"]),
    )


def _restart_history(value: Any) -> PodRestartHistoryObservation:
    item = _mapping(value, _RESTART_HISTORY_KEYS, "pod restart history observation")
    return PodRestartHistoryObservation(
        pod_id=_text(item["pod_id"], "pod_id"),
        start=_time(item["start"]),
        end=_time(item["end"]),
        restart_delta=_optional_count(item["restart_delta"], "restart_delta"),
        complete=_flag(item["complete"], "complete"),
        missing_reason=_optional_text(item["missing_reason"], "missing_reason"),
        evidence_refs=_texts(item["evidence_refs"], "evidence_refs"),
    )


def _owner_deployment(value: Any) -> PodOwnerDeploymentObservation:
    item = _mapping(value, _OWNER_DEPLOYMENT_KEYS, "pod owner deployment observation")
    return PodOwnerDeploymentObservation(
        deployment_id=_text(item["deployment_id"], "deployment_id"),
        desired_replicas=_optional_count(item["desired_replicas"], "desired_replicas"),
        ready_replicas=_optional_count(item["ready_replicas"], "ready_replicas"),
        available_replicas=_optional_count(item["available_replicas"], "available_replicas"),
        unavailable_replicas=_optional_count(item["unavailable_replicas"], "unavailable_replicas"),
        metadata=_state_fact(item["metadata"]),
    )


def _state_fact(value: Any) -> StateFactMetadata:
    if not isinstance(value, Mapping):
        raise ValueError("state fact metadata MUST be an object")
    return StateFactMetadata.from_mapping(value)


def _link_metadata(value: Any) -> LinkObservationMetadata:
    if not isinstance(value, Mapping):
        raise ValueError("link observation metadata MUST be an object")
    return LinkObservationMetadata.from_mapping(value)


def _mapping(value: Any, expected: frozenset[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} MUST be an object")
    keys = set(value)
    if keys != set(expected):
        missing = sorted(set(expected) - keys)
        unknown = sorted(keys - set(expected))
        raise ValueError(f"{name} keys are invalid (missing={missing}, unknown={unknown})")
    return value


def _optional(value: Any, decode: Any) -> Any:
    return None if value is None else decode(value)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} MUST be non-empty text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _texts(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > _MAX_STRINGS:
        raise ValueError(f"{name} MUST be a bounded array of text")
    return tuple(_text(item, name) for item in value)


def _flag(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} MUST be a boolean")
    return value


def _optional_flag(value: Any, name: str) -> bool | None:
    return None if value is None else _flag(value, name)


def _count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} MUST be a non-negative integer")
    return int(value)


def _optional_count(value: Any, name: str) -> int | None:
    return None if value is None else _count(value, name)


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamps MUST be ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {value!r} MUST be timezone-aware")
    return parsed


def pod_evidence_summary(evidence: Sequence[PodLifecycleEvidence]) -> dict[str, object]:
    """Describe the bound Pod evidence for the tick log without leaking values."""

    return {
        "pod_evidence_bound": len(evidence),
        "pod_evidence_resources": [item.resource_ref for item in evidence],
    }


__all__ = [
    "POD_EVIDENCE_ENV",
    "PodEvidenceBindingError",
    "build_pod_lifecycle_evidence_source",
    "parse_pod_lifecycle_evidence",
    "pod_evidence_summary",
]
