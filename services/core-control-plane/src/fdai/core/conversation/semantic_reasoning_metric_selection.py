"""Compile a stated metric threshold or order over a collection into one metric reader stage.

The question form states the comparator, the copied threshold, its unit, and an order
with an optional stated count. Code checks the unit against the grounded metric concept's
canonical unit, derives the reader arguments from the form alone, and lets the reader
apply them to members with a complete window only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    QueryNodeKind,
    canonical_json,
)

from fdai.core.ontology_platform.resource_metric_queries import RESOURCE_METRIC_FUNCTION_NAME

from .semantic_reasoning_form import (
    FilterRole,
    FormGoal,
    GoalLevel,
    GoalOperation,
    MeasureKind,
)
from .semantic_reasoning_metrics import metric_window
from .semantic_reasoning_nodes import (
    CompileContext,
    OperatorResult,
    concept_values,
    declared_maximum,
    function_declared,
)

WINDOW_LIMITATIONS = {
    "default": "default_window_applied",
    "recipe": "recipe_window_applied",
    "applied": "time_window_applied",
    "model_judged": "time_window_model_judged",
}


@dataclass(frozen=True, slots=True)
class MetricStage:
    """One metric reader stage that filters or orders a collection read."""

    arguments: dict[str, Any]
    concept: str
    window_kind: str
    seconds: int
    # The reviewed recipe a qualitative word was read through, stated in the answer.
    recipe_requirement: str | None = None

    def node(self, node_id: str, source_id: str) -> OntologyQueryNode:
        return OntologyQueryNode(
            node_id=node_id,
            kind=QueryNodeKind.FUNCTION,
            depends_on=(source_id,),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_METRIC_FUNCTION_NAME,
                    "arguments": self.arguments,
                    "dependency_arguments": {source_id: "query_result"},
                }
            ),
            output_kind="query.table",
        )

    @property
    def limitation(self) -> str:
        return f"{WINDOW_LIMITATIONS[self.window_kind]}:{self.seconds}"

    @property
    def evidence_requirement(self) -> str:
        return f"window.{self.window_kind}.{self.seconds}"

    @property
    def evidence_requirements(self) -> tuple[str, ...]:
        return (self.evidence_requirement,) + (
            (self.recipe_requirement,) if self.recipe_requirement is not None else ()
        )


Recipe = tuple[str, str, str, int, int]


def stated_qualifier(goal: FormGoal) -> str | None:
    """Return the qualitative word a goal's metric filter states without a number."""

    filters = [item for item in goal.filters if item.role is FilterRole.METRIC]
    if filters and filters[0].qualifier is not None:
        return filters[0].qualifier.value
    return None


def goal_recipe(goal: FormGoal, concept: str, recipes: Sequence[Recipe]) -> Recipe | None:
    """Return the reviewed recipe for the goal's qualitative word and metric, if any."""

    qualifier = stated_qualifier(goal)
    if qualifier is None:
        return None
    return next((item for item in recipes if item[0] == concept and item[1] == qualifier), None)


def metric_selection_arguments(
    goal: FormGoal, *, recipe: Recipe | None = None, unit: str | None = None
) -> dict[str, Any] | None:
    """Return the comparison and order arguments the form states, from the goal alone.

    A qualitative word reads only through ``recipe``, with the metric's canonical ``unit``.
    """

    filters = [item for item in goal.filters if item.role is FilterRole.METRIC]
    ranked = goal.effective_operation is GoalOperation.RANK
    if not filters and not ranked:
        return None
    arguments: dict[str, Any] = {}
    if filters and filters[0].comparison is not None:
        comparison = filters[0].comparison
        arguments.update(
            comparator=comparison.comparator.value,
            threshold=comparison.value,
            threshold_unit=comparison.unit.value,
        )
    elif filters and filters[0].qualifier is not None and recipe is not None and unit:
        arguments.update(comparator=recipe[2], threshold=str(recipe[3]), threshold_unit=unit)
    order = goal.measure.order if goal.measure is not None else None
    if ranked and order is not None:
        arguments["order_direction"] = order.direction.value
        if order.limit is not None:
            arguments["order_limit"] = order.limit
    # A count states only how many match, so its rows are matches alone; a list names
    # every member it could not measure.
    arguments["list_unknown"] = goal.effective_operation is not GoalOperation.COUNT
    return arguments


