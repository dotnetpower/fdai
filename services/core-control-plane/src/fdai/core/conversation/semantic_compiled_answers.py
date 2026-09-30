"""Answer a turn from a released question-form compilation in the local profile.

The form path reads the question beside the judgment, with its own provider calls, deadline,
and anchor reads scoped like the turn's executor. Only a released path whose single goal
compiled into one verified batch answers; every other outcome leaves the current path to
answer the turn. The path records content-free decision events and grants no authority.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import time
from collections.abc import Callable, MutableSequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from fdai_service_contracts.ontology_query import (
    MAX_INTENT_GRAPH_GOALS,
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    content_digest,
    project_intent_graph,
)

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.acl import ProjectionRequest

from .adaptive_call_scope import bind_adaptive_model_budget
from .intent_graph import build_intent_graph
from .model_observation import ConversationModelObservation
from .semantic_manifest import semantic_principal_scope_digest
from .semantic_planning_alignment import verify_frame_plan_alignment
from .semantic_planning_models import (
    SemanticPlanningDisposition,
    SemanticPlanningOutcome,
    hold_details,
)
from .semantic_planning_support import _outcome, _refresh_object_set_cutoffs
from .semantic_reasoning_binding import GatewayAnchorResolver
from .semantic_reasoning_compiler import CompiledBatch, GoalStatus
from .semantic_reasoning_nodes import union_tree
from .semantic_reasoning_shadow import (
    QuestionFormModel,
    ReasoningShadowObservation,
    ShadowBudget,
    run_reasoning_shadow,
)
from .semantic_reasoning_shape import BEYOND_LIST_READING
from .session import Principal

_LOGGER = logging.getLogger(__name__)
COMPILED_PLAN_SOURCE = "compiled_question_form"
_MAX_EVENT_ITEMS = 16
# One ontology query plan names at most eight output nodes.
_MAX_PLAN_OUTPUTS = 8
_MAX_SHAPE_ITEMS = 24
# Plans recovered from words the judgment stated, not from a typed reading of the question.
_LEXICAL_PLAN_SOURCES = frozenset({"server_stated_filter", "server_resource_target_candidates"})


@dataclass(frozen=True, slots=True)
class CompiledAnswerSettings:
    """Bounds for one turn's form path; the defaults match the live evaluation harness."""

    default_lookback_seconds: int = 86_400
    deadline_seconds: float = 45.0
    budget: ShadowBudget = field(default_factory=ShadowBudget)
    # Typed-only answering: a read answers only from the form path, never the legacy cascade.
    typed_only: bool = False

    def __post_init__(self) -> None:
        if not 60 <= self.default_lookback_seconds <= 31 * 86_400:
            raise ValueError("compiled answer default lookback MUST be in [60, 2678400]")
        if not 1.0 <= self.deadline_seconds <= 120.0:
            raise ValueError("compiled answer deadline MUST be in [1, 120] seconds")


class _ObservationCollector:
    """Account every form-path call so the turn record shows each model call made."""

    def __init__(self) -> None:
        self.observations: list[ConversationModelObservation] = []

    def reserve(self, input_bytes: int, output_tokens: int, reserved_calls: int) -> int:
        return 0

    def observe(self, reservation: int, observation: ConversationModelObservation) -> None:
        self.observations.append(observation)


