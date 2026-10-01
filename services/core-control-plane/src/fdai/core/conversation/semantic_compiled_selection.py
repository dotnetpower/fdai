"""Select the one answerable batch of a form reading, or tag why it cannot answer.

A released reading answers only as one goal compiled into one verified batch with only
limitations a reviewed notice states; relation sides that span batches answer as one plan
only when every side fits one intent graph. Every other reading gets one tagged decision
and the closed codes that say why, and only a failed form is read once more.
"""

from __future__ import annotations

import json

from fdai_service_contracts.ontology_query import (
    MAX_INTENT_GRAPH_GOALS,
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    content_digest,
)

from .semantic_planning_models import hold_details
from .semantic_reasoning_compiler import CompiledBatch, GoalStatus
from .semantic_reasoning_nodes import union_tree
from .semantic_reasoning_shadow import ReasoningShadowObservation
from .semantic_reasoning_shape import BEYOND_LIST_READING

# One ontology query plan names at most eight output nodes.
_MAX_PLAN_OUTPUTS = 8


# Compiler reasons that name one mislabeled mention of an otherwise answerable reading. A
# concept no reviewed value matches can be a question word quoted as a kind of thing.
_FORM_MISLABELS = frozenset(
    {
        "measure_mention_unsupported",
        "result_instance_unsupported",
        "anchor_form_unsupported",
        "concept_not_found",
    }
)


def resample_worthy(observation: ReasoningShadowObservation) -> bool:
    decline = single_compiled_batch(observation)
    if not isinstance(decline, str):
        return False
    if decline == "not_released":
        dispositions = {item.disposition for item in observation.passes}
        return bool(dispositions) and not dispositions <= _UNAVAILABLE_PASSES
    return decline == "goal_not_compiled" and any(
        reason.split(":", 1)[0] in _FORM_MISLABELS
        for compilation in observation.compilations
        for goal in compilation.goals
        for reason in goal.reasons
    )


def single_compiled_batch(
    observation: ReasoningShadowObservation,
) -> tuple[CompiledBatch, float] | str:
    """Return the verified read of a released single-goal compilation, else a decline reason.

    A goal whose relation sides span several batches is read as one plan with every
    batch's output when the union fits one intent graph; otherwise it is declined.
    """

    # A reading that needs another pass is a continuation, not a failed form, whether or
    # not its later pass ran; it is never resampled as a form failure.
    if observation.continuation_pending or any(
        compilation.needs_continuation for compilation in observation.compilations
    ):
        return "continuation_pending"
    if not observation.released:
        return "not_released"
    if len(observation.compilations) != 1:
        return "compilation_count"
    goals = observation.compilations[0].goals
    if len(goals) != 1:
        return "goal_count"
    goal = goals[0]
    if goal.status is not GoalStatus.COMPILED:
        return "goal_not_compiled"
    if not _limitations_stated(goal.limitations, goal.batches):
        return "goal_limited"
    if not goal.batches or goal.confidence is None:
        return "goal_unbatched"
    if [(batch.index, batch.total) for batch in goal.batches] != [
        (index, len(goal.batches)) for index in range(len(goal.batches))
    ]:
        return "batch_order"
    merged = _merged_batch(goal.batches)
    return (merged, goal.confidence) if isinstance(merged, CompiledBatch) else merged


# Reviewed limitations an answer states as catalog notices, keyed by limitation code.
_STATED_LIMITATIONS = {
    "default_window_applied": "window.default",
    "time_window_applied": "window.applied",
    "time_window_model_judged": "window.model_judged",
    "time_window_fixed": "window.fixed",
    "cause_not_established": "cause.not_established",
    "possible_impact_not_observed": "impact.possible_not_observed",
    "anchor_uniqueness_unproven": "anchor.uniqueness_unproven",
}


