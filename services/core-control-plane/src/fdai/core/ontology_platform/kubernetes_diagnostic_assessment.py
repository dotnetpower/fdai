"""Reduce exact-target AKS diagnostic evidence into a Forseti-owned T0 receipt."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from fdai.shared.contracts.models import ContractBase
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.kubernetes_metric import KubernetesMetricWindowEvidence


class AksDiagnosticStatus(StrEnum):
    """Primary evidence classification for one exact Kubernetes target."""

    AUTOSCALE_LIMITED = "autoscale_limited"
    CONTROL_PLANE_UNAVAILABLE = "control_plane_unavailable"
    CRASH_LOOP = "crash_loop"
    ENDPOINT_UNREADY = "endpoint_unready"
    EVICTED = "evicted"
    HELD = "held"
    IMAGE_PULL_FAILED = "image_pull_failed"
    NODE_PRESSURE = "node_pressure"
    NETWORKING_UNAVAILABLE = "networking_unavailable"
    NO_FAILURE_SIGNAL = "no_failure_signal"
    OOM_KILLED = "oom_killed"
    PROBE_FAILURE_EVIDENCE = "probe_failure_evidence"
    QUOTA_CONSTRAINED = "quota_constrained"
    RESOURCE_PRESSURE = "resource_pressure"
    ROLLOUT_STALLED = "rollout_stalled"
    SCHEDULING_BLOCKED = "scheduling_blocked"
    STORAGE_BLOCKED = "storage_blocked"


_SIGNAL_PRIORITY = tuple(AksDiagnosticStatus)
_EVIDENCE_CODE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")


class AksDiagnosticEvidenceReceipt(ContractBase):
    """Replayable no-authority evidence emitted for Forseti RCA admission."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    owner_agent: Literal["Forseti"] = "Forseti"
    principal_class: str
    purpose: Literal["operations-review"] = "operations-review"
    producer_version: str
    method_version: str
    target_resource_id: str
    target_uid: str
    target_resource_version: str
    ontology_release: str
    cutoff: datetime
    source_cutoffs: dict[str, datetime]
    source_revisions: dict[str, str]
    status: AksDiagnosticStatus
    signals: tuple[AksDiagnosticStatus, ...]
    complete: bool
    evidence_gaps: tuple[str, ...]
    conflicts: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    synthetic: Literal[False] = False
    cause_claim_supported: Literal[False] = False
    execution_authority: Literal[False] = False
    audit_correlation_id: str


@dataclass(frozen=True, slots=True)
class AksDiagnosticContext:
    """Exact target and independently qualified evidence used by one reducer."""

    target: ResourceRecord
    related: tuple[ResourceRecord, ...]
    event_reasons: tuple[str, ...]
    metrics: tuple[KubernetesMetricWindowEvidence, ...]
    api_reachable: bool | None
    azure_availability: str | None
    cutoff: datetime
    source_cutoffs: dict[str, datetime]
    source_revisions: dict[str, str]
    evidence_refs: tuple[str, ...]
    evidence_complete: bool
    ontology_release: str
    principal_class: str
    audit_correlation_id: str
    evidence_gaps: tuple[str, ...] = ()