def verification_arguments(
    goal: FormGoal,
    *,
    maximum_window_seconds: int | None,
    concepts: set[str],
    recipes: Sequence[Recipe] = (),
    units: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Re-derive the exact metric reader arguments from admitted goal provenance."""

    if maximum_window_seconds is None or not concepts:
        return None
    recipe = goal_recipe(goal, sorted(concepts)[0], recipes) if len(concepts) == 1 else None
    if stated_qualifier(goal) is not None and recipe is None:
        return None
    window = recipe_window(goal, recipe, maximum=maximum_window_seconds)
    if isinstance(window, str):
        return None
    seconds, _ = window
    unit = (units or {}).get(sorted(concepts)[0]) if recipe is not None else None
    return {
        "metric_concepts": sorted(concepts),
        "window_seconds": seconds,
        **(metric_selection_arguments(goal, recipe=recipe, unit=unit) or {}),
    }


def recipe_window(goal: FormGoal, recipe: Recipe | None, *, maximum: int) -> tuple[int, str] | str:
    """Return the read window: a reviewed recipe's window when the goal states none."""

    window = metric_window(goal, maximum=maximum)
    if (
        recipe is not None
        and recipe[4]
        and not isinstance(window, str)
        and window[1] == "default"
        and recipe[4] <= maximum
    ):
        return recipe[4], "recipe"
    return window


def verification_required_functions(goal: FormGoal) -> frozenset[str] | None:
    """Return the exact reader set required for an instance metric lookup."""

    if (
        (goal.level, goal.effective_operation) == (GoalLevel.INSTANCE, GoalOperation.LOOKUP)
        and goal.measure is not None
        and goal.measure.kind is MeasureKind.METRIC
    ):
        return frozenset({RESOURCE_METRIC_FUNCTION_NAME})
    return None


def metric_mention(goal: FormGoal) -> str | None | OperatorResult:
    """Return the one metric mention the goal filters or orders by, if it states one."""

    filters = [item for item in goal.filters if item.role is FilterRole.METRIC]
    if len(filters) > 1:
        return OperatorResult(unsupported=("multiple_metric_filters_unsupported",))
    measured = (
        goal.measure.mention
        if goal.effective_operation is GoalOperation.RANK
        and goal.measure is not None
        and goal.measure.kind is MeasureKind.METRIC
        else None
    )
    stated = filters[0].mention if filters else None
    if stated is not None and measured is not None and stated != measured:
        return OperatorResult(unsupported=("metric_filter_and_order_differ",))
    return stated or measured


def metric_stage(goal: FormGoal, ctx: CompileContext) -> MetricStage | OperatorResult | None:
    """Return the reader stage for a stated metric threshold or order, or why it cannot."""

    if metric_selection_arguments(goal) is None:
        return None
    mention = metric_mention(goal)
    if isinstance(mention, OperatorResult):
        return mention
    if mention is None:
        return OperatorResult(unsupported=("metric_concept_required",))
    concepts, failure = concept_values(mention, ctx)
    if failure is not None:
        return failure
    if len(concepts) != 1:
        return OperatorResult(unsupported=("metric_concept_count_unsupported",))
    concept = concepts[0]
    recipe = goal_recipe(goal, concept, ctx.manifest.metric_recipes)
    qualifier = stated_qualifier(goal)
    if qualifier is not None and recipe is None:
        # No reviewed recipe gives this word a threshold for this metric.
        return OperatorResult(unsupported=("metric_classification_unavailable",))
    unit = dict(ctx.manifest.metric_units).get(concept)
    arguments = metric_selection_arguments(goal, recipe=recipe, unit=unit) or {}
    if recipe is not None and unit is None:
        return OperatorResult(unsupported=("metric_unit_unreviewed",))
    if "threshold_unit" in arguments and recipe is None:
        canonical = dict(ctx.manifest.metric_units).get(concept)
        if canonical is None:
            return OperatorResult(unsupported=("metric_unit_unreviewed",))
        if arguments["threshold_unit"] != canonical:
            # A threshold in another unit is never converted silently.
            return OperatorResult(clarify=("metric_unit_incompatible",))
    if not function_declared(ctx, RESOURCE_METRIC_FUNCTION_NAME):
        return OperatorResult(
            unsupported=(f"function_unavailable:{RESOURCE_METRIC_FUNCTION_NAME}",)
        )
    maximum = declared_maximum(ctx, RESOURCE_METRIC_FUNCTION_NAME, "window_seconds")
    if maximum is None:
        return OperatorResult(
            unsupported=(f"function_unavailable:{RESOURCE_METRIC_FUNCTION_NAME}",)
        )
    window = recipe_window(goal, recipe, maximum=maximum)
    if isinstance(window, str):
        return OperatorResult(unsupported=(window,))
    seconds, kind = window
    if kind == "applied" and goal.id in ctx.admission.judged_times:
        kind = "model_judged"
    return MetricStage(
        arguments={"metric_concepts": [concept], "window_seconds": seconds, **arguments},
        concept=concept,
        window_kind=kind,
        seconds=seconds,
        recipe_requirement=(
            f"metric_recipe.{recipe[1]}.{recipe[2]}.{recipe[3]}.{unit}"
            if recipe is not None
            else None
        ),
    )


__all__ = [
    "RESOURCE_METRIC_FUNCTION_NAME",
    "WINDOW_LIMITATIONS",
    "MetricStage",
    "metric_mention",
    "metric_selection_arguments",
    "metric_stage",
    "verification_arguments",
    "verification_required_functions",
]
