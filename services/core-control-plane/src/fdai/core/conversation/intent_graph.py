"""Deterministic intent graph and execution-evidence production."""

from __future__ import annotations

from typing import Literal

from fdai_service_contracts.ontology_query import (
    MAX_INTENT_GRAPH_GOALS,
    AnswerEvidenceMode,
    EvidenceAuthority,
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


def build_intent_graph(
    *,
    frame: SemanticProblemFrame,
    plan: OntologyQueryPlan,
    confidence: float,
) -> IntentGraph:
    """Build one replay-stable presentation graph from a verified query DAG."""

    if len(plan.nodes) > MAX_INTENT_GRAPH_GOALS:
        raise ValueError(f"conversation intent graph exceeds {MAX_INTENT_GRAPH_GOALS} goals")
    goal_ids = {node.node_id: f"goal-{index}" for index, node in enumerate(plan.nodes, start=1)}
    freshness: dict[str, bool] = {}
    goals: list[IntentGoal] = []
    source_kinds = {
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        QueryNodeKind.FUNCTION,
        QueryNodeKind.TOPOLOGY_AT,
        QueryNodeKind.TOPOLOGY_DIFF,
        QueryNodeKind.METRIC_SERIES,
        QueryNodeKind.METRIC_SCOPE_SERIES,
        QueryNodeKind.METRIC_COMPARISON,
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
    frame: SemanticProblemFrame | None = None,
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
    _authority, authority_status = resolve_execution_authority(
        execution,
        frame=frame,
        plan=plan,
    )
    if execution.status == "completed" and authority_status == "verified":
        status = "completed"
        mode = AnswerEvidenceMode.OPERATIONAL_GROUNDED
    elif execution.status == "completed":
        status = "failed"
        mode = AnswerEvidenceMode.HELD_FOR_REVIEW
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


def resolve_execution_authority(
    execution: QueryPlanExecution,
    *,
    frame: SemanticProblemFrame | None = None,
    plan: OntologyQueryPlan | None = None,
) -> tuple[EvidenceAuthority | None, Literal["verified", "missing", "conflict"]]:
    output_task_ids = {f"query:{node_id}" for node_id in execution.output_node_ids}
    evidence_receipts = tuple(
        receipt
        for receipt in execution.receipts
        if receipt.task_id in output_task_ids
        and receipt.status is TaskStatus.COMPLETED
        and receipt.evidence_refs
    )
    if not evidence_receipts or any(receipt.authority is None for receipt in evidence_receipts):
        return None, "missing"
    if frame is not None and frame.output_shape == "resource_condition_sections":
        if _permits_resource_condition_authorities(
            evidence_receipts,
            frame=frame,
            plan=plan,
        ):
            return None, "verified"
        return None, "conflict"
    authorities = {receipt.authority for receipt in evidence_receipts}
    if len(authorities) != 1:
        return None, "conflict"
    return next(iter(authorities)), "verified"


def _permits_resource_condition_authorities(
    evidence_receipts: tuple[GoalTaskReceipt, ...],
    *,
    frame: SemanticProblemFrame | None,
    plan: OntologyQueryPlan | None,
) -> bool:
    if (
        frame is None
        or plan is None
        or frame.output_shape != "resource_condition_sections"
        or len(plan.nodes) != 3
        or len(plan.output_node_ids) != 2
    ):
        return False
    by_id = {node.node_id: node for node in plan.nodes}
    output_nodes = tuple(by_id.get(node_id) for node_id in plan.output_node_ids)
    if any(node is None or node.kind is not QueryNodeKind.FUNCTION for node in output_nodes):
        return False
    expected_by_task: dict[str, EvidenceAuthority] = {}
    for node in output_nodes:
        if node is None:
            return False
        function_name = node.arguments.get("function_name")
        if not isinstance(function_name, str):
            return False
        expected_authority = {
            "query.resource_health_inventory": EvidenceAuthority.SERVER_RESOURCE_HEALTH,
            "query.resource_state_inventory": EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        }.get(function_name)
        if expected_authority is None:
            return False
        expected_by_task[f"query:{node.node_id}"] = expected_authority
    if set(expected_by_task.values()) != {
        EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        EvidenceAuthority.SERVER_RESOURCE_HEALTH,
    }:
        return False
    receipts_by_task = {receipt.task_id: receipt for receipt in evidence_receipts}
    if set(receipts_by_task) != set(expected_by_task):
        return False
    if any(
        receipts_by_task[task_id].authority is not authority
        for task_id, authority in expected_by_task.items()
    ):
        return False
    scope_nodes = tuple(node for node in plan.nodes if node.kind is QueryNodeKind.OBJECT_SET)
    return len(scope_nodes) == 1 and all(
        node is not None and node.depends_on == (scope_nodes[0].node_id,) for node in output_nodes
    )


__all__ = [
    "build_intent_graph",
    "build_intent_graph_evidence",
    "resolve_execution_authority",
]
