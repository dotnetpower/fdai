"""Compile an admitted question form into verified, batched read plans.

The compiler is mechanical. It binds exact mention text, accepted concept
bindings, reviewed LinkType sides, and server defaults into closed plans, then
verifies every plan three ways: the ontology plan verifier, frame-to-plan
alignment, and the independent V-SEM, V-PROV, and V-LEVEL goal verifier. A goal
that fails any check is reported with its reasons and never broadened.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from fdai_service_contracts.ontology_query import (
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticProblemFrame,
    content_digest,
)

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest

from .semantic_planning_alignment import verify_frame_plan_alignment
from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_models import SemanticFrameProposal, SemanticOutputShape
from .semantic_reasoning_admission import AdmissionDisposition, FormAdmission
from .semantic_reasoning_binding import AnchorBindingReceipt, AnchorOutcome
from .semantic_reasoning_concepts import ConceptSelectionReceipt
from .semantic_reasoning_handles import ReferenceReceipt, reference_mention
from .semantic_reasoning_nodes import CompileContext, OperatorResult, PlanSpec
from .semantic_reasoning_operators import compile_goal
from .semantic_reasoning_verification import verify_goal_semantics


class GoalStatus(StrEnum):
    COMPILED = "compiled"
    UNSUPPORTED = "unsupported"
    CLARIFY = "clarify"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class CompiledBatch:
    """One verified plan; a goal with more sides than one plan holds has several."""

    index: int
    total: int
    frame: SemanticProblemFrame
    plan: OntologyQueryPlan


@dataclass(frozen=True, slots=True)
class GoalCompilation:
    goal_id: str
    status: GoalStatus
    reasons: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    batches: tuple[CompiledBatch, ...] = ()
    # The admitted goal's own confidence, carried only by a compiled goal.
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class ReasoningCompilation:
    """Per-goal compile outcomes for one admitted form; never an execution grant."""

    form_digest: str
    concept_digest: str
    anchor_digest: str
    goals: tuple[GoalCompilation, ...]
    needs_continuation: bool
    execution_authority: Literal[False] = False

    @property
    def digest(self) -> str:
        return content_digest(
            {
                "form_digest": self.form_digest,
                "concept_digest": self.concept_digest,
                "anchor_digest": self.anchor_digest,
                "needs_continuation": self.needs_continuation,
                "goals": [
                    {
                        "goal": goal.goal_id,
                        "status": goal.status.value,
                        "reasons": list(goal.reasons),
                        "limitations": list(goal.limitations),
                        "plans": [batch.plan.plan_digest for batch in goal.batches],
                    }
                    for goal in self.goals
                ],
            }
        )

    def goal(self, goal_id: str) -> GoalCompilation:
        return next(item for item in self.goals if item.goal_id == goal_id)


def compile_question_form(
    admission: FormAdmission,
    *,
    concepts: ConceptSelectionReceipt,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    purpose: str,
    evaluation_time: datetime,
    default_lookback_seconds: int,
    utterance: str,
    context: tuple[str, ...] = (),
    anchors: AnchorBindingReceipt | None = None,
    references: ReferenceReceipt | None = None,
) -> ReasoningCompilation:
    """Return verified plan batches or typed reasons for every goal of one form."""

    if admission.disposition is not AdmissionDisposition.ADMITTED:
        raise ValueError("only an admitted question form may compile")
    if evaluation_time.tzinfo is None:
        raise ValueError("reasoning evaluation time MUST be timezone-aware")
    if purpose not in manifest.purposes:
        raise PermissionError("reasoning purpose is absent from the principal manifest")
    ctx = CompileContext(
        manifest=manifest,
        admission=admission,
        concepts=concepts,
        purpose=purpose,
        evaluation_time=evaluation_time,
        default_lookback_seconds=default_lookback_seconds,
        anchors=anchors or AnchorBindingReceipt(),
        references=references or ReferenceReceipt(),
    )
    outcomes: dict[str, GoalCompilation] = {}
    for goal in admission.form.goals:
        blocked = tuple(
            f"dependency_not_compiled:{item}"
            for item in goal.depends_on
            if outcomes[item].status is not GoalStatus.COMPILED
        )
        if blocked:
            outcomes[goal.id] = GoalCompilation(goal.id, GoalStatus.BLOCKED, blocked)
            continue
        result = _with_unproven_anchors(compile_goal(goal, ctx), ctx)
        reference = ctx.references.binding(reference_mention(admission, goal.id))
        if reference is not None and reference.bound and reference.truncated:
            # The earlier answer showed only part of its rows, so them means only what was seen.
            result = replace(result, limitations=(*result.limitations, "prior_result_truncated"))
        if result.clarify:
            outcomes[goal.id] = GoalCompilation(
                goal.id, GoalStatus.CLARIFY, result.clarify, result.limitations
            )
            continue
        if result.unsupported or not result.specs:
            outcomes[goal.id] = GoalCompilation(
                goal.id,
                GoalStatus.UNSUPPORTED,
                result.unsupported or ("no_reviewed_compilation",),
                result.limitations,
            )
            continue
        batches, failure = _verified_batches(
            result.specs,
            confidence=goal.confidence,
            ctx=ctx,
            verifier=verifier,
            utterance=utterance,
            context=context,
        )
        violations = (
            failure
            if failure
            else verify_goal_semantics(
                goal,
                admission=admission,
                concepts=concepts,
                descriptors=manifest.descriptors,
                plans=tuple(batch.plan for batch in batches),
                default_lookback_seconds=default_lookback_seconds,
                anchors=ctx.anchors,
                references=ctx.references,
                evaluation_time=evaluation_time,
            )
        )
        outcomes[goal.id] = (
            GoalCompilation(goal.id, GoalStatus.UNSUPPORTED, violations, result.limitations)
            if violations
            else GoalCompilation(
                goal.id,
                GoalStatus.COMPILED,
                (),
                result.limitations,
                tuple(batches),
                confidence=goal.confidence,
            )
        )
    return ReasoningCompilation(
        form_digest=admission.form.digest,
        concept_digest=concepts.digest,
        anchor_digest=ctx.anchors.digest,
        goals=tuple(outcomes[goal.id] for goal in admission.form.goals),
        needs_continuation=admission.needs_continuation,
    )


UNIQUENESS_UNPROVEN = "anchor_uniqueness_unproven"
UNIQUENESS_REQUIREMENT = "anchor.uniqueness_unproven"


def _with_unproven_anchors(result: OperatorResult, ctx: CompileContext) -> OperatorResult:
    """State that an anchor matched under incomplete coverage may not be the only match.

    Every batch of the goal carries the notice requirement, so the frame, the plan, and
    the rendered answer agree on the limitation.
    """

    unproven = {
        binding.object_id
        for binding in ctx.anchors.bindings
        if binding.outcome is AnchorOutcome.BOUND
        and not binding.uniqueness_proven
        and binding.object_id is not None
    }
    if not unproven or not any(_reads_anchor(spec, unproven) for spec in result.specs):
        return result
    specs = tuple(
        replace(spec, evidence_requirements=(*spec.evidence_requirements, UNIQUENESS_REQUIREMENT))
        for spec in result.specs
    )
    return replace(result, specs=specs, limitations=(*result.limitations, UNIQUENESS_UNPROVEN))


def _reads_anchor(spec: PlanSpec, object_ids: set[str]) -> bool:
    for node in spec.nodes:
        definition = (
            node.arguments.get("definition") if node.kind is QueryNodeKind.OBJECT_SET else None
        )
        predicates = definition.get("predicates") if isinstance(definition, dict) else None
        for predicate in predicates or ():
            if (
                predicate.get("property") == "id"
                and predicate.get("operator") == "equals"
                and predicate.get("equals") in object_ids
            ):
                return True
    return False


def _verified_batches(
    specs: Sequence[PlanSpec],
    *,
    confidence: float,
    ctx: CompileContext,
    verifier: OntologyQueryPlanVerifier,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[list[CompiledBatch], tuple[str, ...]]:
    batches: list[CompiledBatch] = []
    for index, spec in enumerate(specs):
        try:
            shape = spec.output_shape
            reviewed_shape = isinstance(shape, SemanticOutputShape)
            frame = build_semantic_frame(
                SemanticFrameProposal(
                    operation=spec.operation,
                    subject_constraints=spec.subject_constraints,
                    measure_concepts=spec.measure_concepts,
                    temporal_scope={},
                    output_shape=(
                        shape
                        if isinstance(shape, SemanticOutputShape)
                        else SemanticOutputShape.RESOURCE_LIST
                    ),
                    evidence_requirements=spec.evidence_requirements,
                    investigation=None,
                    confidence=confidence,
                ),
                utterance=utterance,
                context=context,
            )
            if not reviewed_shape:
                frame = compiler_frame(frame, output_shape=str(shape))
            plan = _plan(spec, frame=frame, ctx=ctx)
            verifier.verify(plan, manifest=ctx.manifest)
            verify_frame_plan_alignment(frame, plan, descriptors=ctx.manifest.descriptors)
        except (PermissionError, ValueError) as exc:
            return [], (f"plan_verification_failed:{type(exc).__name__}",)
        batches.append(CompiledBatch(index=index, total=len(specs), frame=frame, plan=plan))
    return batches, ()


def compiler_frame(frame: SemanticProblemFrame, *, output_shape: str) -> SemanticProblemFrame:
    """Return the frame with a compiler-only output shape and its recomputed digest."""

    body: dict[str, Any] = {
        "schema_version": frame.schema_version,
        "operation": frame.operation.value,
        "subject_constraints": frame.subject_constraints,
        "measure_concepts": frame.measure_concepts,
        "temporal_scope": frame.temporal_scope,
        "output_shape": output_shape,
        "evidence_requirements": frame.evidence_requirements,
        "unresolved_terms": frame.unresolved_terms,
        "input_digest": frame.input_digest,
        "authority": frame.authority,
        "execution_authority": False,
    }
    if frame.investigation_intent_digest is not None:
        body["investigation_intent_digest"] = frame.investigation_intent_digest
    return SemanticProblemFrame.model_validate(
        {
            **frame.model_dump(mode="json", exclude={"frame_digest", "output_shape"}),
            "output_shape": output_shape,
            "frame_digest": content_digest(body),
        }
    )


def _plan(spec: PlanSpec, *, frame: SemanticProblemFrame, ctx: CompileContext) -> OntologyQueryPlan:
    manifest = ctx.manifest
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": frame.frame_digest,
        "purpose": ctx.purpose,
        "caller_role": manifest.principal_role.value,
        "nodes": [node.model_dump(mode="json") for node in spec.nodes],
        "output_node_ids": list(spec.output_node_ids),
        "execution_authority": False,
    }
    return OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=ctx.purpose,
        caller_role=manifest.principal_role.value,
        nodes=spec.nodes,
        output_node_ids=spec.output_node_ids,
        plan_digest=content_digest(body),
    )


__all__ = [
    "CompiledBatch",
    "GoalCompilation",
    "GoalStatus",
    "ReasoningCompilation",
    "compile_question_form",
]
