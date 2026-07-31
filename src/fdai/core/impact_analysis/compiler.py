"""Compile a complete affected set into an immutable impact envelope."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fdai.core.impact_analysis.models import (
    AffectedSet,
    ImpactEnvelopeRecord,
    ObjectiveBound,
    TelemetryRequirements,
)


def compile_impact_envelope(
    *,
    decision_case_id: str,
    affected_set: AffectedSet,
    action_type_cap: int,
    decision_cap: int,
    max_dependency_depth: int,
    max_duration_seconds: int,
    objective_bounds: tuple[ObjectiveBound, ...],
    required_signals: tuple[str, ...],
    forbidden_signals: tuple[str, ...],
    telemetry_requirements: TelemetryRequirements,
    uncertainty: float,
    expires_at: datetime,
) -> ImpactEnvelopeRecord:
    if not decision_case_id.strip():
        raise ValueError("decision_case_id MUST be non-empty")
    if not affected_set.complete:
        raise ValueError("impact envelope requires a complete affected set")
    if action_type_cap < 1 or decision_cap < 1:
        raise ValueError("impact caps MUST be positive")
    effective_cap = min(action_type_cap, decision_cap)
    affected = affected_set.all_resource_ids
    if len(affected) > effective_cap:
        raise ValueError("affected resources exceed the effective impact cap")
    targets_digest = _digest(affected_set.direct_targets)
    affected_digest = _digest(affected)
    identity = _digest(
        (
            decision_case_id,
            affected_set.graph_revision,
            targets_digest,
            affected_digest,
            str(max_duration_seconds),
        )
    )
    return ImpactEnvelopeRecord(
        envelope_id=f"impact-{identity[:32]}",
        decision_case_id=decision_case_id,
        graph_revision=affected_set.graph_revision,
        target_set_digest=targets_digest,
        affected_set_digest=affected_digest,
        direct_target_ids=affected_set.direct_targets,
        affected_resource_ids=affected,
        protected_objective_ids=affected_set.protected_objectives,
        max_affected_resources=effective_cap,
        max_dependency_depth=max_dependency_depth,
        max_duration_seconds=max_duration_seconds,
        objective_bounds=objective_bounds,
        required_signals=tuple(sorted(set(required_signals))),
        forbidden_signals=tuple(sorted(set(forbidden_signals))),
        telemetry_requirements=telemetry_requirements,
        uncertainty=uncertainty,
        expires_at=expires_at,
    )


def _digest(values: tuple[str, ...]) -> str:
    encoded = json.dumps(sorted(values), separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["compile_impact_envelope"]
