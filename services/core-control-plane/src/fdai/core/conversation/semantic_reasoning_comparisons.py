"""Compile reviewed comparison operators from closed form fields."""

from __future__ import annotations

from datetime import UTC, timedelta

from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind, canonical_json

from .semantic_reasoning_form import FormGoal, GoalOperation, MeasureKind, TimeKind
from .semantic_reasoning_metrics import METRIC_READER, metric_window
from .semantic_reasoning_nodes import (
    FUNCTION_ANCHOR_LIMIT,
    RESOURCE_OBJECT_TYPE,
    CompileContext,
    OperatorResult,
    anchor_node,
    concept_values,
    declared_maximum,
    function_declared,
    plan_spec,
)


def comparison_goal(goal: FormGoal, ctx: CompileContext) -> OperatorResult | None:
    """Compile supported comparison forms or return their exact missing prerequisite."""

    if goal.effective_operation is GoalOperation.COMPARE_WINDOWS:
        return _compare_windows(goal, ctx)
    return None


def _compare_windows(goal: FormGoal, ctx: CompileContext) -> OperatorResult:
    measure = goal.measure
    if measure is None or measure.kind is not MeasureKind.METRIC or measure.mention is None:
        return OperatorResult(unsupported=("compare_windows_measure_unreviewed",))
    if goal.subject is None:
        return OperatorResult(unsupported=("anchor_missing",))
    if goal.time.kind is not TimeKind.TWO_WINDOWS or len(goal.time.windows) != 2:
        return OperatorResult(unsupported=("compare_windows_requires_two_typed_windows",))
    if not function_declared(ctx, METRIC_READER):
        return OperatorResult(unsupported=(f"function_unavailable:{METRIC_READER}",))
    concepts, failure = concept_values(measure.mention, ctx)
    if failure is not None:
        return failure
    if len(concepts) != 1:
        return OperatorResult(unsupported=("metric_concept_count_unsupported",))
    maximum = declared_maximum(ctx, METRIC_READER, "window_seconds")
    if maximum is None:
        return OperatorResult(unsupported=(f"function_unavailable:{METRIC_READER}",))
    windows: list[tuple[str, str]] = []
    end = ctx.evaluation_time.astimezone(UTC)
    for value in reversed(goal.time.windows):
        probe = goal.model_copy(
            update={
                "time": goal.time.model_copy(
                    update={"kind": TimeKind.WINDOW, "value": value, "windows": ()}
                )
            }
        )
        window = metric_window(probe, maximum=maximum)
        if isinstance(window, str):
            return OperatorResult(unsupported=(window,))
        seconds, _kind = window
        start = end - timedelta(seconds=seconds)
        windows.insert(0, (start.isoformat(), end.isoformat()))
        end = start
    anchor = anchor_node(f"{goal.id}-anchor", goal.subject, ctx, FUNCTION_ANCHOR_LIMIT)
    if isinstance(anchor, OperatorResult):
        return anchor
    reads = tuple(
        OntologyQueryNode(
            node_id=f"{goal.id}-metric-{index}",
            kind=QueryNodeKind.METRIC_SCOPE_SERIES,
            depends_on=(anchor.node_id,),
            arguments_json=canonical_json(
                {"concept_id": concepts[0], "start": start, "end": end_at}
            ),
            output_kind="metric.window",
        )
        for index, (start, end_at) in enumerate(windows, start=1)
    )
    comparison = OntologyQueryNode(
        node_id=f"{goal.id}-comparison",
        kind=QueryNodeKind.METRIC_COMPARISON,
        depends_on=tuple(node.node_id for node in reads),
        arguments_json=canonical_json({}),
        output_kind="metric.comparison",
    )
    return OperatorResult(
        specs=(
            plan_spec(
                goal,
                (anchor, *reads, comparison),
                (comparison.node_id,),
                ctx,
                subjects=(RESOURCE_OBJECT_TYPE,),
                output_shape="metric_comparison",
                measure_concepts=(concepts[0],),
            ),
        )
    )


__all__ = ["comparison_goal"]