def _limitations_stated(limitations: tuple[str, ...], batches: tuple[CompiledBatch, ...]) -> bool:
    """Return whether every limitation is one each frame requires its answer to state."""

    for limitation in limitations:
        code, _, value = limitation.partition(":")
        prefix = _STATED_LIMITATIONS.get(code)
        if prefix is None:
            return False
        requirement = f"{prefix}.{value}" if value else prefix
        if any(requirement not in batch.frame.evidence_requirements for batch in batches):
            return False
    return True


_CONTINUATION_DECLINES = frozenset(
    {"continuation_pending", "compilation_count", "goal_count", "merge_over_budget"}
)
_UNAVAILABLE_PASSES = frozenset({"model_unavailable", "shadow_error", "input_held"})


def decline_decision(reason: str, observation: ReasoningShadowObservation) -> str:
    """Return the tagged decision for one declined form path."""

    if reason == "not_released":
        dispositions = {item.disposition for item in observation.passes}
        if not dispositions or dispositions <= _UNAVAILABLE_PASSES:
            return "unavailable"
        if "invalid" in dispositions:
            return "unverified"
        if dispositions & {"clarify", "review"}:
            return "clarification"
        return "unavailable" if observation.review == "unavailable" else "unverified"
    if reason in _CONTINUATION_DECLINES:
        return "continuation"
    if reason == "goal_limited":
        return "limited"
    if reason == "goal_not_compiled":
        failed = [
            goal
            for compilation in observation.compilations
            for goal in compilation.goals
            if goal.status is not GoalStatus.COMPILED
        ]
        # Only a reason that names an unsupported atom says the question asks for something
        # no builder reads; an incomplete anchor read or an unbound concept is about data.
        if any(
            goal.status is GoalStatus.UNSUPPORTED
            and any(item.split(":", 1)[0].endswith("_unsupported") for item in goal.reasons)
            for goal in failed
        ):
            return "unsupported"
        if any(goal.status is GoalStatus.CLARIFY for goal in failed):
            return "clarification"
        return "unavailable"
    return "unverified"


def decision_details(decision: str, observation: ReasoningShadowObservation) -> tuple[str, ...]:
    """Return the closed codes that say why a declined reading ended with ``decision``.

    Positions and mention ids stay out of a code the operator's notice may name: a review
    reason keeps only its constraint role, and a clarification keeps only its kind.
    """

    goals = [
        goal
        for compilation in observation.compilations
        for goal in compilation.goals
        if goal.status is not GoalStatus.COMPILED
    ]
    codes: list[str] = []
    if decision == "unsupported":
        codes.extend(
            reason
            for goal in goals
            if goal.status is GoalStatus.UNSUPPORTED
            for reason in goal.reasons
            if reason.split(":", 1)[0].endswith("_unsupported")
        )
    elif decision == "clarification":
        codes.extend(
            reason.split(":", 1)[0]
            for item in observation.passes
            if item.disposition in {"clarify", "review"}
            for reason in item.reasons
        )
        codes.extend(
            reason.split(":", 1)[0]
            for goal in goals
            if goal.status is GoalStatus.CLARIFY
            for reason in goal.reasons
        )
    elif decision == "unverified":
        for reason in observation.review_reasons:
            kind, _, rest = reason.partition(":")
            role = rest.split(":", 1)[0]
            if kind == "review_uncovered" and role:
                codes.append(f"role:{role}")
            elif kind == "review_unexpressible" and role:
                codes.append(f"unexpressible:{role}")
            elif kind == "review_answer_kind" and role:
                codes.append(f"answer_kind:{role}")
            else:
                codes.append(kind)
    elif decision == "unavailable":
        codes.extend(reason for goal in goals for reason in goal.reasons)
    elif decision == "limited":
        codes.extend(
            limitation.split(":", 1)[0]
            for compilation in observation.compilations
            for goal in compilation.goals
            for limitation in goal.limitations
            if limitation.split(":", 1)[0] not in _STATED_LIMITATIONS
        )
    return hold_details(codes)


