"""V-SEM and V-PROV checks for reviewed comparison operators."""

from __future__ import annotations

from collections.abc import Sequence

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
)

from .semantic_reasoning_form import FormGoal, GoalOperation, MeasureKind


def comparison_operand_violations(node: OntologyQueryNode, goal: FormGoal) -> list[str]:
    if goal.effective_operation is not GoalOperation.COMPARE_WINDOWS:
        return [f"prov_unexpected_node:{node.node_id}:{node.kind.value}"]
    if goal.measure is None or goal.measure.kind is not MeasureKind.METRIC:
        return [f"prov_unexpected_node:{node.node_id}:{node.kind.value}"]
    if node.kind is QueryNodeKind.METRIC_SCOPE_SERIES:
        return _metric_scope_operand(node)
    if node.kind is QueryNodeKind.METRIC_COMPARISON:
        return [] if not node.arguments else [f"prov_metric_comparison_arguments:{node.node_id}"]
    return [f"prov_unexpected_node:{node.node_id}:{node.kind.value}"]


def comparison_coverage_violations(goal: FormGoal, plans: Sequence[OntologyQueryPlan]) -> list[str]:
    if goal.effective_operation is GoalOperation.COMPARE_WINDOWS:
        return _compare_windows_violations(plans)
    if goal.effective_operation is GoalOperation.COMPARE_ENTITIES:
        return _compare_entities_violations(plans)
    return []


def _metric_scope_operand(node: OntologyQueryNode) -> list[str]:
    if set(node.arguments) != {"concept_id", "start", "end"}:
        return [f"prov_metric_window:{node.node_id}"]
    if not all(
        isinstance(node.arguments[item], str) and node.arguments[item] for item in node.arguments
    ):
        return [f"prov_metric_window:{node.node_id}"]
    return []


def _compare_windows_violations(plans: Sequence[OntologyQueryPlan]) -> list[str]:
    nodes = {node.node_id: node for plan in plans for node in plan.nodes}
    outputs = [nodes[item] for plan in plans for item in plan.output_node_ids if item in nodes]
    metrics = [node for node in nodes.values() if node.kind is QueryNodeKind.METRIC_SCOPE_SERIES]
    if len(outputs) != 1 or outputs[0].kind is not QueryNodeKind.METRIC_COMPARISON:
        return ["sem_comparison_read_differs"]
    if len(metrics) != 2 or tuple(outputs[0].depends_on) != tuple(node.node_id for node in metrics):
        return ["sem_comparison_read_differs"]
    concepts = {node.arguments.get("concept_id") for node in metrics}
    return [] if len(concepts) == 1 else ["sem_comparison_measure_mismatch"]


def _compare_entities_violations(plans: Sequence[OntologyQueryPlan]) -> list[str]:
    nodes = {node.node_id: node for plan in plans for node in plan.nodes}
    outputs = [nodes[item] for plan in plans for item in plan.output_node_ids if item in nodes]
    if len(outputs) != 2:
        return ["sem_comparison_read_differs"]
    names = []
    for node in outputs:
        if node.kind is not QueryNodeKind.FUNCTION:
            return ["sem_comparison_read_differs"]
        names.append(node.arguments.get("function_name"))
    return [] if len(set(names)) == 1 else ["sem_comparison_measure_mismatch"]


__all__ = ["comparison_coverage_violations", "comparison_operand_violations"]
