"""Shadow runner for the question-form path; it records digests and never answers.

The runner asks the model for a closed question form, binds quoted spans, admits
the form, grounds concepts over complete catalog shards, and compiles verified
plans. It returns an observation of dispositions and digests only. It never
executes a plan, renders an answer, or changes the production turn.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal, Protocol

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest

from .semantic_reasoning_admission import AdmissionDisposition, admit_question_form
from .semantic_reasoning_binding import AnchorResolver, bind_anchors
from .semantic_reasoning_compiler import ReasoningCompilation, compile_question_form
from .semantic_reasoning_concepts import (
    ConceptSelectionReceipt,
    ConceptShard,
    accept_concept_selection,
    apply_runoff,
    concept_catalogs,
    plan_concept_selection,
    runoff_requests,
    shard_answer_valid,
)
from .semantic_reasoning_proposal import resolve_question_form

MAX_FORM_PASSES = 3


class QuestionFormModel(Protocol):
    async def propose_form(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        locale: str,
        pass_index: int,
        prior_goals: tuple[dict[str, Any], ...],
    ) -> Mapping[str, Any] | None: ...

    async def choose_concepts(
        self,
        *,
        utterance: str,
        mentions: tuple[dict[str, Any], ...],
        shard: ConceptShard,
    ) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class ShadowBudget:
    """Per-turn ceilings reserved before the shadow path starts."""

    max_form_passes: int = MAX_FORM_PASSES
    max_concept_calls: int = 8
    max_shard_bytes: int = 12 * 1024

    def __post_init__(self) -> None:
        if not 1 <= self.max_form_passes <= MAX_FORM_PASSES:
            raise ValueError("shadow form passes MUST be in [1, 3]")
        if not 0 <= self.max_concept_calls <= 64:
            raise ValueError("shadow concept calls MUST be in [0, 64]")


@dataclass(frozen=True, slots=True)
class ShadowPass:
    index: int
    disposition: str
    reasons: tuple[str, ...] = ()
    form_digest: str | None = None
    concepts: ConceptSelectionReceipt | None = None
    compilation: ReasoningCompilation | None = None


@dataclass(frozen=True, slots=True)
class ReasoningShadowObservation:
    """Digest-only record of one shadow turn; it carries no utterance text."""

    passes: tuple[ShadowPass, ...]
    model_calls: int
    elapsed_ms: int
    continuation_pending: bool
    execution_authority: Literal[False] = False
    notes: tuple[str, ...] = field(default=())

    def summary(self) -> dict[str, Any]:
        return {
            "passes": [
                {
                    "index": item.index,
                    "disposition": item.disposition,
                    "reasons": list(item.reasons),
                    "form_digest": item.form_digest,
                    "goals": [
                        {
                            "goal": goal.goal_id,
                            "status": goal.status.value,
                            "reasons": list(goal.reasons),
                            "plans": [batch.plan.plan_digest for batch in goal.batches],
                        }
                        for goal in (item.compilation.goals if item.compilation else ())
                    ],
                }
                for item in self.passes
            ],
            "model_calls": self.model_calls,
            "elapsed_ms": self.elapsed_ms,
            "continuation_pending": self.continuation_pending,
            "notes": list(self.notes),
        }


async def run_reasoning_shadow(
    *,
    model: QuestionFormModel,
    utterance: str,
    context: tuple[str, ...],
    locale: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    purpose: str,
    evaluation_time: datetime,
    default_lookback_seconds: int,
    budget: ShadowBudget | None = None,
    resolver: AnchorResolver | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ReasoningShadowObservation:
    """Run successive bounded form passes and compile each admitted pass."""

    limits = budget or ShadowBudget()
    started = clock()
    calls = 0
    concept_calls = 0
    passes: list[ShadowPass] = []
    prior_goals: tuple[dict[str, Any], ...] = ()
    catalogs = concept_catalogs(manifest.descriptors)
    pending = False
    for index in range(limits.max_form_passes):
        calls += 1
        raw = await model.propose_form(
            utterance=utterance,
            context=context,
            locale=locale,
            pass_index=index,
            prior_goals=prior_goals,
        )
        if raw is None:
            passes.append(ShadowPass(index, "model_unavailable"))
            break
        resolution = resolve_question_form(raw, utterance=utterance)
        if resolution.form is None:
            passes.append(ShadowPass(index, "invalid", resolution.reasons))
            break
        admission = admit_question_form(resolution.form, utterance=utterance)
        if admission.disposition is not AdmissionDisposition.ADMITTED:
            passes.append(
                ShadowPass(
                    index,
                    admission.disposition.value,
                    admission.reasons,
                    resolution.form.digest,
                )
            )
            break
        receipt = await _select(
            model,
            admission=admission,
            catalogs=catalogs,
            utterance=utterance,
            max_calls=limits.max_concept_calls - concept_calls,
            max_shard_bytes=limits.max_shard_bytes,
        )
        concept_calls += receipt.model_calls
        calls += receipt.model_calls
        anchors = await bind_anchors(admission, resolver)
        compilation = compile_question_form(
            admission,
            concepts=receipt,
            anchors=anchors,
            manifest=manifest,
            verifier=verifier,
            purpose=purpose,
            evaluation_time=evaluation_time,
            default_lookback_seconds=default_lookback_seconds,
            utterance=utterance,
            context=context,
        )
        passes.append(
            ShadowPass(index, "admitted", (), resolution.form.digest, receipt, compilation)
        )
        pending = admission.needs_continuation
        if not pending:
            break
        prior_goals = prior_goals + tuple(
            goal.model_dump(mode="json", include={"level", "operation", "subject_scope"})
            for goal in resolution.form.goals
        )
    return ReasoningShadowObservation(
        passes=tuple(passes),
        model_calls=calls,
        elapsed_ms=int((clock() - started) * 1000),
        continuation_pending=pending,
        notes=("continuation_budget_exhausted",) if pending else (),
    )


async def _select(
    model: QuestionFormModel,
    *,
    admission: Any,
    catalogs: Any,
    utterance: str,
    max_calls: int,
    max_shard_bytes: int,
) -> ConceptSelectionReceipt:
    """Present every planned shard to the model, then accept verified choices."""

    plan = plan_concept_selection(
        admission,
        catalogs=catalogs,
        max_model_calls=max_calls,
        max_shard_bytes=max_shard_bytes,
    )
    answers: list[Mapping[str, Any] | None] = []
    retries = 0
    for request in plan.requests:
        answer = await model.choose_concepts(
            utterance=utterance, mentions=request.mentions, shard=request.shard
        )
        # One bounded re-ask for a malformed shard answer; a second failure stays invalid.
        if not shard_answer_valid(answer, request) and (len(plan.requests) + retries < max_calls):
            retries += 1
            answer = await model.choose_concepts(
                utterance=utterance, mentions=request.mentions, shard=request.shard
            )
        answers.append(answer)
    receipt = accept_concept_selection(plan, answers)
    receipt = replace(receipt, model_calls=receipt.model_calls + retries)
    runoff = runoff_requests(plan, receipt)
    if not runoff or receipt.model_calls + len(runoff) > max_calls:
        return receipt
    runoff_answers = [
        await model.choose_concepts(
            utterance=utterance, mentions=request.mentions, shard=request.shard
        )
        for request in runoff
    ]
    return apply_runoff(receipt, runoff, runoff_answers)


__all__ = [
    "MAX_FORM_PASSES",
    "QuestionFormModel",
    "ReasoningShadowObservation",
    "ShadowBudget",
    "ShadowPass",
    "run_reasoning_shadow",
]
