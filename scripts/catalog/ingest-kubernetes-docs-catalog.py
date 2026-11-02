#!/usr/bin/env python3
"""Ingest a bounded Kubernetes documentation scenario batch.

The source class is Kubernetes official operational documentation, licensed
CC BY 4.0. FDAI stores no copied prose: each curated mapping records only the
public URL, section locator, and review date. Extraction is deterministic and
network-free; a source watcher can later compare the locator upstream without
making catalog generation depend on network availability.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

import yaml
from fdai.core.detection.signals import SignalRole, known_signals

_HERE = pathlib.Path(__file__).resolve()
_REPO_ROOT = next(parent for parent in _HERE.parents if (parent / "pyproject.toml").is_file())
_OUT_DIR = _REPO_ROOT / "rule-catalog" / "chaos-scenarios" / "collected" / "kubernetes-docs"
_SOURCE_PREFIX = "https://kubernetes.io/docs/"
_SOURCE_LICENSE = "CC-BY-4.0"
_REVIEWED_AT = "2026-07-17"
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_ALLOWED_CATEGORIES = frozenset(
    {
        "compute",
        "network",
        "storage",
        "state",
        "dependency",
        "traffic",
        "time",
        "resource_saturation",
        "identity",
        "quota",
        "cost_governance",
    }
)
_ALLOWED_TARGET_TYPES = frozenset(
    {
        "pod",
        "node",
        "vm",
        "vmss",
        "db",
        "lb",
        "dns",
        "disk",
        "cache",
        "secret_store",
        "identity",
        "ingress",
        "egress",
        "quota",
        "llm_endpoint",
        "control_plane",
    }
)
_ALLOWED_FAULT_FAMILIES = frozenset(
    {
        "stop",
        "delay",
        "drop",
        "corrupt",
        "saturate",
        "throttle",
        "deny",
        "misroute",
        "expire",
        "quota_shrink",
        "oom",
        "hang",
        "preempt",
        "checkpoint_fail",
        "cache_overflow",
        "ramp",
    }
)
_ALLOWED_INTENSITIES = frozenset({"mild", "high", "extreme"})


@dataclass(frozen=True, slots=True)
class Entry:
    slug: str
    source_url: str
    source_section: str
    category: str
    target_type: str
    fault_family: str
    intensity: str
    expected_signal: str
    description: str
    rollback_note: str


_ENTRIES = (
    Entry(
        slug="pod-disruption-budget-gap",
        source_url="https://kubernetes.io/docs/concepts/workloads/pods/disruptions/",
        source_section="pod-disruption-budgets",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="backend_health",
        description="Concurrent voluntary disruptions exceed the workload availability budget.",
        rollback_note="Restore healthy replicas and stop additional voluntary disruptions.",
    ),
    Entry(
        slug="dns-resolution-failure",
        source_url="https://kubernetes.io/docs/tasks/administer-cluster/dns-debugging-resolution/",
        source_section="check-the-local-dns-configuration-first",
        category="network",
        target_type="dns",
        fault_family="misroute",
        intensity="high",
        expected_signal="request_failure",
        description="Workload DNS configuration prevents service-name resolution.",
        rollback_note="Restore the prior resolver configuration and verify service lookup.",
    ),
    Entry(
        slug="image-pull-backoff",
        source_url="https://kubernetes.io/docs/concepts/containers/images/#imagepullbackoff",
        source_section="imagepullbackoff",
        category="dependency",
        target_type="pod",
        fault_family="deny",
        intensity="high",
        expected_signal="rollout_stall",
        description="A workload cannot pull its declared image and the rollout stalls.",
        rollback_note="Restore the previous resolvable image reference and restart the rollout.",
    ),
    Entry(
        slug="crash-loop-backoff-liveness-probe",
        source_url=(
            "https://kubernetes.io/docs/tasks/configure-pod-container/"
            "configure-liveness-readiness-startup-probes/"
        ),
        source_section="define-a-liveness-command",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_crash_loop_back_off",
        description=(
            "Misconfigured or failing livenessProbe repeatedly restarts the container "
            "into CrashLoopBackOff."
        ),
        rollback_note="Restore valid livenessProbe command or threshold parameters and redeploy.",
    ),
    Entry(
        slug="readiness-probe-endpoint-removal",
        source_url=(
            "https://kubernetes.io/docs/tasks/configure-pod-container/"
            "configure-liveness-readiness-startup-probes/"
        ),
        source_section="define-readiness-probes",
        category="traffic",
        target_type="pod",
        fault_family="deny",
        intensity="mild",
        expected_signal="pod_unready",
        description=(
            "Failing readinessProbe removes the Pod from Service EndpointSlices "
            "without restarting the container."
        ),
        rollback_note="Restore backend dependency health or readinessProbe port configuration.",
    ),
    Entry(
        slug="container-oom-killed-memory-limit",
        source_url="https://kubernetes.io/docs/tasks/configure-pod-container/assign-memory-resource/",
        source_section="exceed-a-container-s-memory-limit",
        category="resource_saturation",
        target_type="pod",
        fault_family="oom",
        intensity="high",
        expected_signal="pod_oom_killed",
        description=(
            "Container memory usage exceeds its cgroup limit and triggers "
            "kernel OOMKilled termination."
        ),
        rollback_note=(
            "Restore safe memory limit and request sizing or roll back "
            "the leaking workload revision."
        ),
    ),
    Entry(
        slug="kubelet-node-not-ready-stop",
        source_url="https://kubernetes.io/docs/concepts/architecture/nodes/",
        source_section="node-status",
        category="compute",
        target_type="node",
        fault_family="stop",
        intensity="high",
        expected_signal="resource_availability",
        description=(
            "Stopped kubelet agent causes NodeReady status to become Unknown "
            "and triggers pod eviction."
        ),
        rollback_note="Restart the node kubelet service and verify NodeReady status recovery.",
    ),
    Entry(
        slug="network-policy-egress-deny-drop",
        source_url="https://kubernetes.io/docs/concepts/services-networking/network-policies/",
        source_section="default-deny-all-egress-traffic",
        category="network",
        target_type="egress",
        fault_family="drop",
        intensity="high",
        expected_signal="request_failure",
        description=(
            "Restrictive egress NetworkPolicy drops outbound Pod traffic "
            "despite destination ingress allowance."
        ),
        rollback_note=(
            "Restore the egress NetworkPolicy allow rule for the target service selector and port."
        ),
    ),
    Entry(
        slug="service-selector-label-mismatch",
        source_url="https://kubernetes.io/docs/concepts/services-networking/service/",
        source_section="defining-a-service",
        category="network",
        target_type="lb",
        fault_family="misroute",
        intensity="high",
        expected_signal="backend_health",
        description=(
            "Service label selector mismatch leaves EndpointSlices empty "
            "and collapses backend health."
        ),
        rollback_note="Align the Service selector labels with the active Pod template labels.",
    ),
    Entry(
        slug="resource-quota-admission-denial",
        source_url="https://kubernetes.io/docs/concepts/policy/resource-quotas/",
        source_section="compute-resource-quota",
        category="quota",
        target_type="quota",
        fault_family="quota_shrink",
        intensity="mild",
        expected_signal="rollout_stall",
        description=(
            "Namespace ResourceQuota exhaustion blocks ReplicaSet Pod creation during rollout."
        ),
        rollback_note="Restore namespace ResourceQuota headroom or right-size workload requests.",
    ),
    Entry(
        slug="node-taint-untolerated-pending",
        source_url="https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/",
        source_section="concepts",
        category="compute",
        target_type="node",
        fault_family="deny",
        intensity="mild",
        expected_signal="rollout_stall",
        description=(
            "Untolerated NoSchedule or NoExecute node taints leave newly "
            "scheduled Pods in Pending state."
        ),
        rollback_note=(
            "Remove the unintended node taint or add the matching toleration to the workload spec."
        ),
    ),
    Entry(
        slug="pvc-provisioning-mount-stall",
        source_url="https://kubernetes.io/docs/concepts/storage/persistent-volumes/",
        source_section="lifecycle-of-a-volume-and-claim",
        category="storage",
        target_type="disk",
        fault_family="hang",
        intensity="high",
        expected_signal="pod_unready",
        description=(
            "Unbound PersistentVolumeClaim or cross-zone volume attach failure stalls Pod startup."
        ),
        rollback_note=(
            "Restore StorageClass availability or attach a zone-aligned PersistentVolume."
        ),
    ),
    Entry(
        slug="ingress-backend-gateway-timeout",
        source_url="https://kubernetes.io/docs/concepts/services-networking/ingress/",
        source_section="the-ingress-resource",
        category="traffic",
        target_type="ingress",
        fault_family="delay",
        intensity="high",
        expected_signal="gateway_latency",
        description=(
            "Slow upstream Pod response across Ingress routing rules elevates "
            "gateway first-byte latency."
        ),
        rollback_note=(
            "Restore upstream service response latency or roll back the Ingress backend route."
        ),
    ),
    Entry(
        slug="configmap-drift-rollout-regression",
        source_url="https://kubernetes.io/docs/concepts/configuration/configmap/",
        source_section="using-configmaps",
        category="state",
        target_type="pod",
        fault_family="corrupt",
        intensity="mild",
        expected_signal="config_drift",
        description=(
            "Out-of-band ConfigMap mutation introduces runtime configuration drift "
            "from declared manifests."
        ),
        rollback_note=(
            "Reconcile the ConfigMap with the declared GitOps revision and restart affected Pods."
        ),
    ),
    Entry(
        slug="container-abnormal-exit-entrypoint",
        source_url=(
            "https://kubernetes.io/docs/tasks/debug/debug-application/determine-reason-pod-failure/"
        ),
        source_section="writing-and-reading-a-termination-message",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_abnormal_termination",
        description=(
            "Invalid container entrypoint or command causes immediate non-zero exit "
            "upon container start."
        ),
        rollback_note="Restore the verified container command and arguments in the Pod template.",
    ),
)


def _validate_entry(entry: Entry) -> None:
    if not _SLUG_PATTERN.fullmatch(entry.slug):
        raise ValueError("invalid_slug")
    if not entry.source_url.startswith(_SOURCE_PREFIX):
        raise ValueError("unsupported_source_url")
    if not entry.source_section.strip():
        raise ValueError("missing_source_section")
    if entry.category not in _ALLOWED_CATEGORIES:
        raise ValueError("unsupported_category")
    if entry.target_type not in _ALLOWED_TARGET_TYPES:
        raise ValueError("unsupported_target_type")
    if entry.fault_family not in _ALLOWED_FAULT_FAMILIES:
        raise ValueError("unsupported_fault_family")
    if entry.intensity not in _ALLOWED_INTENSITIES:
        raise ValueError("unsupported_intensity")
    if not entry.description.strip() or not entry.rollback_note.strip():
        raise ValueError("missing_description_or_rollback_note")
    signal = known_signals().get(entry.expected_signal)
    if signal is None:
        raise ValueError("unknown_expected_signal")
    if signal.role is SignalRole.RCA_ONLY:
        raise ValueError("rca_only_signal_not_scenario_eligible")


def _to_body(entry: Entry) -> dict[str, object]:
    _validate_entry(entry)
    return {
        "id": f"chaos.kubernetes-docs.{entry.slug}",
        "version": 1,
        "provenance": {
            "source": "vendor-doc",
            "source_url": entry.source_url,
            "source_ref": (
                f"section={entry.source_section};license={_SOURCE_LICENSE};reviewed={_REVIEWED_AT}"
            ),
            "synthesis_method": "manual",
        },
        "category": entry.category,
        "target_type": entry.target_type,
        "fault_family": entry.fault_family,
        "intensity": entry.intensity,
        "duration_seconds": 360,
        "expected_signal": entry.expected_signal,
        "injector": "needs-injector",
        "blast_radius_cap": 1,
        "rollback_note": entry.rollback_note,
        "gates": {"shadow_status": "pending", "enforce_status": None},
        "requires_hardware": False,
        "description": entry.description,
        "tags": ["kubernetes", "vendor-doc"],
    }


def main() -> int:
    slugs = [entry.slug for entry in _ENTRIES]
    if len(slugs) != len(set(slugs)):
        raise ValueError("duplicate_slug")
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    valid_names = {f"{entry.slug}.yaml" for entry in _ENTRIES}
    for existing in _OUT_DIR.glob("*.yaml"):
        if existing.name not in valid_names:
            existing.unlink()
    for entry in _ENTRIES:
        path = _OUT_DIR / f"{entry.slug}.yaml"
        path.write_text(yaml.safe_dump(_to_body(entry), sort_keys=False))
    print(f"wrote {len(_ENTRIES)} Kubernetes docs scenarios -> {_OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
