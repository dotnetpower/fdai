"""Shadow runner for the question-form path; it records digests and never answers.

The runner asks the model for a closed question form, binds quoted spans, admits
the form, grounds concepts over complete catalog shards, and compiles verified
plans. A proposal that breaks its contract gets one bounded repair call. It
returns an observation of dispositions and digests only. It never executes a
plan, renders an answer, or changes the production turn.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal, Protocol

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest

from .semantic_reasoning_admission import AdmissionDisposition, SpanAccounting
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
from .semantic_reasoning_form import SemanticQuestionForm
from .semantic_reasoning_proposal import FormInputHeldError
from .semantic_reasoning_repair import FormRepair, propose_with_repair

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
        repair: FormRepair | None = None,
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
    repairs_per_pass: int = 1

    def __post_init__(self) -> None:
        if not 1 <= self.max_form_passes <= MAX_FORM_PASSES:
            raise ValueError("shadow form passes MUST be in [1, 3]")
        if self.repairs_per_pass not in (0, 1):
            raise ValueError("shadow form repairs per pass MUST be 0 or 1")
        if not 0 <= self.max_concept_calls <= 64:
            raise ValueError("shadow concept calls MUST be in [0, 64]")


@dataclass(frozen=True, slots=True)
class ShadowGoal:
    """One goal outcome by closed status, typed reasons, and plan digests only."""

    goal_id: str
    status: str
    reasons: tuple[str, ...]
    plan_digests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShadowPass:
    """One form pass; it holds digests and closed values, never utterance text."""

    index: int
    disposition: str
    reasons: tuple[str, ...] = ()
    form_digest: str | None = None
    concept_digest: str | None = None
    anchor_digest: str | None = None
    goals: tuple[ShadowGoal, ...] = ()
    repair: str | None = None
    repaired_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReasoningShadowObservation:
    """Digest-only record of one shadow turn; it carries no utterance text.

    ``compilations`` is populated only when an evaluation harness explicitly asks
    to retain compiled plans; production shadow use never retains them. ``released``
    is true only when every pass was admitted and no continuation is pending, because
    an earlier pass compiles before the final pass accounts for every word; until then
    every compilation is provisional and no answer may use it.
    """

    passes: tuple[ShadowPass, ...]
    model_calls: int
    elapsed_ms: int
    continuation_pending: bool
    released: bool = False
    execution_authority: Literal[False] = False
    notes: tuple[str, ...] = field(default=())
    compilations: tuple[ReasoningCompilation, ...] = field(default=(), repr=False)

    def summary(self) -> dict[str, Any]:
        return {
            "passes": [
                {
                    "index": item.index,
                    "disposition": item.disposition,
                    "reasons": list(item.reasons),
                    "form_digest": item.form_digest,
                    "repair": item.repair,
                    "repaired_reasons": list(item.repaired_reasons),
                    "goals": [
                        {
                            "goal": goal.goal_id,
                            "status": goal.status,
                            "reasons": list(goal.reasons),
                            "plans": list(goal.plan_digests),
                        }
                        for goal in item.goals
                    ],
                }
                for item in self.passes
            ],
            "model_calls": self.model_calls,
            "elapsed_ms": self.elapsed_ms,
            "continuation_pending": self.continuation_pending,
            "released": self.released,
            "notes": list(self.notes),
        }


class _CountingModel:
    """Count every provider call as it starts, so a failing pass never hides one."""

    def __init__(self, inner: QuestionFormModel) -> None:
        self._inner = inner
        self.form_calls = 0
        self.concept_calls = 0

    @property
    def calls(self) -> int:
        return self.form_calls + self.concept_calls

    async def propose_form(self, **kwargs: Any) -> Mapping[str, Any] | None:
        self.form_calls += 1
        return await self._inner.propose_form(**kwargs)

    async def choose_concepts(self, **kwargs: Any) -> Mapping[str, Any] | None:
        self.concept_calls += 1
        return await self._inner.choose_concepts(**kwargs)


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
    retain_compilations: bool = False,
    clock: Callable[[], float] = time.monotonic,
    account_spans: bool = True,
) -> ReasoningShadowObservation:
    """Run successive bounded form passes and compile each admitted pass."""

    limits = budget or ShadowBudget()
    started = clock()
    counting = _CountingModel(model)
    passes: list[ShadowPass] = []
    compilations: list[ReasoningCompilation] = []
    prior_goals: tuple[dict[str, Any], ...] = ()
    catalogs = concept_catalogs(manifest.descriptors)
    pending = False
    notes: list[str] = []
    accounting = SpanAccounting(required=account_spans)
    for index in range(limits.max_form_passes):
        try:
            outcome = await _run_pass(
                counting,
                index=index,
                utterance=utterance,
                context=context,
                locale=locale,
                prior_goals=prior_goals,
                catalogs=catalogs,
                concept_budget=limits.max_concept_calls - counting.concept_calls,
                max_shard_bytes=limits.max_shard_bytes,
                repairs=limits.repairs_per_pass,
                resolver=resolver,
                accounting=accounting,
                compile_args={
                    "manifest": manifest,
                    "verifier": verifier,
                    "purpose": purpose,
                    "evaluation_time": evaluation_time,
                    "default_lookback_seconds": default_lookback_seconds,
                },
            )
        except Exception as exc:  # noqa: BLE001 - shadow work must never fail the turn
            held = exc.reason if isinstance(exc, FormInputHeldError) else None
            reason = held or f"shadow_error:{type(exc).__name__}"
            passes.append(ShadowPass(index, "input_held" if held else "shadow_error", (reason,)))
            if pending:
                notes.append("continuation_failed")
            break
        shadow_pass, goals, compilation, admitted = outcome
        passes.append(shadow_pass)
        if compilation is None:
            if pending:
                notes.append("continuation_failed")
            break
        if retain_compilations:
            compilations.append(compilation)
        pending = compilation.needs_continuation
        if not pending:
            break
        prior_goals = prior_goals + goals
        if admitted is not None:
            accounting = accounting.after(admitted)
    if pending and "continuation_failed" not in notes:
        notes.append("continuation_budget_exhausted")
    return ReasoningShadowObservation(
        passes=tuple(passes),
        model_calls=counting.calls,
        elapsed_ms=int((clock() - started) * 1000),
        continuation_pending=pending,
        released=bool(passes)
        and not pending
        and all(item.disposition == "admitted" for item in passes),
        notes=tuple(notes),
        compilations=tuple(compilations),
    )


async def _run_pass(
    model: QuestionFormModel,
    *,
    index: int,
    utterance: str,
    context: tuple[str, ...],
    locale: str,
    prior_goals: tuple[dict[str, Any], ...],
    catalogs: Any,
    concept_budget: int,
    max_shard_bytes: int,
    repairs: int,
    resolver: AnchorResolver | None,
    compile_args: dict[str, Any],
    accounting: SpanAccounting,
) -> tuple[
    ShadowPass,
    tuple[dict[str, Any], ...],
    ReasoningCompilation | None,
    SemanticQuestionForm | None,
]:
    """Run one bounded form pass; return the pass, its goal summaries, its compilation,
    and the admitted form, whose spans the next pass may rely on."""

    async def propose(repair: FormRepair | None = None) -> Mapping[str, Any] | None:
        return await model.propose_form(
            utterance=utterance,
            context=context,
            locale=locale,
            pass_index=index,
            prior_goals=prior_goals,
            repair=repair,
        )

    proposal = await propose_with_repair(
        propose, utterance=utterance, repairs=repairs, accounting=accounting
    )
    if proposal.resolution is None:
        return ShadowPass(index, "model_unavailable"), (), None, None
    resolution, admission = proposal.resolution, proposal.admission
    if resolution.form is None or admission is None:
        return (
            ShadowPass(
                index,
                "invalid",
                resolution.reasons,
                repair=proposal.repair,
                repaired_reasons=proposal.repaired_reasons,
            ),
            (),
            None,
            None,
        )
    if admission.disposition is not AdmissionDisposition.ADMITTED:
        return (
            ShadowPass(
                index,
                admission.disposition.value,
                admission.reasons,
                resolution.form.digest,
                repair=proposal.repair,
                repaired_reasons=proposal.repaired_reasons,
            ),
            (),
            None,
            None,
        )
    receipt = await _select(
        model,
        admission=admission,
        catalogs=catalogs,
        utterance=utterance,
        max_calls=concept_budget,
        max_shard_bytes=max_shard_bytes,
    )
    anchors = await bind_anchors(admission, resolver, utterance=utterance)
    compilation = compile_question_form(
        admission,
        concepts=receipt,
        anchors=anchors,
        utterance=utterance,
        context=context,
        **compile_args,
    )
    goals = tuple(
        goal.model_dump(mode="json", include={"level", "operation", "subject_scope"})
        for goal in resolution.form.goals
    )
    shadow_pass = ShadowPass(
        index,
        "admitted",
        (),
        resolution.form.digest,
        receipt.digest,
        anchors.digest,
        tuple(
            ShadowGoal(
                goal.goal_id,
                goal.status.value,
                goal.reasons,
                tuple(batch.plan.plan_digest for batch in goal.batches),
            )
            for goal in compilation.goals
        ),
        proposal.repair,
        proposal.repaired_reasons,
    )
    return shadow_pass, goals, compilation, resolution.form


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
