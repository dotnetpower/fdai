"""Deterministic intent graph and execution-evidence production."""

from __future__ import annotations

from typing import Literal

from fdai_service_contracts.ontology_query import (
    AnswerEvidenceMode,
    GoalEvidenceMode,
    GoalTaskReceipt,
    IntentGoal,
    IntentGraph,
    IntentGraphEvidence,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticProblemFrame,
    TaskStatus,
)

from fdai.core.ontology_platform import QueryPlanExecution

_MAX_GRAPH_GOALS = 8


def build_intent_graph(
    *,
    frame: SemanticProblemFrame,
    plan: OntologyQueryPlan,
    confidence: float,
) -> IntentGraph:
    """Build one replay-stable presentation graph from a verified query DAG."""

    if len(plan.nodes) > _MAX_GRAPH_GOALS:
        raise ValueError(f"conversation intent graph exceeds {_MAX_GRAPH_GOALS} goals")
    goal_ids = {node.node_id: f"goal-{index}" for index, node in enumerate(plan.nodes, start=1)}
    freshness: dict[str, bool] = {}
    goals: list[IntentGoal] = []
    source_kinds = {
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
        QueryNodeKind.TOPOLOGY_AT,
        QueryNodeKind.TOPOLOGY_DIFF,
        QueryNodeKind.METRIC_SERIES,
        QueryNodeKind.EVIDENCE_JOIN,
    }
    for node in plan.nodes:
        goal_freshness = node.kind in source_kinds or any(
            freshness[dependency] for dependency in node.depends_on
        )
        freshness[node.node_id] = goal_freshness
        goals.append(
            IntentGoal(
                goal_id=goal_ids[node.node_id],
                intent=node.kind.value,
                capability=f"query.{node.kind.value}",
                arguments_json=node.arguments_json,
                depends_on=tuple(goal_ids[item] for item in node.depends_on),
                evidence_mode=GoalEvidenceMode.OPERATIONAL,
                freshness_required=goal_freshness,
                confidence=confidence,
            )
        )
    return IntentGraph(
        problem_frame_digest=frame.frame_digest,
        plan_digest=plan.plan_digest,
        goals=tuple(goals),
        confidence=confidence,
        action_posture="advise_only",
    )


def build_intent_graph_evidence(
    *,
    graph: IntentGraph,
    plan: OntologyQueryPlan,
    execution: QueryPlanExecution,
) -> IntentGraphEvidence:
    """Bind executor receipts to presentation goals without copying provider bodies."""

    if execution.plan_digest != plan.plan_digest or len(execution.receipts) != len(graph.goals):
        raise ValueError("query execution does not match intent graph")
    goal_ids = {
        node.node_id: goal.goal_id for node, goal in zip(plan.nodes, graph.goals, strict=True)
    }
    receipts: list[GoalTaskReceipt] = []
    for node, goal, receipt in zip(plan.nodes, graph.goals, execution.receipts, strict=True):
        if receipt.goal_id != node.node_id:
            raise ValueError("query task receipt order does not match plan")
        evidence_refs = receipt.evidence_refs[:12]
        reason = receipt.reason
        if len(receipt.evidence_refs) > len(evidence_refs):
            reason = (
                "evidence_refs_truncated" if reason is None else f"{reason}+evidence_refs_truncated"
            )
        receipts.append(
            GoalTaskReceipt.model_validate(
                {
                    **receipt.model_dump(),
                    "goal_id": goal.goal_id,
                    "intent": goal.intent,
                    "capability": goal.capability,
                    "depends_on": tuple(goal_ids[item] for item in node.depends_on),
                    "blocked_by": tuple(goal_ids[item] for item in receipt.blocked_by),
                    "evidence_refs": evidence_refs,
                    "reason": reason,
                }
            )
        )
    statuses = {receipt.status for receipt in receipts}
    status: Literal["completed", "partial", "unavailable", "failed", "cancelled"]
    if execution.status == "completed":
        status = "completed"
        mode = AnswerEvidenceMode.OPERATIONAL_GROUNDED
    elif execution.status == "cancelled":
        status = "cancelled"
        mode = AnswerEvidenceMode.HELD_FOR_REVIEW
    elif TaskStatus.COMPLETED in statuses:
        status = "partial"
        mode = AnswerEvidenceMode.PARTIAL
    elif TaskStatus.UNAVAILABLE in statuses:
        status = "unavailable"
        mode = AnswerEvidenceMode.HELD_FOR_REVIEW
    else:
        status = "failed"
        mode = AnswerEvidenceMode.HELD_FOR_REVIEW
    return IntentGraphEvidence(status=status, evidence_mode=mode, goals=tuple(receipts))


__all__ = ["build_intent_graph", "build_intent_graph_evidence"]