def assess_aks_diagnostic(context: AksDiagnosticContext) -> AksDiagnosticEvidenceReceipt:
    """Return deterministic signals without claiming root cause or execution authority."""

    if context.cutoff.tzinfo is None or context.cutoff.utcoffset() is None:
        raise ValueError("AKS diagnostic cutoff MUST be timezone-aware")
    if not isinstance(context.evidence_complete, bool) or (
        context.api_reachable is not None and not isinstance(context.api_reachable, bool)
    ):
        raise ValueError("AKS diagnostic boolean flags MUST be booleans")
    if not context.target.resource_id.strip() or len(context.target.resource_id) > 1_024:
        raise ValueError("AKS diagnostic target Resource id MUST be bounded non-empty text")
    if not context.principal_class.strip() or len(context.principal_class) > 64:
        raise ValueError("AKS diagnostic principal class MUST be bounded non-empty text")
    if not context.audit_correlation_id.strip() or len(context.audit_correlation_id) > 128:
        raise ValueError("AKS diagnostic audit correlation MUST be bounded non-empty text")
    if re.fullmatch(r"sha256:[a-f0-9]{64}", context.ontology_release) is None:
        raise ValueError("AKS diagnostic ontology release MUST be a lowercase SHA-256")
    props = context.target.props
    cluster_ref = _required_text(props, "cluster_ref")
    uid = _required_text(props, "uid")
    resource_version = _required_text(props, "resource_version")
    namespace = _optional_namespace(props.get("namespace"))
    for source, cutoff in context.source_cutoffs.items():
        if (
            _EVIDENCE_CODE.fullmatch(source) is None
            or cutoff.tzinfo is None
            or cutoff.utcoffset() is None
            or cutoff > context.cutoff
        ):
            raise ValueError("AKS diagnostic source cutoff is invalid")
    if len(context.source_cutoffs) > 16 or len(context.source_revisions) > 16:
        raise ValueError("AKS diagnostic source evidence exceeds its bound")
    if any(
        _EVIDENCE_CODE.fullmatch(key) is None or not value.strip() or len(value) > 256
        for key, value in context.source_revisions.items()
    ):
        raise ValueError("AKS diagnostic source revisions MUST be bounded non-empty text")
    if len(context.evidence_gaps) > 32 or any(
        _EVIDENCE_CODE.fullmatch(gap) is None for gap in context.evidence_gaps
    ):
        raise ValueError("AKS diagnostic evidence gaps MUST be bounded reason codes")
    if len(context.evidence_refs) > 32 or any(
        not ref.strip() or len(ref) > 512 for ref in context.evidence_refs
    ):
        raise ValueError("AKS diagnostic evidence refs MUST be bounded non-empty text")

    gaps = list(dict.fromkeys(context.evidence_gaps))
    conflicts: list[str] = []
    if not context.evidence_complete:
        gaps.append("required_evidence_incomplete")
    if set(context.source_cutoffs) != set(context.source_revisions):
        conflicts.append("source_identity_mismatch")
    qualified_metrics, metric_conflicts = _qualified_metrics(
        context,
        cluster_ref=cluster_ref,
        uid=uid,
        namespace=namespace,
    )
    conflicts.extend(metric_conflicts)
    signals = _signals(context, metrics=qualified_metrics)
    if conflicts or (not signals and gaps):
        status = AksDiagnosticStatus.HELD
    elif signals:
        status = min(signals, key=_SIGNAL_PRIORITY.index)
    else:
        status = AksDiagnosticStatus.NO_FAILURE_SIGNAL
    return AksDiagnosticEvidenceReceipt(
        principal_class=context.principal_class,
        producer_version="aks-diagnostic-evidence-v1",
        method_version="deterministic-t0-v1",
        target_resource_id=context.target.resource_id,
        target_uid=uid,
        target_resource_version=resource_version,
        ontology_release=context.ontology_release,
        cutoff=context.cutoff,
        source_cutoffs=context.source_cutoffs,
        source_revisions=context.source_revisions,
        status=status,
        signals=tuple(sorted(signals, key=_SIGNAL_PRIORITY.index)),
        complete=not gaps and not conflicts,
        evidence_gaps=tuple(gaps),
        conflicts=tuple(conflicts),
        evidence_refs=tuple(dict.fromkeys(context.evidence_refs)),
        audit_correlation_id=context.audit_correlation_id,
    )


def _signals(
    context: AksDiagnosticContext,
    *,
    metrics: tuple[KubernetesMetricWindowEvidence, ...],
) -> set[AksDiagnosticStatus]:
    props = context.target.props
    signals: set[AksDiagnosticStatus] = set()
    waiting = _string_set(props.get("container_waiting_reasons"))
    waiting.update(_string_set(props.get("init_container_waiting_reasons")))
    if waiting & {"ErrImagePull", "ImagePullBackOff", "InvalidImageName"}:
        signals.add(AksDiagnosticStatus.IMAGE_PULL_FAILED)
    if "CrashLoopBackOff" in waiting:
        signals.add(AksDiagnosticStatus.CRASH_LOOP)
    terminations = props.get("container_terminations")
    if isinstance(terminations, tuple) and any(
        isinstance(item, dict) and item.get("reason") == "OOMKilled" for item in terminations
    ):
        signals.add(AksDiagnosticStatus.OOM_KILLED)
    if props.get("reason") == "Evicted":
        signals.add(AksDiagnosticStatus.EVICTED)
    if "Unhealthy" in context.event_reasons:
        signals.add(AksDiagnosticStatus.PROBE_FAILURE_EVIDENCE)
    conditions = _conditions(props)
    if conditions.get("PodScheduled") == "False":
        signals.add(AksDiagnosticStatus.SCHEDULING_BLOCKED)
    if any(
        conditions.get(name) == "True" for name in ("DiskPressure", "MemoryPressure", "PIDPressure")
    ):
        signals.add(AksDiagnosticStatus.NODE_PRESSURE)
    if conditions.get("NetworkUnavailable") == "True" or set(context.event_reasons) & {
        "DNSConfigForming",
        "FailedCreatePodSandBox",
        "FailedPodNetworkSetup",
        "NetworkNotReady",
    }:
        signals.add(AksDiagnosticStatus.NETWORKING_UNAVAILABLE)
    if context.target.type == "kubernetes.endpoint-slice":
        endpoint_count = _count(props, "endpoint_count")
        ready = _count(props, "ready")
        ready_unknown = _count(props, "ready_unknown")
        if endpoint_count > 0 and ready == 0 and ready_unknown == 0:
            signals.add(AksDiagnosticStatus.ENDPOINT_UNREADY)
    if context.target.type in {
        "kubernetes.daemon-set",
        "kubernetes.deployment",
        "kubernetes.stateful-set",
    } and (_count(props, "unavailable_replicas") > 0 or conditions.get("Progressing") == "False"):
        signals.add(AksDiagnosticStatus.ROLLOUT_STALLED)
    if context.target.type in {
        "kubernetes.persistent-volume",
        "kubernetes.persistent-volume-claim",
    } and props.get("phase") in {"Failed", "Lost", "Pending", "Released"}:
        signals.add(AksDiagnosticStatus.STORAGE_BLOCKED)
    if context.target.type == "kubernetes.resource-quota" and _quota_exhausted(props):
        signals.add(AksDiagnosticStatus.QUOTA_CONSTRAINED)
    if context.target.type == "kubernetes.horizontal-pod-autoscaler" and (
        conditions.get("ScalingLimited") == "True"
        or (
            _count(props, "max_replicas") > 0
            and _count(props, "current_replicas") >= _count(props, "max_replicas")
        )
    ):
        signals.add(AksDiagnosticStatus.AUTOSCALE_LIMITED)
    if context.api_reachable is False or context.azure_availability in {
        "Degraded",
        "Unavailable",
    }:
        signals.add(AksDiagnosticStatus.CONTROL_PLANE_UNAVAILABLE)
    for metric in metrics:
        if metric.metric_name == "kubernetes.container.oom_events" and any(
            point.value > 0 for point in metric.points
        ):
            signals.add(AksDiagnosticStatus.OOM_KILLED)
        if metric.metric_name in {
            "kubernetes.container.cpu.throttled_seconds",
            "kubernetes.node.pressure",
        } and any(point.value > 0 for point in metric.points):
            signals.add(AksDiagnosticStatus.RESOURCE_PRESSURE)
    return signals