class CompiledAnswerTicket:
    """One started form path; the planner consumes it once or cancels it."""

    def __init__(
        self,
        future: concurrent.futures.Future[ReasoningShadowObservation],
        collector: _ObservationCollector,
        *,
        deadline_seconds: float,
        manifest: QueryManifest,
        verifier: OntologyQueryPlanVerifier,
        cutoff: Callable[[], datetime],
        clock: Callable[[], float] = time.monotonic,
        typed_only: bool = False,
    ) -> None:
        self._future = future
        self._collector = collector
        self._deadline = clock() + deadline_seconds
        self._manifest = manifest
        self._verifier = verifier
        self._cutoff = cutoff
        self._clock = clock
        self._settled = False
        self._unsupported: tuple[str, ...] = ()
        self.typed_only = typed_only
        # The tagged terminal decision, set once the path is consumed or cancelled.
        self.decision: str | None = None
        # Closed codes that say why a declined reading ended with its decision.
        self.details: tuple[str, ...] = ()

    def outcome(
        self,
        *,
        manifest_digest: str,
        observations: MutableSequence[Any],
    ) -> SemanticPlanningOutcome | None:
        """Return the compiled answer when the path released one; record its calls either way."""

        if self._settled:
            return None
        self._settled = True
        try:
            observation = self._future.result(timeout=max(0.0, self._deadline - self._clock()))
        except concurrent.futures.TimeoutError:
            self._future.cancel()
            self.decision = "unavailable"
            _log_completion("timeout")
            return None
        except Exception as exc:  # noqa: BLE001 - provider details stay inside the adapter
            self._future.cancel()
            self.decision = "unavailable"
            _log_completion("failed", failure_type=type(exc).__name__)
            return None
        finally:
            observations.extend(self._collector.observations)
        selected = _single_compiled_batch(observation)
        if isinstance(selected, str):
            self._unsupported = _held_word_recovery_reasons(observation)
            self.decision = _decline_decision(selected, observation)
            self.details = _decision_details(self.decision, observation)
            _log_completion("declined", observation=observation, decline_reason=selected)
            return None
        batch, confidence = selected
        # Compilation ran seconds ago; the gateway accepts only a current cutoff, so the plan
        # is stamped again and verified again before it can answer.
        try:
            plan = _refresh_object_set_cutoffs(batch.plan, execution_time=self._cutoff())
            self._verifier.verify(plan, manifest=self._manifest)
            verify_frame_plan_alignment(batch.frame, plan, descriptors=self._manifest.descriptors)
            intent_graph = build_intent_graph(frame=batch.frame, plan=plan, confidence=confidence)
            # The Console shows the graph it answers from, so a graph it cannot show holds.
            project_intent_graph(intent_graph)
        except (PermissionError, ValueError) as exc:
            self.decision = "unverified"
            _log_completion("failed", observation=observation, failure_type=type(exc).__name__)
            return None
        self.decision = "selected"
        _log_completion("selected", observation=observation)
        _LOGGER.info(
            "semantic_planning_stage_completed",
            extra={
                "stage": "plan_verify",
                "plan_source": COMPILED_PLAN_SOURCE,
                "output_shape": batch.frame.output_shape,
            },
        )
        return _outcome(
            SemanticPlanningDisposition.PLANNED,
            "semantic_plan_verified",
            manifest_digest=manifest_digest,
            frame=batch.frame,
            plan=plan,
            intent_graph=intent_graph,
        )

    def veto(self, plan_source: str, *, manifest_digest: str) -> SemanticPlanningOutcome | None:
        """Hold a word-recovered plan that answers a narrower question than the typed reading.

        A reviewed reading that no builder can compile names what the question needs, and
        any parsed reading may show a grouping, state, relation, or schema level that one
        filtered list recovered from the judgment's words never reads.
        """

        if not self._unsupported or plan_source not in _LEXICAL_PLAN_SOURCES:
            return None
        _LOGGER.info(
            "semantic_compiled_answer_veto",
            extra={
                "plan_source": plan_source,
                "goal_reasons": list(self._unsupported[:_MAX_EVENT_ITEMS]),
            },
        )
        return _outcome(
            SemanticPlanningDisposition.UNSUPPORTED,
            "semantic_stated_constraint_unsupported",
            manifest_digest=manifest_digest,
            hold_details=hold_details(self._unsupported),
        )

    def cancel(self) -> None:
        """Cancel an unconsumed path; the owner loop drains its provider calls."""

        if not self._settled:
            self._settled = True
            self._future.cancel()
            self.decision = "superseded"
            _log_completion("cancelled")


