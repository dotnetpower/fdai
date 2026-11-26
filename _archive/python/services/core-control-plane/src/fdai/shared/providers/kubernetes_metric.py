"""CSP-neutral exact-target Kubernetes metric evidence contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from fdai.shared.providers.metric import MetricPoint

KUBERNETES_DIAGNOSTIC_METRICS: Final[frozenset[str]] = frozenset(
    {
        "kubernetes.container.cpu.usage",
        "kubernetes.container.cpu.throttled_seconds",
        "kubernetes.container.filesystem.usage_bytes",
        "kubernetes.container.memory.working_set_bytes",
        "kubernetes.container.network.receive_bytes",
        "kubernetes.container.network.transmit_bytes",
        "kubernetes.container.oom_events",
        "kubernetes.node.allocatable.cpu",
        "kubernetes.node.allocatable.memory_bytes",
        "kubernetes.node.pressure",
        "kubernetes.pod.request.cpu",
        "kubernetes.pod.request.memory_bytes",
    }
)


@dataclass(frozen=True, slots=True)
class KubernetesMetricTarget:
    """Exact Kubernetes metric subject."""

    cluster_ref: str
    uid: str
    namespace: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("cluster_ref", "uid"):
            value = getattr(self, field_name)
            if not value.strip() or len(value) > 512:
                raise ValueError(f"Kubernetes metric {field_name} MUST be bounded non-empty text")
        if self.namespace is not None and (not self.namespace.strip() or len(self.namespace) > 253):
            raise ValueError("Kubernetes metric namespace MUST be bounded non-empty text or null")


@dataclass(frozen=True, slots=True)
class KubernetesMetricWindowEvidence:
    """Validated metric candidates plus independent window-coverage state."""

    metric_name: str
    target: KubernetesMetricTarget
    start: datetime
    end: datetime
    points: tuple[MetricPoint, ...]
    source_identity: str
    source_revision: str
    provider_cutoff: datetime | None
    coverage_receipt_ref: str | None
    complete: bool
    limitation: str | None

    def __post_init__(self) -> None:
        if self.metric_name not in KUBERNETES_DIAGNOSTIC_METRICS:
            raise ValueError("Kubernetes diagnostic metric name is not reviewed")
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start >= self.end:
            raise ValueError("Kubernetes metric window MUST be aware and positive")
        if not self.source_identity.strip() or not self.source_revision.strip():
            raise ValueError("Kubernetes metric source identity and revision are required")
        if len(self.points) > 20:
            raise ValueError("Kubernetes metric evidence exceeds its point bound")
        if self.provider_cutoff is not None and self.provider_cutoff.tzinfo is None:
            raise ValueError("Kubernetes metric provider cutoff MUST be timezone-aware")
        if self.complete != (self.limitation is None):
            raise ValueError("Kubernetes metric completeness and limitation are inconsistent")
        if self.complete and (self.provider_cutoff is None or self.coverage_receipt_ref is None):
            raise ValueError("complete Kubernetes metrics require provider cutoff and coverage")
        if self.complete and self.provider_cutoff is not None and self.provider_cutoff < self.end:
            raise ValueError("complete Kubernetes metrics require cutoff through the window end")


__all__ = [
    "KUBERNETES_DIAGNOSTIC_METRICS",
    "KubernetesMetricTarget",
    "KubernetesMetricWindowEvidence",
]