def _qualified_metrics(
    context: AksDiagnosticContext,
    *,
    cluster_ref: str,
    uid: str,
    namespace: str | None,
) -> tuple[tuple[KubernetesMetricWindowEvidence, ...], tuple[str, ...]]:
    qualified: list[KubernetesMetricWindowEvidence] = []
    conflicts: list[str] = []
    for metric in context.metrics:
        if (
            metric.target.cluster_ref != cluster_ref
            or metric.target.uid != uid
            or metric.target.namespace != namespace
        ):
            if "metric_target_mismatch" not in conflicts:
                conflicts.append("metric_target_mismatch")
            continue
        if not metric.complete:
            continue
        if (
            metric.provider_cutoff is None
            or metric.end > metric.provider_cutoff
            or metric.provider_cutoff > context.cutoff
        ):
            if "metric_window_mismatch" not in conflicts:
                conflicts.append("metric_window_mismatch")
            continue
        if (
            context.source_cutoffs.get(metric.source_identity) != metric.provider_cutoff
            or context.source_revisions.get(metric.source_identity) != metric.source_revision
        ):
            if "metric_source_mismatch" not in conflicts:
                conflicts.append("metric_source_mismatch")
            continue
        expected_labels = {"cluster_ref": cluster_ref, "uid": uid}
        if namespace is not None:
            expected_labels["namespace"] = namespace
        if any(
            point.metric_name != metric.metric_name
            or point.at.tzinfo is None
            or not metric.start <= point.at <= metric.end
            or any(point.labels.get(key) != value for key, value in expected_labels.items())
            for point in metric.points
        ):
            if "metric_point_mismatch" not in conflicts:
                conflicts.append("metric_point_mismatch")
            continue
        qualified.append(metric)
    return tuple(qualified), tuple(conflicts)


def _conditions(props: Mapping[str, object]) -> dict[str, str]:
    raw = props.get("diagnostic_conditions")
    if not isinstance(raw, tuple):
        return {}
    output: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        kind = item.get("type")
        status = item.get("status")
        if isinstance(kind, str) and isinstance(status, str):
            output[kind] = status
    return output


def _quota_exhausted(props: Mapping[str, object]) -> bool:
    hard = props.get("quota_hard")
    used = props.get("quota_used")
    return (
        isinstance(hard, Mapping)
        and isinstance(used, Mapping)
        and any(used.get(key) == value for key, value in hard.items())
    )


def _string_set(value: object) -> set[str]:
    if not isinstance(value, tuple):
        return set()
    return {item for item in value if isinstance(item, str)}


def _count(props: Mapping[str, object], key: str) -> int:
    direct = props.get(key)
    if isinstance(direct, int) and not isinstance(direct, bool):
        return direct
    status_counts = props.get("status_counts")
    if isinstance(status_counts, Mapping):
        nested = status_counts.get(key)
        if isinstance(nested, int) and not isinstance(nested, bool):
            return nested
    return 0


def _required_text(props: Mapping[str, object], key: str) -> str:
    value = props.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"AKS diagnostic target {key} MUST be bounded non-empty text")
    return value.strip()


def _optional_namespace(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 253:
        raise ValueError("AKS diagnostic target namespace MUST be bounded non-empty text or null")
    return value.strip()


__all__ = [
    "AksDiagnosticContext",
    "AksDiagnosticEvidenceReceipt",
    "AksDiagnosticStatus",
    "assess_aks_diagnostic",
]