class CompiledAnswerPath:
    """Start the form path beside the judgment for one unbound operational turn."""

    def __init__(
        self,
        *,
        model: QuestionFormModel,
        owner_loop: asyncio.AbstractEventLoop,
        gateway: SecuredObjectSetQueryGateway,
        purpose: str,
        clock: Callable[[], datetime],
        settings: CompiledAnswerSettings | None = None,
    ) -> None:
        self._model = model
        self._owner_loop = owner_loop
        self._gateway = gateway
        self._purpose = purpose
        self._clock = clock
        self._settings = settings or CompiledAnswerSettings()

    @property
    def typed_only(self) -> bool:
        return self._settings.typed_only

    def start(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        locale: str,
        manifest: QueryManifest,
        verifier: OntologyQueryPlanVerifier,
        principal: Principal,
        purpose: str,
    ) -> CompiledAnswerTicket | None:
        """Schedule the form path; a break-glass principal or other purpose is skipped."""

        if purpose != self._purpose:
            return None
        try:
            role = CeilingRole(principal.role)
        except ValueError:
            return None
        resolver = GatewayAnchorResolver(
            self._gateway,
            projection_request=ProjectionRequest(
                caller_role=role,
                declared_purposes=frozenset({purpose}),
                principal_scope_digest=semantic_principal_scope_digest(
                    principal=principal, purpose=purpose
                ),
            ),
            purpose=purpose,
            as_of=self._clock,
        )
        collector = _ObservationCollector()
        future = asyncio.run_coroutine_threadsafe(
            _run_form_path(
                self._model,
                collector,
                utterance=utterance,
                context=context,
                locale=locale,
                manifest=manifest,
                verifier=verifier,
                purpose=purpose,
                evaluation_time=self._clock(),
                default_lookback_seconds=self._settings.default_lookback_seconds,
                budget=self._settings.budget,
                resolver=resolver,
            ),
            self._owner_loop,
        )
        return CompiledAnswerTicket(
            future,
            collector,
            deadline_seconds=self._settings.deadline_seconds,
            manifest=manifest,
            verifier=verifier,
            cutoff=self._clock,
            typed_only=self._settings.typed_only,
        )


def start_compiled_answer(
    path: CompiledAnswerPath,
    *,
    eligible: bool,
    **arguments: Any,
) -> CompiledAnswerTicket | None:
    """Start the form path for an eligible turn, or record a typed skip."""

    if not eligible:
        _log_completion("skipped")
        return None
    return path.start(**arguments)


def compiled_answer_or(
    ticket: CompiledAnswerTicket | None,
    outcome: SemanticPlanningOutcome,
    *,
    manifest_digest: str,
    observations: MutableSequence[Any],
) -> SemanticPlanningOutcome:
    """Prefer a released compiled answer over a current-path hold or clarification."""

    if ticket is None:
        return outcome
    compiled = ticket.outcome(manifest_digest=manifest_digest, observations=observations)
    if compiled is not None:
        return compiled
    return (
        typed_only_outcome(ticket, manifest_digest=manifest_digest)
        if ticket.typed_only
        else outcome
    )


# Each tagged form-path decision ends a typed-only turn with one typed planner outcome.
_TYPED_ONLY_OUTCOMES: dict[str, tuple[SemanticPlanningDisposition, str]] = {
    "unsupported": (
        SemanticPlanningDisposition.UNSUPPORTED,
        "semantic_stated_constraint_unsupported",
    ),
    "clarification": (SemanticPlanningDisposition.UNAVAILABLE, "semantic_reading_ambiguous"),
    "continuation": (
        SemanticPlanningDisposition.UNAVAILABLE,
        "semantic_reading_continuation_required",
    ),
    "limited": (SemanticPlanningDisposition.UNAVAILABLE, "semantic_reading_limited"),
    "unverified": (SemanticPlanningDisposition.UNAVAILABLE, "semantic_reading_unverified"),
    "unavailable": (SemanticPlanningDisposition.UNAVAILABLE, "semantic_reading_unavailable"),
}


def typed_only_outcome(
    ticket: CompiledAnswerTicket | None,
    *,
    manifest_digest: str,
) -> SemanticPlanningOutcome:
    """End a typed-only read that the form path did not answer, never the legacy cascade.

    A turn whose form path never started, such as a bound-resource read, is unavailable
    rather than answered from the judgment's words.
    """

    decision = ticket.decision if ticket is not None and ticket.decision else "unavailable"
    disposition, reason = _TYPED_ONLY_OUTCOMES.get(decision, _TYPED_ONLY_OUTCOMES["unavailable"])
    details = ticket.details if ticket is not None and decision == ticket.decision else ()
    _LOGGER.info(
        "semantic_typed_only_outcome",
        extra={
            "decision": decision,
            "reason": reason,
            "disposition": disposition.value,
            "details": list(details),
        },
    )
    return _outcome(disposition, reason, manifest_digest=manifest_digest, hold_details=details)


