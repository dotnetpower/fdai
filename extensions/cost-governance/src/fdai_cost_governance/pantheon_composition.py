"""Compose authority-free Njord candidate payloads from coupled optimization plans."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fdai.core.decision_case import ObjectiveEffect
from fdai.core.operational_context import SourceFreshness

from fdai_cost_governance.guard import FinOpsActionKind
from fdai_cost_governance.optimization import (
    CoupledResourceOptimizationPlan,
    OptimizationDisposition,
)

_RIGHT_SIZE_ACTION_TYPE = "remediate.right-size"
_MAX_COUPLED_CANDIDATES = 20
_MAX_EVIDENCE_REFS = 32


def compose_njord_optimization_candidate(
    plan: CoupledResourceOptimizationPlan,
    *,
    correlation_id: str,
    observed_at: datetime,
    cost_objective_id: str,
    effects: tuple[ObjectiveEffect, ...],
    evidence_refs: tuple[str, ...],
    source_freshness: tuple[SourceFreshness, ...],
) -> dict[str, Any]:
    """Return one Njord-owned payload for Forseti's existing candidate intake.

    This function grants no publication authority. Njord remains the only principal
    allowed to publish the returned payload on ``object.cost-anomaly``.
    """

    if plan.disposition is not OptimizationDisposition.CANDIDATE:
        raise ValueError("cost optimization plan MUST be an eligible candidate")
    if plan.execution_authority or not plan.approval_required or plan.route != "risk_gate":
        raise ValueError("cost optimization plan authority boundary is invalid")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("cost optimization candidate time MUST be timezone-aware")
    if not correlation_id.strip() or correlation_id != correlation_id.strip():
        raise ValueError("cost optimization correlation_id MUST be exact")
    if not cost_objective_id.strip() or cost_objective_id != cost_objective_id.strip():
        raise ValueError("cost optimization objective id MUST be exact")
    if not 1 < len(plan.candidates) <= _MAX_COUPLED_CANDIDATES or len(plan.profile_digests) != len(
        plan.candidates
    ):
        raise ValueError("cost optimization candidate lineage is incomplete")
    action_ids = tuple(candidate.action_id for candidate in plan.candidates)
    if len(action_ids) != len(set(action_ids)):
        raise ValueError("cost optimization candidates MUST have unique action ids")
    _require_sha256("cost optimization target revision", plan.target_revision_digest)
    for digest in plan.profile_digests:
        _require_sha256("cost optimization profile", digest)
    if {candidate.kind for candidate in plan.candidates} != {FinOpsActionKind.RIGHT_SIZE}:
        raise ValueError("cost optimization candidate has no shared ActionType mapping")
    if not effects:
        raise ValueError("cost optimization candidate MUST carry objective effects")
    objective_ids = tuple(effect.objective_id for effect in effects)
    if len(objective_ids) != len(set(objective_ids)):
        raise ValueError("cost optimization candidate effects MUST be unique by objective")
    cost_effect = next(
        (effect for effect in effects if effect.objective_id == cost_objective_id),
        None,
    )
    if cost_effect is None or cost_effect.utility <= 0:
        raise ValueError("cost optimization candidate MUST improve its cost objective")
    if not source_freshness:
        raise ValueError("cost optimization candidate MUST carry source freshness")
    if any(item.observed_at > observed_at for item in source_freshness):
        raise ValueError("cost optimization source evidence is from the future")

    lineage = tuple(
        dict.fromkeys(
            (
                f"optimization-target-revision:{plan.target_revision_digest}",
                *(
                    f"optimization-candidate:{candidate.action_id}:profile:{profile_digest}"
                    for candidate, profile_digest in zip(
                        plan.candidates, plan.profile_digests, strict=True
                    )
                ),
                *evidence_refs,
            )
        )
    )
    if len(lineage) > _MAX_EVIDENCE_REFS:
        raise ValueError("cost optimization evidence refs exceed the intake limit")
    if any(not item.strip() or item != item.strip() or len(item) > 512 for item in lineage):
        raise ValueError("cost optimization evidence refs MUST be bounded exact text")
    return {
        "kind": "cross_vertical_candidate",
        "correlation_id": correlation_id,
        "idempotency_key": plan.idempotency_key,
        "resource_id": plan.target_set_id,
        "observed_at": observed_at.isoformat(),
        "action_type": _RIGHT_SIZE_ACTION_TYPE,
        "effects": [_effect_mapping(effect) for effect in effects],
        "evidence_refs": list(lineage),
        "source_freshness": [
            {
                "source": item.source,
                "observed_at": item.observed_at.isoformat(),
                "max_age_seconds": item.max_age_seconds,
            }
            for item in source_freshness
        ],
    }


def _effect_mapping(effect: ObjectiveEffect) -> dict[str, object]:
    return {
        "objective_id": effect.objective_id,
        "utility": effect.utility,
        "confidence": effect.confidence,
        "metric": effect.metric,
        "expected_min": effect.expected_min,
        "expected_max": effect.expected_max,
        "observation_window_seconds": effect.observation_window_seconds,
    }


def _require_sha256(label: str, value: str) -> None:
    if (
        not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{label} MUST be an exact SHA-256 digest")


__all__ = ["compose_njord_optimization_candidate"]
