"""Contract tests for ontology-grounded operator query records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts.ontology_query import (
    GoalEvidenceMode,
    GoalTaskReceipt,
    IntentGoal,
    IntentGraph,
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
    StructuralCoverageReceipt,
    TaskStatus,
    canonical_json,
    content_digest,
)
from pydantic import ValidationError

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)


def _frame() -> SemanticProblemFrame:
    temporal = {"baseline": {"days": 7}, "current": {"days": 7}}
    payload = {
        "schema_version": "1.0.0",
        "operation": "explain_change",
        "subject_constraints": ("interface.observable",),
        "measure_concepts": ("request.volume",),
        "temporal_scope": temporal,
        "output_shape": "ranked_hypotheses",
        "evidence_requirements": ("complete_metric_windows",),
        "unresolved_terms": (),
        "input_digest": DIGEST_A,
        "authority": "candidate_only",
        "execution_authority": False,
    }
    return SemanticProblemFrame(
        operation=SemanticOperation.EXPLAIN_CHANGE,
        subject_constraints=("interface.observable",),
        measure_concepts=("request.volume",),
        temporal_scope_json=canonical_json(temporal),
        output_shape="ranked_hypotheses",
        evidence_requirements=("complete_metric_windows",),
        input_digest=DIGEST_A,
        frame_digest=content_digest(payload),
    )


def _plan(frame: SemanticProblemFrame) -> OntologyQueryPlan:
    nodes = (
        OntologyQueryNode(
            node_id="services",
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json(
                {"selector": {"kind": "interface", "name": "Observable"}}
            ),
            output_kind="object_set",
        ),
        OntologyQueryNode(
            node_id="request_series",
            kind=QueryNodeKind.METRIC_SERIES,
            depends_on=("services",),
            arguments_json=canonical_json({"metric_concept": "request.volume"}),
            output_kind="metric_series",
        ),
    )
    payload = {
        "schema_version": "1.0.0",
        "ontology_release_digest": DIGEST_A,
        "semantic_catalog_digest": DIGEST_B,
        "problem_frame_digest": frame.frame_digest,
        "purpose": "incident-investigation",
        "caller_role": "Reader",
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "output_node_ids": ("request_series",),
        "execution_authority": False,
    }
    return OntologyQueryPlan(
        ontology_release_digest=DIGEST_A,
        semantic_catalog_digest=DIGEST_B,
        problem_frame_digest=frame.frame_digest,
        purpose="incident-investigation",
        caller_role="Reader",
        nodes=nodes,
        output_node_ids=("request_series",),
        plan_digest=content_digest(payload),
    )


def test_problem_frame_and_plan_are_replay_stable_and_no_authority() -> None:
    frame = _frame()
    plan = _plan(frame)

    assert frame.temporal_scope["baseline"] == {"days": 7}
    assert frame.execution_authority is False
    assert plan.nodes[1].arguments == {"metric_concept": "request.volume"}
    assert plan.execution_authority is False
    assert OntologyQueryPlan.model_validate_json(plan.model_dump_json()) == plan


def test_frame_rejects_noncanonical_json_and_digest_mismatch() -> None:
    frame = _frame()
    values = frame.model_dump()
    values["temporal_scope_json"] = '{"current": {"days": 7}}'
    with pytest.raises(ValidationError, match="canonical JSON"):
        SemanticProblemFrame.model_validate(values)

    values = frame.model_dump()
    values["frame_digest"] = DIGEST_B
    with pytest.raises(ValidationError, match="digest"):
        SemanticProblemFrame.model_validate(values)


def test_plan_rejects_forward_dependency_unknown_output_and_digest_drift() -> None:
    frame = _frame()
    plan = _plan(frame)
    first, second = plan.nodes

    with pytest.raises(ValidationError, match="dependencies MUST precede"):
        OntologyQueryPlan.model_validate({**plan.model_dump(), "nodes": (second, first)})
    with pytest.raises(ValidationError, match="unknown output"):
        OntologyQueryPlan.model_validate({**plan.model_dump(), "output_node_ids": ("missing",)})
    with pytest.raises(ValidationError, match="digest"):
        OntologyQueryPlan.model_validate({**plan.model_dump(), "plan_digest": DIGEST_A})


def test_intent_graph_and_task_receipt_preserve_dependencies_and_times() -> None:
    frame = _frame()
    plan = _plan(frame)
    goal = IntentGoal(
        goal_id="request_series",
        intent="explain_change",
        capability="query.metric_series",
        arguments_json=canonical_json({"metric_concept": "request.volume"}),
        evidence_mode=GoalEvidenceMode.OPERATIONAL,
        freshness_required=True,
        confidence=0.9,
    )
    graph = IntentGraph(
        problem_frame_digest=frame.frame_digest,
        plan_digest=plan.plan_digest,
        goals=(goal,),
        confidence=0.9,
        action_posture="advise_only",
    )
    receipt = GoalTaskReceipt(
        task_id="request-1:request_series",
        goal_id=goal.goal_id,
        intent=goal.intent,
        capability=goal.capability,
        evidence_mode=goal.evidence_mode,
        status=TaskStatus.COMPLETED,
        duration_ms=10,
        evidence_refs=("metric-receipt:1",),
        started_at=NOW,
        completed_at=NOW + timedelta(milliseconds=10),
    )

    assert graph.goals == (goal,)
    assert receipt.completed_at > receipt.started_at

    with pytest.raises(ValidationError, match="blocked_by"):
        GoalTaskReceipt.model_validate(
            {**receipt.model_dump(), "status": "skipped", "blocked_by": ()}
        )


def test_structural_coverage_receipt_requires_accounted_declarations() -> None:
    payload = {
        "schema_version": "1.0.0",
        "ontology_release_digest": DIGEST_A,
        "principal_scope_digest": DIGEST_B,
        "readable_declaration_count": 3,
        "descriptor_count": 2,
        "unavailable_declaration_ids": ("function:query.example",),
        "manifest_digest": DIGEST_A,
        "complete": True,
    }
    receipt = StructuralCoverageReceipt(
        **payload,
        receipt_digest=content_digest(payload),
    )
    assert receipt.complete is True

    with pytest.raises(ValidationError, match="complete flag"):
        StructuralCoverageReceipt.model_validate(
            {
                **receipt.model_dump(),
                "unavailable_declaration_ids": (),
                "complete": True,
            }
        )