async def _run_form_path(
    model: QuestionFormModel,
    collector: _ObservationCollector,
    **arguments: Any,
) -> ReasoningShadowObservation:
    """Read the question once, and once more only when the first reading failed as a form.

    A second sample passes the same admission, grounding, blind review, and selection
    rules, so it never lowers the bar; it only replaces a reading whose form was invalid,
    unreviewed, or mislabeled one mention's kind. At most two samples are taken.
    """

    async with bind_adaptive_model_budget(collector):
        first = await run_reasoning_shadow(model=model, retain_compilations=True, **arguments)
        if not _resample_worthy(first):
            return first
        second = await run_reasoning_shadow(model=model, retain_compilations=True, **arguments)
    if isinstance(_single_compiled_batch(second), str):
        return replace(first, notes=(*first.notes, "form_resampled_unanswered"))
    return replace(
        second,
        model_calls=first.model_calls + second.model_calls,
        elapsed_ms=first.elapsed_ms + second.elapsed_ms,
        notes=(*second.notes, "form_resampled"),
    )


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


def _resample_worthy(observation: ReasoningShadowObservation) -> bool:
    decline = _single_compiled_batch(observation)
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


def _single_compiled_batch(
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


def _decline_decision(reason: str, observation: ReasoningShadowObservation) -> str:
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


def _decision_details(decision: str, observation: ReasoningShadowObservation) -> tuple[str, ...]:
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


def _held_word_recovery_reasons(observation: ReasoningShadowObservation) -> tuple[str, ...]:
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


def _log_completion(
    result: str,
    *,
    observation: ReasoningShadowObservation | None = None,
    failure_type: str | None = None,
    decline_reason: str | None = None,
) -> None:
    extra: dict[str, object] = {"result": result}
    if failure_type is not None:
        extra["failure_type"] = failure_type
    if decline_reason is not None:
        extra["decline_reason"] = decline_reason
    if observation is not None:
        goals = [goal for compilation in observation.compilations for goal in compilation.goals]
        extra.update(
            {
                "released": observation.released,
                "review": observation.review,
                "review_reasons": list(observation.review_reasons[:_MAX_EVENT_ITEMS]),
                "pass_dispositions": [item.disposition for item in observation.passes],
                "pass_reasons": [reason for item in observation.passes for reason in item.reasons][
                    :_MAX_EVENT_ITEMS
                ],
                "goal_statuses": [
                    goal.status for item in observation.passes for goal in item.goals
                ][:_MAX_EVENT_ITEMS],
                "goal_reasons": [
                    reason
                    for item in observation.passes
                    for goal in item.goals
                    for reason in goal.reasons
                ][:_MAX_EVENT_ITEMS],
                "compiled_goals": len(goals),
                "batch_count": sum(len(goal.batches) for goal in goals),
                "goal_limitations": [
                    limitation for goal in goals for limitation in goal.limitations
                ][:_MAX_EVENT_ITEMS],
                "model_calls": observation.model_calls,
                "elapsed_ms": observation.elapsed_ms,
                "notes": list(observation.notes[:_MAX_EVENT_ITEMS]),
                "direction_swaps": [
                    goal for item in observation.passes for goal in item.direction_swaps
                ][:_MAX_EVENT_ITEMS],
                "form_shapes": list(
                    observation.passes[-1].shape[:_MAX_SHAPE_ITEMS] if observation.passes else ()
                ),
            }
        )
    _LOGGER.info("semantic_compiled_answer_completed", extra=extra)


__all__ = [
    "COMPILED_PLAN_SOURCE",
    "CompiledAnswerPath",
    "CompiledAnswerSettings",
    "CompiledAnswerTicket",
    "compiled_answer_or",
    "start_compiled_answer",
    "typed_only_outcome",
]
