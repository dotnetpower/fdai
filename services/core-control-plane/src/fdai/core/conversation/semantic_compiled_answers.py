"""Answer a turn from a released question-form compilation in the local profile.

The form path reads the question beside the judgment, with its own provider calls, deadline,
and anchor reads scoped like the turn's executor. Only a released path whose single goal
compiled into one verified batch answers; every other outcome leaves the current path to
answer the turn. The path records content-free decision events and grants no authority.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from collections.abc import Callable, Mapping, MutableSequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryPlan,
    project_intent_graph,
)

from fdai.core.conversation.result_handle_store import ResultHandleBinding, ResultHandleStore
from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.acl import ProjectionRequest

from .adaptive_call_scope import bind_adaptive_model_budget
from .intent_graph import build_intent_graph
from .model_observation import ConversationModelObservation
from .semantic_compiled_selection import (
    decision_details,
    decline_decision,
    held_word_recovery_reasons,
    resample_worthy,
    single_compiled_batch,
)
from .semantic_manifest import semantic_principal_scope_digest
from .semantic_plan_coverage import plan_reads_only_a_list
from .semantic_planning_alignment import verify_frame_plan_alignment
from .semantic_planning_models import (
    SemanticPlanningDisposition,
    SemanticPlanningOutcome,
    hold_details,
)
from .semantic_planning_support import _outcome, _refresh_object_set_cutoffs
from .semantic_reasoning_admission import FormAdmission
from .semantic_reasoning_ambiguity import AmbiguityReader, ambiguity_verdict
from .semantic_reasoning_binding import GatewayAnchorResolver
from .semantic_reasoning_compiler import CompiledBatch
from .semantic_reasoning_handles import ReferenceReceipt
from .semantic_reasoning_shadow import (
    QuestionFormModel,
    ReasoningShadowObservation,
    ShadowBudget,
    run_reasoning_shadow,
)
from .semantic_stored_result_handles import StoredReferenceContext, bind_stored_references
from .session import Principal

_LOGGER = logging.getLogger(__name__)
COMPILED_PLAN_SOURCE = "compiled_question_form"
_MAX_EVENT_ITEMS = 16
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
        ambiguity: Callable[[], concurrent.futures.Future[Mapping[str, Any] | None]] | None = None,
    ) -> None:
        self._future = future
        self._collector = collector
        self._ambiguity = ambiguity
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

        selected = self._select(observations)
        if selected is None:
            return None
        return self._answer(*selected, manifest_digest=manifest_digest)

    def primary_read_outcome(
        self, *, manifest_digest: str, observations: MutableSequence[Any]
    ) -> SemanticPlanningOutcome | None:
        """Reuse a typed-only direct read agreed by both blind readers, never their authority."""

        if not self.typed_only:
            return None
        try:
            observation = self._future.result(timeout=max(0.0, self._deadline - self._clock()))
        except Exception:  # noqa: BLE001 - the ordinary consumer records the typed failure
            self._select(observations)
            return typed_only_outcome(self, manifest_digest=manifest_digest)
        if not observation.primary_read:
            return None
        compiled = self.outcome(manifest_digest=manifest_digest, observations=observations)
        return compiled or typed_only_outcome(self, manifest_digest=manifest_digest)

    def outcome_over_clarification(
        self,
        *,
        manifest_digest: str,
        observations: MutableSequence[Any],
    ) -> SemanticPlanningOutcome | None:
        """Answer over the judgment's clarification only when a third reader finds one reading.

        The released reading must first pass every selection rule of ``outcome``. Then a
        reader of another model family, which sees neither reading, says whether the
        question has one plausible reading; any other answer, no answer, or a failure
        leaves the clarification to end the turn. The plan takes the gateway's cutoff only
        after that verdict, because the gateway accepts an ``as_of`` only within seconds of
        its own cutoff and the reader may take longer.
        """

        selected = self._select(observations)
        if selected is None:
            return None
        verdict = "unavailable"
        if self._ambiguity is not None:
            recorded = len(self._collector.observations)
            future = self._ambiguity()
            try:
                verdict = ambiguity_verdict(
                    future.result(timeout=max(0.0, self._deadline - self._clock()))
                )
            except concurrent.futures.TimeoutError:
                future.cancel()
                verdict = "timeout"
            except Exception as exc:  # noqa: BLE001 - provider details stay inside the adapter
                future.cancel()
                verdict = f"failed:{type(exc).__name__}"
            finally:
                observations.extend(self._collector.observations[recorded:])
        _LOGGER.info("semantic_compiled_answer_ambiguity", extra={"verdict": verdict})
        if verdict != "one":
            self.decision = "clarification"
            _log_completion("clarified", observation=selected[2])
            return None
        return self._answer(*selected, manifest_digest=manifest_digest)

    def _select(
        self, observations: MutableSequence[Any]
    ) -> tuple[CompiledBatch, float, ReasoningShadowObservation] | None:
        """Consume the path once and return its one answerable batch, or record the decline."""

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
        selected = single_compiled_batch(observation)
        if isinstance(selected, str):
            self._unsupported = held_word_recovery_reasons(observation)
            self.decision = decline_decision(selected, observation)
            self.details = decision_details(self.decision, observation)
            _log_completion("declined", observation=observation, decline_reason=selected)
            return None
        batch, confidence = selected
        return batch, confidence, observation

    def _answer(
        self,
        batch: CompiledBatch,
        confidence: float,
        observation: ReasoningShadowObservation,
        *,
        manifest_digest: str,
    ) -> SemanticPlanningOutcome | None:
        """Stamp the selected plan with the gateway's current cutoff, verify it, and answer."""

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

    def veto(
        self,
        plan_source: str,
        *,
        manifest_digest: str,
        plan: OntologyQueryPlan | None = None,
    ) -> SemanticPlanningOutcome | None:
        """Hold a current-path plan that answers a narrower question than the typed reading.

        A reviewed reading that no builder can compile names what the question needs, and
        any parsed reading may show a grouping, state, relation, or schema level that one
        filtered list never reads: neither a list recovered from the judgment's words nor
        any other plan that reads only a filtered list may then answer.
        """

        if not self._unsupported:
            return None
        narrower = plan is not None and plan_reads_only_a_list(plan)
        if plan_source not in _LEXICAL_PLAN_SOURCES and not narrower:
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
        ambiguity_reader: AmbiguityReader | None = None,
    ) -> None:
        self._model = model
        self._ambiguity_reader = ambiguity_reader
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
        stored_reference_context: StoredReferenceContext | None = None,
        result_handle_store: ResultHandleStore | None = None,
    ) -> CompiledAnswerTicket | None:
        """Schedule the form path; a break-glass principal or other purpose is skipped."""

        if purpose != self._purpose:
            return None
        try:
            role = CeilingRole(principal.role)
        except ValueError:
            return None
        projection_request = ProjectionRequest(
            caller_role=role,
            declared_purposes=frozenset({purpose}),
            principal_scope_digest=semantic_principal_scope_digest(
                principal=principal, purpose=purpose
            ),
        )
        resolver = GatewayAnchorResolver(
            self._gateway,
            projection_request=projection_request,
            purpose=purpose,
            as_of=self._clock,
        )
        stored_reference_binder = None
        stored_context = stored_reference_context
        active_store = result_handle_store or (
            stored_context.store if stored_context is not None else None
        )
        if stored_context is not None and active_store is not None and stored_context.references:
            binding = ResultHandleBinding(
                deployment_scope_digest=manifest.release_digest,
                principal_digest=manifest.manifest_digest,
                conversation_id=stored_context.session_id,
                purpose=purpose,
                manifest_digest=manifest.manifest_digest,
                now=self._clock(),
            )

            async def bind_stored(admission: FormAdmission) -> ReferenceReceipt | None:
                return await bind_stored_references(
                    admission,
                    references=stored_context.references,
                    store=active_store,
                    binding=binding,
                    gateway=self._gateway,
                    projection_request=projection_request,
                    purpose=purpose,
                    as_of=self._clock,
                )

            stored_reference_binder = bind_stored
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
                stored_reference_binder=stored_reference_binder,
            ),
            self._owner_loop,
        )
        reader = self._ambiguity_reader

        def ambiguity() -> concurrent.futures.Future[Mapping[str, Any] | None]:
            async def ask() -> Mapping[str, Any] | None:
                if reader is None:
                    return None
                async with bind_adaptive_model_budget(collector):
                    return await reader.check_ambiguity(
                        utterance=utterance, context=context, locale=locale
                    )

            return asyncio.run_coroutine_threadsafe(ask(), self._owner_loop)

        return CompiledAnswerTicket(
            future,
            collector,
            deadline_seconds=self._settings.deadline_seconds,
            manifest=manifest,
            verifier=verifier,
            cutoff=self._clock,
            typed_only=self._settings.typed_only,
            ambiguity=ambiguity if reader is not None else None,
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


def settled_clarification(
    ticket: CompiledAnswerTicket | None,
    clarified: SemanticPlanningOutcome,
    manifest_digest: str,
    observations: MutableSequence[Any],
) -> SemanticPlanningOutcome:
    """Keep the judgment's clarification unless a third reader finds one plausible reading."""

    settled = (
        ticket.outcome_over_clarification(
            manifest_digest=manifest_digest, observations=observations
        )
        if ticket is not None
        else None
    )
    return settled if settled is not None else clarified


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
        if not resample_worthy(first):
            return first
        second = await run_reasoning_shadow(model=model, retain_compilations=True, **arguments)
    if isinstance(single_compiled_batch(second), str):
        return replace(first, notes=(*first.notes, "form_resampled_unanswered"))
    return replace(
        second,
        model_calls=first.model_calls + second.model_calls,
        elapsed_ms=first.elapsed_ms + second.elapsed_ms,
        notes=(*second.notes, "form_resampled"),
    )


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
    "settled_clarification",
    "start_compiled_answer",
    "typed_only_outcome",
]
