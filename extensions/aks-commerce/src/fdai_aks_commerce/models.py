"""Bounded evidence inputs for the deterministic commerce assessment."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from fdai_service_contracts import (
    AksCommerceEvidenceState,
    AksCommerceMetric,
    AksCommerceSlo,
    AksCommerceWorkload,
)


@dataclass(frozen=True, slots=True)
class AksCommerceEvidenceFrame:
    """One exact observation window across business and resource evidence."""

    service_id: Literal["catalog-browse", "order-fulfillment"]
    observed_at: datetime
    window_start: datetime
    window_end: datetime
    dependency_path: tuple[str, ...]
    workloads: tuple[AksCommerceWorkload, ...]
    slos: tuple[AksCommerceSlo, ...]
    metrics: tuple[AksCommerceMetric, ...]
    evidence_refs: tuple[str, ...]
    evidence_gaps: tuple[str, ...] = ()
    deployment_changed: bool = False
    rollout_stalled: bool = False
    order_store_pressure: bool = False
    prior_degraded: bool = False
    synthetic: bool = False

    def __post_init__(self) -> None:
        if self.service_id not in {"catalog-browse", "order-fulfillment"}:
            raise ValueError("AKS commerce service_id is unsupported")
        times = (self.observed_at, self.window_start, self.window_end)
        if any(value.tzinfo is None or value.utcoffset() is None for value in times):
            raise ValueError("AKS commerce evidence times must be timezone-aware")
        if not self.window_start < self.window_end <= self.observed_at:
            raise ValueError("AKS commerce evidence window is invalid")
        if not self.dependency_path or len(self.dependency_path) > 16:
            raise ValueError("AKS commerce dependency path must contain 1 to 16 workloads")
        if len(set(self.dependency_path)) != len(self.dependency_path):
            raise ValueError("AKS commerce dependency path must not contain cycles")
        if not self.workloads or len(self.workloads) > 16:
            raise ValueError("AKS commerce workloads must contain 1 to 16 items")
        if not self.slos or len(self.slos) > 8:
            raise ValueError("AKS commerce SLO evidence must contain 1 to 8 items")
        if len(self.metrics) > 32 or len(self.evidence_refs) > 64:
            raise ValueError("AKS commerce evidence exceeds its bounds")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("AKS commerce evidence refs must be unique")
        if len(self.evidence_gaps) > 32 or len(set(self.evidence_gaps)) != len(self.evidence_gaps):
            raise ValueError("AKS commerce evidence gaps must be bounded and unique")

    def metric(self, name: str) -> AksCommerceMetric | None:
        """Return one uniquely named metric or fail on conflicting inputs."""

        matches = tuple(metric for metric in self.metrics if metric.name == name)
        if len(matches) > 1:
            raise ValueError(f"AKS commerce metric {name!r} is duplicated")
        return matches[0] if matches else None

    @property
    def derived_gaps(self) -> tuple[str, ...]:
        """Return explicit and qualification-derived evidence gaps."""

        gaps = list(self.evidence_gaps)
        if any(
            workload.evidence_state is not AksCommerceEvidenceState.COMPLETE
            for workload in self.workloads
        ):
            gaps.append("workload_evidence_incomplete")
        if any(slo.state is not AksCommerceEvidenceState.COMPLETE for slo in self.slos):
            gaps.append("slo_evidence_incomplete")
        if any(metric.state is not AksCommerceEvidenceState.COMPLETE for metric in self.metrics):
            gaps.append("metric_evidence_incomplete")
        return tuple(dict.fromkeys(gaps))


@dataclass(frozen=True, slots=True)
class AksCommerceAssessmentPolicy:
    """Reviewed thresholds applied to already normalized observations."""

    backlog_growth_minimum: float = 1.0
    dead_letter_growth_minimum: float = 1.0
    catalog_availability_metric: str = "synthetic.catalog.availability"
    active_messages_metric: str = "stream.active_messages"
    incoming_messages_metric: str = "stream.incoming_messages"
    completed_messages_metric: str = "stream.completed_messages"
    dead_letter_messages_metric: str = "stream.dead_letter_messages"
    required_metrics: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "catalog-browse": ("synthetic.catalog.availability",),
            "order-fulfillment": (
                "synthetic.order.availability",
                "stream.active_messages",
                "stream.incoming_messages",
                "stream.completed_messages",
                "stream.dead_letter_messages",
            ),
        }
    )

    def __post_init__(self) -> None:
        if self.backlog_growth_minimum <= 0 or self.dead_letter_growth_minimum <= 0:
            raise ValueError("AKS commerce growth thresholds must be positive")