def held_word_recovery_reasons(observation: ReasoningShadowObservation) -> tuple[str, ...]:
    """Return why a word-recovered plan would answer a narrower question, else nothing.

    A released reading's unsupported goal names a stated atom no builder reads; a data
    outcome, such as an incomplete anchor read, says nothing about the question. A parsed
    reading of any pass that asks more than one filtered list also holds such a plan.
    """

    reasons: list[str] = []
    if observation.released and not observation.continuation_pending:
        reasons.extend(
            reason
            for compilation in observation.compilations
            for goal in compilation.goals
            if goal.status is GoalStatus.UNSUPPORTED
            for reason in goal.reasons
            if reason.split(":", 1)[0].endswith("_unsupported")
        )
    if any(BEYOND_LIST_READING in item.shape for item in observation.passes):
        reasons.append("reading_beyond_list")
    return tuple(dict.fromkeys(reasons))


def _merged_batch(batches: tuple[CompiledBatch, ...]) -> CompiledBatch | str:
    if len(batches) == 1:
        return batches[0]
    frame = batches[0].frame
    if any(batch.frame.frame_digest != frame.frame_digest for batch in batches):
        return "merge_frame_mismatch"
    nodes: dict[str, OntologyQueryNode] = {}
    outputs: list[str] = []
    for batch in batches:
        for node in batch.plan.nodes:
            # A shared anchor read repeats with identical content; any other id clash is unsafe.
            if node.node_id in nodes and nodes[node.node_id] != node:
                return "merge_node_conflict"
            nodes.setdefault(node.node_id, node)
        outputs.extend(batch.plan.output_node_ids)
    if len(set(outputs)) != len(outputs):
        return "merge_node_conflict"
    if len(outputs) > _MAX_PLAN_OUTPUTS:
        united = _united_outputs(nodes, outputs)
        if united is None:
            return "merge_over_budget"
        outputs = united
    if len(nodes) > MAX_INTENT_GRAPH_GOALS:
        return "merge_over_budget"
    first = batches[0].plan
    body = {
        **first.model_dump(mode="json", exclude={"nodes", "output_node_ids", "plan_digest"}),
        "nodes": [node.model_dump(mode="json") for node in nodes.values()],
        "output_node_ids": outputs,
    }
    plan = OntologyQueryPlan.model_validate({**body, "plan_digest": content_digest(body)})
    return CompiledBatch(index=0, total=1, frame=frame, plan=plan)


def _united_outputs(nodes: dict[str, OntologyQueryNode], outputs: list[str]) -> list[str] | None:
    """Unite traversal outputs that reach one ObjectType, so every side is still read.

    One plan names at most eight outputs; the traversals stay as nodes and a union of
    those reaching the same endpoint type becomes one output, which keeps each reached
    endpoint exactly once instead of declining the sides beyond the eighth.
    """

    groups: dict[str, list[str]] = {}
    for node_id in outputs:
        node = nodes[node_id]
        if node.kind is not QueryNodeKind.RELATIONSHIP_TRAVERSAL:
            return None
        selector = json.loads(node.arguments_json).get("selector")
        if not isinstance(selector, dict) or not isinstance(selector.get("name"), str):
            return None
        groups.setdefault(selector["name"], []).append(node_id)
    united: list[str] = []
    for index, members in enumerate(groups.values(), start=1):
        if len(members) == 1:
            united.append(members[0])
            continue
        union_id = f"union-{index}"
        created = union_tree(union_id, members)
        if any(node.node_id in nodes for node in created):
            return None
        nodes.update((node.node_id, node) for node in created)
        united.append(union_id)
    return united if len(united) <= _MAX_PLAN_OUTPUTS else None


__all__ = [
    "decision_details",
    "decline_decision",
    "held_word_recovery_reasons",
    "resample_worthy",
    "single_compiled_batch",
]
