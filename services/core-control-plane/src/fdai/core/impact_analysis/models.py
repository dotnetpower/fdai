"""Immutable impact-analysis and envelope contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.shared.providers.ontology_instance import OntologyObjectRecord


@dataclass(frozen=True, slots=True)
class ObjectiveBound:
    metric: str
    lower: float | None = None
    upper: float | None = None
    window_seconds: int = 300

    def __post_init__(self) -> None:
        if not self.metric.strip():
            raise ValueError("ObjectiveBound.metric MUST be non-empty")
        if self.lower is None and self.upper is None:
            raise ValueError("ObjectiveBound requires a lower or upper bound")
        for value in (self.lower, self.upper):
            if value is not None and not math.isfinite(value):
                raise ValueError("ObjectiveBound values MUST be finite")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("ObjectiveBound.lower MUST be <= upper")
        if self.window_seconds < 1:
            raise ValueError("ObjectiveBound.window_seconds MUST be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "lower": self.lower,
            "upper": self.upper,
            "window_seconds": self.window_seconds,
        }


@dataclass(frozen=True, slots=True)
class TelemetryRequirements:
    required_sources: tuple[str, ...]
    freshness_seconds: int
    cadence_seconds: int

    def __post_init__(self) -> None:
        if not self.required_sources or any(not item.strip() for item in self.required_sources):
            raise ValueError("TelemetryRequirements.required_sources MUST be non-empty")
        if self.freshness_seconds < 1 or self.cadence_seconds < 1:
            raise ValueError("telemetry freshness and cadence MUST be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "required_sources": list(self.required_sources),
            "freshness_seconds": self.freshness_seconds,
            "cadence_seconds": self.cadence_seconds,
        }


@dataclass(frozen=True, slots=True)
class AffectedSet:
    direct_targets: tuple[str, ...]
    runtime_dependents: tuple[str, ...]
    protected_services: tuple[str, ...]
    protected_objectives: tuple[str, ...]
    control_dependencies: tuple[str, ...]
    graph_revision: str
    truncated: bool = False
    incomplete_reasons: tuple[str, ...] = ()

    @property
    def all_resource_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                set(
                    (
                        *self.direct_targets,
                        *self.runtime_dependents,
                        *self.control_dependencies,
                    )
                )
            )
        )

    @property
    def complete(self) -> bool:
        return not self.truncated and not self.incomplete_reasons


@dataclass(frozen=True, slots=True)
class ImpactEnvelopeRecord:
    envelope_id: str
    decision_case_id: str
    graph_revision: str
    target_set_digest: str
    affected_set_digest: str
    direct_target_ids: tuple[str, ...]
    affected_resource_ids: tuple[str, ...]
    protected_objective_ids: tuple[str, ...]
    max_affected_resources: int
    max_dependency_depth: int
    max_duration_seconds: int
    objective_bounds: tuple[ObjectiveBound, ...]
    required_signals: tuple[str, ...]
    forbidden_signals: tuple[str, ...]
    telemetry_requirements: TelemetryRequirements
    uncertainty: float
    expires_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("envelope_id", self.envelope_id),
            ("decision_case_id", self.decision_case_id),
            ("graph_revision", self.graph_revision),
            ("target_set_digest", self.target_set_digest),
            ("affected_set_digest", self.affected_set_digest),
        ):
            if not value.strip():
                raise ValueError(f"{name} MUST be non-empty")
        if not self.direct_target_ids or not self.affected_resource_ids:
            raise ValueError("impact envelope target sets MUST be non-empty")
        if not set(self.direct_target_ids) <= set(self.affected_resource_ids):
            raise ValueError("direct targets MUST be included in affected resources")
        if len(self.affected_resource_ids) > self.max_affected_resources:
            raise ValueError("affected resources exceed the envelope cap")
        if not 1 <= self.max_dependency_depth <= 5:
            raise ValueError("max_dependency_depth MUST be in [1, 5]")
        if self.max_duration_seconds < 1:
            raise ValueError("max_duration_seconds MUST be positive")
        if not math.isfinite(self.uncertainty) or not 0.0 <= self.uncertainty <= 1.0:
            raise ValueError("uncertainty MUST be finite and in [0, 1]")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at MUST be timezone-aware")
        if set(self.required_signals) & set(self.forbidden_signals):
            raise ValueError("a signal cannot be both required and forbidden")

    def to_ontology_object(self) -> OntologyObjectRecord:
        objective_bounds: dict[str, Any] = {
            item.metric: item.to_dict() for item in self.objective_bounds
        }
        return OntologyObjectRecord(
            id=self.envelope_id,
            object_type="ImpactEnvelope",
            properties={
                "id": self.envelope_id,
                "decision_case_id": self.decision_case_id,
                "graph_revision": self.graph_revision,
                "target_set_digest": self.target_set_digest,
                "affected_set_digest": self.affected_set_digest,
                "max_affected_resources": self.max_affected_resources,
                "max_dependency_depth": self.max_dependency_depth,
                "max_duration_seconds": self.max_duration_seconds,
                "objective_bounds": objective_bounds,
                "required_signals": list(self.required_signals),
                "forbidden_signals": list(self.forbidden_signals),
                "telemetry_requirements": self.telemetry_requirements.to_dict(),
                "uncertainty": self.uncertainty,
                "expires_at": self.expires_at,
            },
        )


__all__ = [
    "AffectedSet",
    "ImpactEnvelopeRecord",
    "ObjectiveBound",
    "TelemetryRequirements",
]
