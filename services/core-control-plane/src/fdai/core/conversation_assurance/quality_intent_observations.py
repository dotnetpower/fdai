"""Qualification contributions from verified semantic planning outcomes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from fdai_service_contracts.ontology_query import SemanticOperation

from fdai.core.conversation.semantic_planning_models import (
    SemanticPlanningDisposition,
    SemanticPlanningOutcome,
)
from fdai.core.conversation_assurance.quality_observation_models import (
    QualificationDimensionContribution,
)
from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
)


@dataclass(frozen=True, slots=True)
class IntentPlanningScenarioResult:
    case_id: str
    expected_disposition: SemanticPlanningDisposition
    expected_operation: SemanticOperation | None
    expected_ambiguous: bool
    expected_clarification_digest: str | None
    expected_frame_input_digest: str | None
    expected_plan_shape_digest: str | None
    actual: SemanticPlanningOutcome
    evidence_digest: str


def observe_intent_planning(
    result: IntentPlanningScenarioResult,
) -> tuple[QualificationDimensionContribution, ...]:
    """Measure applicable items 1-5 from typed semantic output only."""

    _require_digest(result.evidence_digest, "scenario evidence_digest")
    actual_operation = None if result.actual.frame is None else result.actual.frame.operation
    contributions = [
        _contribution(
            result,
            item_id=1,
            correct=result.actual.disposition is result.expected_disposition
            and actual_operation is result.expected_operation,
            reason="semantic_disposition_and_operation_match",
        ),
        _contribution(
            result,
            item_id=2,
            correct=(result.actual.disposition is SemanticPlanningDisposition.CLARIFICATION)
            is result.expected_ambiguous,
            reason="ambiguity_disposition_match",
        ),
    ]
    if result.expected_clarification_digest is not None:
        _require_digest(
            result.expected_clarification_digest,
            "expected clarification digest",
        )
        actual_digest = (
            None
            if result.actual.clarification is None
            else hashlib.sha256(result.actual.clarification.encode()).hexdigest()
        )
        contributions.append(
            _contribution(
                result,
                item_id=3,
                correct=actual_digest == result.expected_clarification_digest,
                reason="clarification_commitment_match",
            )
        )
    if result.expected_frame_input_digest is not None:
        if not result.expected_frame_input_digest.startswith("sha256:"):
            raise ValueError("expected frame input digest MUST use sha256:")
        contributions.append(
            _contribution(
                result,
                item_id=4,
                correct=result.actual.frame is not None
                and result.actual.frame.input_digest == result.expected_frame_input_digest,
                reason="frame_context_binding_match",
            )
        )
    if result.expected_plan_shape_digest is not None:
        _require_digest(result.expected_plan_shape_digest, "expected plan shape digest")
        contributions.append(
            _contribution(
                result,
                item_id=5,
                correct=_plan_shape_digest(result.actual) == result.expected_plan_shape_digest,
                reason="compound_plan_shape_match",
            )
        )
    return tuple(contributions)


def plan_shape_digest(outcome: SemanticPlanningOutcome) -> str | None:
    """Return the content digest of one verified plan's DAG shape."""

    return _plan_shape_digest(outcome)


def _plan_shape_digest(outcome: SemanticPlanningOutcome) -> str | None:
    if outcome.plan is None:
        return None
    shape = {
        "nodes": [
            {
                "node_id": node.node_id,
                "kind": node.kind.value,
                "depends_on": list(node.depends_on),
                "output_kind": node.output_kind,
            }
            for node in outcome.plan.nodes
        ],
        "output_node_ids": list(outcome.plan.output_node_ids),
    }
    return _digest(shape)


def _contribution(
    result: IntentPlanningScenarioResult,
    *,
    item_id: int,
    correct: bool,
    reason: str,
) -> QualificationDimensionContribution:
    item = CHATOPS_QUALITY_CONTRACT_V1.items[item_id - 1]
    observed = {
        "disposition": result.actual.disposition.value,
        "reason_digest": hashlib.sha256(result.actual.reason.encode()).hexdigest(),
        "operation": (None if result.actual.frame is None else result.actual.frame.operation.value),
        "clarification_digest": (
            None
            if result.actual.clarification is None
            else hashlib.sha256(result.actual.clarification.encode()).hexdigest()
        ),
        "frame_input_digest": (
            None if result.actual.frame is None else result.actual.frame.input_digest
        ),
        "plan_shape_digest": _plan_shape_digest(result.actual),
    }
    return QualificationDimensionContribution(
        case_id=result.case_id,
        item_id=item_id,
        workstream=item.workstream,
        metric=item.metric,
        dimension=QualityDimension.FUNCTIONAL_CORRECTNESS,
        value=1.0 if correct else 0.0,
        reason_code=reason,
        evidence_ref_digests=(result.evidence_digest, _digest(observed)),
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _require_digest(value: str, field: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} MUST be a lowercase SHA-256 digest")


__all__ = [
    "IntentPlanningScenarioResult",
    "observe_intent_planning",
    "plan_shape_digest",
]
