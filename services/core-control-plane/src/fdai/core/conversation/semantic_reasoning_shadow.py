"""Shadow runner for the question-form path; it records digests and never answers.

The runner asks the model for a closed question form, binds quoted spans, admits
the form, grounds concepts over complete catalog shards, and compiles verified
plans. A proposal that breaks its contract gets one bounded repair call. It
returns an observation of dispositions and digests only. It never executes a
plan, renders an answer, or changes the production turn.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal, Protocol

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest

from .semantic_reasoning_admission import (
    AdmissionDisposition,
    SpanAccounting,
    admit_question_form,
)
from .semantic_reasoning_binding import AnchorResolver, bind_anchors
from .semantic_reasoning_compiler import ReasoningCompilation, compile_question_form
from .semantic_reasoning_concepts import (
    ConceptSelectionReceipt,
    ConceptShard,
    accept_concept_selection,
    agree_concepts,
    apply_runoff,
    concept_catalogs,
    plan_concept_selection,
    runoff_requests,
    shard_answer_valid,
)
from .semantic_reasoning_direction import (
    DirectionQuestion,
    settle_directions,
)
from .semantic_reasoning_form import SemanticQuestionForm
from .semantic_reasoning_handles import (
    HandleScope,
    ResultSetHandle,
    bind_references,
    reference_anchors,
)
from .semantic_reasoning_kinds import ground_kinds
from .semantic_reasoning_proposal import (
    FormInputHeldError,
    FormResolution,
    resolve_question_form,
)
from .semantic_reasoning_relabel import relabel_mentions
from .semantic_reasoning_repair import (
    FormProposal,
    FormRepair,
    propose_with_repair,
    repair_keeps_operands,
)
from .semantic_reasoning_review import (
    FormReview,
    describe_uncovered,
    describe_unexpressible,
    literal_disagreements,
    merged_constraints,
    quoted_form,
    resolve_extraction,
    review_forms,
    unacknowledged_constraints,
    uncovered_constraints,
)
from .semantic_reasoning_shape import form_shape

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
        second: bool = False,
    ) -> Mapping[str, Any] | None: ...

    async def extract_constraints(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        locale: str,
    ) -> Mapping[str, Any] | None: ...

    async def check_direction(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        locale: str,
        question: DirectionQuestion,
        tiebreak: bool = False,
    ) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class ShadowBudget:
    """Per-turn ceilings reserved before the shadow path starts."""

    max_form_passes: int = MAX_FORM_PASSES
    max_concept_calls: int = 16
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
    reference_digest: str | None = None
    # Mentions grounded in the sibling kind lane, whose domain the form now carries.
    regrounded: tuple[str, ...] = ()
    shape: tuple[str, ...] = ()
    # Goals whose relation roles follow two blind readers that outvoted the proposer.
    direction_swaps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReasoningShadowObservation:
    """Digest-only record of one shadow turn; it carries no utterance text.

    ``compilations`` is populated only when an evaluation harness explicitly asks
    to retain compiled plans; production shadow use never retains them. ``released``
    is true only when every pass was admitted, no continuation is pending, and every
    constraint the independent extraction found lies in a span of the admitted forms
    that states it, because an earlier pass compiles before the final pass accounts for
    every word and before the review; until then every compilation is provisional and
    no answer may use it.
    """

    passes: tuple[ShadowPass, ...]
    model_calls: int
    elapsed_ms: int
    continuation_pending: bool
    released: bool = False
    review: str | None = None
    review_reasons: tuple[str, ...] = ()
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
                    "reference_digest": item.reference_digest,
                    "repair": item.repair,
                    "repaired_reasons": list(item.repaired_reasons),
                    "regrounded": list(item.regrounded),
                    "direction_swaps": list(item.direction_swaps),
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
            "review": self.review,
            "review_reasons": list(self.review_reasons),
            "notes": list(self.notes),
        }


class _CountingModel:
    """Count every provider call as it starts, so a failing pass never hides one."""

    def __init__(self, inner: QuestionFormModel) -> None:
        self._inner = inner
        self.form_calls = 0
        self.concept_calls = 0
        self.review_calls = 0
        self.direction_calls = 0

    @property
    def calls(self) -> int:
        return self.form_calls + self.concept_calls + self.review_calls + self.direction_calls

    async def propose_form(self, **kwargs: Any) -> Mapping[str, Any] | None:
        self.form_calls += 1
        return await self._inner.propose_form(**kwargs)

    async def choose_concepts(self, **kwargs: Any) -> Mapping[str, Any] | None:
        self.concept_calls += 1
        return await self._inner.choose_concepts(**kwargs)

    async def extract_constraints(self, **kwargs: Any) -> Mapping[str, Any] | None:
        self.review_calls += 1
        return await self._inner.extract_constraints(**kwargs)

    async def check_direction(self, **kwargs: Any) -> Mapping[str, Any] | None:
        self.direction_calls += 1
        return await self._inner.check_direction(**kwargs)


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
    handles: tuple[ResultSetHandle, ...] = (),
    handle_scope: HandleScope | None = None,
) -> ReasoningShadowObservation:
    """Run successive bounded form passes and compile each admitted pass."""

    if handle_scope is not None and handle_scope.manifest_digest != manifest.manifest_digest:
        raise ValueError("handle scope MUST name the manifest this turn compiles against")
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
    compile_args: dict[str, Any] = {
        "manifest": manifest,
        "verifier": verifier,
        "purpose": purpose,
        "evaluation_time": evaluation_time,
        "default_lookback_seconds": default_lookback_seconds,
        "handles": handles,
        "handle_scope": handle_scope,
    }
    admitted_forms: list[SemanticQuestionForm] = []
    # The extraction reads only the question, so it runs beside the form passes.
    extraction = asyncio.ensure_future(
        _extract(counting, utterance=utterance, context=context, locale=locale)
    )
    try:
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
                    compile_args=compile_args,
                )
            except Exception as exc:  # noqa: BLE001 - shadow work must never fail the turn
                passes.append(_failed_pass(index, exc))
                if pending:
                    notes.append("continuation_failed")
                break
            shadow_pass, goals, compilation, admitted = outcome
            passes.append(shadow_pass)
            if admitted is not None and shadow_pass.disposition == "admitted":
                admitted_forms.append(admitted)
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
        complete = (
            bool(passes) and not pending and all(item.disposition == "admitted" for item in passes)
        )
        review: FormReview | None = None
        if complete:
            raw, failure = await extraction
            review = (
                FormReview("unavailable", (failure,))
                if failure is not None
                else review_forms(admitted_forms, raw, utterance=utterance)
            )
            if review.outcome == "invalid":
                # An unusable extraction, such as a quote not in the question, is read once
                # more by the same blind extractor; its answer is reviewed by the same rules.
                notes.append("review_reextracted")
                raw, failure = await _extract(
                    counting, utterance=utterance, context=context, locale=locale
                )
                review = (
                    FormReview("unavailable", (failure,))
                    if failure is not None
                    else review_forms(admitted_forms, raw, utterance=utterance)
                )
            repair = _review_repair(
                review, raw, admitted_forms, passes, limits, utterance=utterance
            )
            if repair is not None:
                try:
                    shadow_pass, _goals, compilation, admitted = await _run_pass(
                        counting,
                        index=len(passes),
                        utterance=utterance,
                        context=context,
                        locale=locale,
                        prior_goals=(),
                        catalogs=catalogs,
                        concept_budget=limits.max_concept_calls - counting.concept_calls,
                        max_shard_bytes=limits.max_shard_bytes,
                        repairs=0,
                        resolver=resolver,
                        compile_args=compile_args,
                        accounting=SpanAccounting(required=account_spans),
                        review_repair=repair,
                    )
                except Exception as exc:  # noqa: BLE001 - shadow work must never fail the turn
                    shadow_pass, compilation, admitted = _failed_pass(len(passes), exc), None, None
                passes.append(shadow_pass)
                repaired_whole = compilation is None or not compilation.needs_continuation
                if (
                    admitted is not None
                    and shadow_pass.disposition == "admitted"
                    and repaired_whole
                ):
                    review = review_forms((admitted,), raw, utterance=utterance)
                    if retain_compilations and compilation is not None:
                        compilations = [compilation]
                else:
                    # A repair that reads only part of the question releases nothing.
                    complete = False
                    pending = pending or not repaired_whole
        else:
            extraction.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await extraction
        return ReasoningShadowObservation(
            passes=tuple(passes),
            model_calls=counting.calls,
            elapsed_ms=int((clock() - started) * 1000),
            continuation_pending=pending,
            released=complete and review is not None and review.faithful,
            review=review.outcome if review is not None else None,
            review_reasons=review.reasons if review is not None else (),
            notes=tuple(notes),
            compilations=tuple(compilations),
        )
    finally:
        # A cancelled or failed turn never leaves the extraction's provider call running.
        if not extraction.done():
            extraction.cancel()
        await asyncio.gather(extraction, return_exceptions=True)


def _failed_pass(index: int, exc: Exception) -> ShadowPass:
    """Record a pass that raised, as held input or a shadow error, instead of failing."""

    held = exc.reason if isinstance(exc, FormInputHeldError) else None
    reason = held or f"shadow_error:{type(exc).__name__}"
    return ShadowPass(index, "input_held" if held else "shadow_error", (reason,))


@dataclass(frozen=True, slots=True)
class _ReviewRepair:
    """The admitted form the review found incomplete, and the constraints it must state."""

    previous: Mapping[str, Any]
    typed: SemanticQuestionForm
    violations: tuple[str, ...]
    reasons: tuple[str, ...]


def _review_repair(
    review: FormReview,
    raw: Mapping[str, Any] | None,
    forms: list[SemanticQuestionForm],
    passes: list[ShadowPass],
    limits: ShadowBudget,
    *,
    utterance: str,
) -> _ReviewRepair | None:
    """Return one repair for a single admitted pass whose review found uncovered words."""

    if review.outcome != "unfaithful" or raw is None or limits.repairs_per_pass < 1:
        return None
    if len(forms) != 1 or len(passes) != 1:
        return None
    extraction = resolve_extraction(raw, utterance)
    if extraction is None:
        return None
    uncovered = uncovered_constraints(forms, extraction, utterance)
    unacknowledged = unacknowledged_constraints(forms, extraction, utterance)
    # A repair only adds information, so it can neither split a mention that merged a
    # restriction with another constraint nor move a literal; the turn is held instead.
    if not (uncovered or unacknowledged) or (
        merged_constraints(forms, extraction) or literal_disagreements(forms, extraction)
    ):
        return None
    violations = (
        *(describe_uncovered(item, utterance, forms) for item in uncovered),
        *(describe_unexpressible(item, utterance) for item in unacknowledged),
    )
    return _ReviewRepair(
        previous=quoted_form(forms[0], utterance),
        typed=forms[0],
        violations=tuple(dict.fromkeys(violations)),
        reasons=review.reasons,
    )


async def _propose_review_repair(
    propose: Callable[..., Any],
    repair: _ReviewRepair,
    *,
    utterance: str,
    accounting: SpanAccounting,
) -> FormProposal:
    """Ask the proposer to state the uncovered constraints, adding information only."""

    raw = await propose(repair=FormRepair(previous=repair.previous, violations=repair.violations))
    if raw is None:
        return FormProposal(None, None, "unavailable", repair.reasons)
    resolution = resolve_question_form(raw, utterance=utterance)
    if resolution.form is None:
        return FormProposal(resolution, None, "invalid", repair.reasons)
    form = relabel_mentions(repair.typed, resolution.form)
    resolution = replace(resolution, form=form)
    if not repair_keeps_operands(
        repair.previous,
        form,
        utterance=utterance,
        typed=repair.typed,
        extension_only=True,
    ):
        dropped = FormResolution(None, ("review_repair_operand_dropped",))
        return FormProposal(dropped, None, "operand_dropped", repair.reasons)
    admission = admit_question_form(form, utterance=utterance, accounting=accounting)
    if admission.disposition is AdmissionDisposition.INVALID and all(
        reason.startswith("span_unaccounted:") for reason in admission.reasons
    ):
        # This is the turn's one repair, and the review reads the repaired form again, so
        # a word it leaves unplaced is judged there, as after a first-pass repair.
        relaxed = admit_question_form(
            form, utterance=utterance, accounting=SpanAccounting(required=False)
        )
        return FormProposal(resolution, relaxed, "review_applied_unaccounted", repair.reasons)
    return FormProposal(resolution, admission, "review_applied", repair.reasons)


async def _extract(
    model: _CountingModel,
    *,
    utterance: str,
    context: tuple[str, ...],
    locale: str,
) -> tuple[Mapping[str, Any] | None, str | None]:
    """Ask the independent extractor for every constraint the question states."""

    try:
        raw = await model.extract_constraints(utterance=utterance, context=context, locale=locale)
    except Exception as exc:  # noqa: BLE001 - an unavailable review releases nothing
        held = exc.reason if isinstance(exc, FormInputHeldError) else None
        return None, held or f"review_error:{type(exc).__name__}"
    return raw, None


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
    review_repair: _ReviewRepair | None = None,
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

    proposal = (
        await propose_with_repair(
            propose, utterance=utterance, repairs=repairs, accounting=accounting
        )
        if review_repair is None
        else await _propose_review_repair(
            propose, review_repair, utterance=utterance, accounting=accounting
        )
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
                shape=form_shape(resolution.form),
            ),
            (),
            None,
            None,
        )

    def select(lane: Any, calls: int) -> Any:
        return _select(
            model,
            admission=lane,
            catalogs=catalogs,
            utterance=utterance,
            max_calls=calls,
            max_shard_bytes=max_shard_bytes,
        )

    receipt = await select(admission, concept_budget)
    grounding = await ground_kinds(
        admission,
        receipt,
        catalogs=catalogs,
        utterance=utterance,
        select=select,
        choose=lambda mentions, shard, second: model.choose_concepts(
            utterance=utterance, mentions=mentions, shard=shard, second=second
        ),
        budget=concept_budget - receipt.model_calls,
    )
    # One grounded form replaces the proposal everywhere after this point.
    admission, receipt = grounding.admission, grounding.receipt
    settled = await settle_directions(
        admission.form,
        utterance=utterance,
        descriptors=compile_args["manifest"].descriptors,
        check=lambda question, tiebreak: model.check_direction(
            utterance=utterance,
            context=context,
            locale=locale,
            question=question,
            tiebreak=tiebreak,
        ),
    )
    reasons = settled.reasons
    if settled.swapped:
        admission = admit_question_form(settled.form, utterance=utterance, accounting=accounting)
        if admission.disposition is not AdmissionDisposition.ADMITTED:
            reasons = admission.reasons
    form = admission.form
    if reasons:
        return ShadowPass(index, "direction_held", reasons, shape=form_shape(form)), (), None, None
    anchors = await bind_anchors(admission, resolver, utterance=utterance)
    arguments = dict(compile_args)
    references = bind_references(
        admission, arguments.pop("handles", ()), arguments.pop("handle_scope", None)
    )
    anchors = reference_anchors(anchors, references)
    compilation = compile_question_form(
        admission,
        concepts=receipt,
        anchors=anchors,
        references=references,
        utterance=utterance,
        context=context,
        **arguments,
    )
    goals = tuple(
        goal.model_dump(mode="json", include={"level", "operation", "subject_scope"})
        for goal in form.goals
    )
    shadow_pass = ShadowPass(
        index,
        "admitted",
        (),
        form.digest,
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
        references.digest if references.bindings else None,
        grounding.regrounded,
        form_shape(form),
        settled.swapped,
    )
    return shadow_pass, goals, compilation, form


async def _select(
    model: QuestionFormModel,
    *,
    admission: Any,
    catalogs: Any,
    utterance: str,
    max_calls: int,
    max_shard_bytes: int,
) -> ConceptSelectionReceipt:
    """Ground every concept with two blind choosers of different model families.

    Each chooser sees every planned shard and resolves its own runoff; a binding stands
    only where both choose the same values, so no single reader grounds a concept.
    """

    primary, second = await asyncio.gather(
        _select_one(
            model,
            admission=admission,
            catalogs=catalogs,
            utterance=utterance,
            max_calls=max_calls // 2,
            max_shard_bytes=max_shard_bytes,
            second=False,
        ),
        _select_one(
            model,
            admission=admission,
            catalogs=catalogs,
            utterance=utterance,
            max_calls=max_calls // 2,
            max_shard_bytes=max_shard_bytes,
            second=True,
        ),
    )
    return agree_concepts(primary, second)


async def _select_one(
    model: QuestionFormModel,
    *,
    admission: Any,
    catalogs: Any,
    utterance: str,
    max_calls: int,
    max_shard_bytes: int,
    second: bool,
) -> ConceptSelectionReceipt:
    """Present every planned shard to one chooser, then accept verified choices."""

    plan = plan_concept_selection(
        admission,
        catalogs=catalogs,
        max_model_calls=max_calls,
        max_shard_bytes=max_shard_bytes,
    )

    async def choose(request: Any) -> Mapping[str, Any] | None:
        return await model.choose_concepts(
            utterance=utterance, mentions=request.mentions, shard=request.shard, second=second
        )

    answers: list[Mapping[str, Any] | None] = []
    retries = 0
    for request in plan.requests:
        answer = await choose(request)
        # One bounded re-ask for a malformed shard answer; a second failure stays invalid.
        if not shard_answer_valid(answer, request) and (len(plan.requests) + retries < max_calls):
            retries += 1
            answer = await choose(request)
        answers.append(answer)
    receipt = accept_concept_selection(plan, answers)
    receipt = replace(receipt, model_calls=receipt.model_calls + retries)
    runoff = runoff_requests(plan, receipt)
    if not runoff or receipt.model_calls + len(runoff) > max_calls:
        return receipt
    runoff_answers = [await choose(request) for request in runoff]
    return apply_runoff(receipt, runoff, runoff_answers)


__all__ = [
    "MAX_FORM_PASSES",
    "QuestionFormModel",
    "ReasoningShadowObservation",
    "ShadowBudget",
    "ShadowPass",
    "run_reasoning_shadow",
]
