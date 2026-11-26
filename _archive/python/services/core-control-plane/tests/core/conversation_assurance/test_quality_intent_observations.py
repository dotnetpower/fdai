from __future__ import annotations

import hashlib

from fdai.core.conversation.semantic_planning_models import (
    SemanticPlanningDisposition,
    SemanticPlanningOutcome,
)
from fdai.core.conversation_assurance.quality_intent_observations import (
    IntentPlanningScenarioResult,
    observe_intent_planning,
    plan_shape_digest,
)
from fdai_service_contracts.ontology_query import (
    IntentGraph,
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
)

_EVIDENCE = "a" * 64


def _planned() -> SemanticPlanningOutcome:
    frame = SemanticProblemFrame.model_construct(
        operation=SemanticOperation.SELECT,
        input_digest="sha256:" + "b" * 64,
    )
    node = OntologyQueryNode.model_construct(
        node_id="resources",
        kind=QueryNodeKind.OBJECT_SET,
        depends_on=(),
        output_kind="resource_set",
    )
    plan = OntologyQueryPlan.model_construct(
        nodes=(node,),
        output_node_ids=("resources",),
    )
    return SemanticPlanningOutcome(
        disposition=SemanticPlanningDisposition.PLANNED,
        reason="verified_plan",
        frame=frame,
        plan=plan,
        intent_graph=IntentGraph.model_construct(),
    )


def test_planned_outcome_measures_intent_context_and_plan_shape() -> None:
    actual = _planned()
    contributions = observe_intent_planning(
        IntentPlanningScenarioResult(
            case_id="en-case-1",
            expected_disposition=SemanticPlanningDisposition.PLANNED,
            expected_operation=SemanticOperation.SELECT,
            expected_ambiguous=False,
            expected_clarification_digest=None,
            expected_frame_input_digest="sha256:" + "b" * 64,
            expected_plan_shape_digest=plan_shape_digest(actual),
            actual=actual,
            evidence_digest=_EVIDENCE,
        )
    )
    assert [item.item_id for item in contributions] == [1, 2, 4, 5]
    assert all(item.value == 1.0 for item in contributions)


def test_clarification_measures_ambiguity_and_exact_question_commitment() -> None:
    question = "Which resource should I inspect?"
    actual = SemanticPlanningOutcome(
        disposition=SemanticPlanningDisposition.CLARIFICATION,
        reason="ambiguous_subject",
        clarification=question,
    )
    contributions = observe_intent_planning(
        IntentPlanningScenarioResult(
            case_id="en-case-1",
            expected_disposition=SemanticPlanningDisposition.CLARIFICATION,
            expected_operation=None,
            expected_ambiguous=True,
            expected_clarification_digest=hashlib.sha256(question.encode()).hexdigest(),
            expected_frame_input_digest=None,
            expected_plan_shape_digest=None,
            actual=actual,
            evidence_digest=_EVIDENCE,
        )
    )
    assert [item.item_id for item in contributions] == [1, 2, 3]
    assert all(item.value == 1.0 for item in contributions)


def test_mismatched_semantic_expectations_score_zero() -> None:
    actual = _planned()
    contributions = observe_intent_planning(
        IntentPlanningScenarioResult(
            case_id="en-case-1",
            expected_disposition=SemanticPlanningDisposition.CLARIFICATION,
            expected_operation=None,
            expected_ambiguous=True,
            expected_clarification_digest="c" * 64,
            expected_frame_input_digest="sha256:" + "d" * 64,
            expected_plan_shape_digest="e" * 64,
            actual=actual,
            evidence_digest=_EVIDENCE,
        )
    )
    assert all(item.value == 0.0 for item in contributions)
