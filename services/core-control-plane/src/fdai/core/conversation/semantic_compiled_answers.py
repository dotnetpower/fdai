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
from collections.abc import Callable, MutableSequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.acl import ProjectionRequest

from .adaptive_call_scope import bind_adaptive_model_budget
from .intent_graph import build_intent_graph
from .model_observation import ConversationModelObservation
from .semantic_manifest import semantic_principal_scope_digest
from .semantic_planning_models import SemanticPlanningDisposition, SemanticPlanningOutcome
from .semantic_planning_support import _outcome, _refresh_object_set_cutoffs
from .semantic_reasoning_binding import GatewayAnchorResolver
from .semantic_reasoning_compiler import GoalStatus
from .semantic_reasoning_shadow import (
    QuestionFormModel,
    ReasoningShadowObservation,
    ShadowBudget,
    run_reasoning_shadow,
)
from .session import Principal

_LOGGER = logging.getLogger(__name__)
COMPILED_PLAN_SOURCE = "compiled_question_form"
_MAX_EVENT_ITEMS = 16


@dataclass(frozen=True, slots=True)
class CompiledAnswerSettings:
    """Bounds for one turn's form path; the defaults match the live evaluation harness."""

    default_lookback_seconds: int = 86_400
    deadline_seconds: float = 45.0
    budget: ShadowBudget = field(default_factory=ShadowBudget)

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
    ) -> None:
        self._future = future
        self._collector = collector
        self._deadline = clock() + deadline_seconds
        self._manifest = manifest
        self._verifier = verifier
        self._cutoff = cutoff
        self._clock = clock
        self._settled = False

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
            _log_completion("timeout")
            return None
        except Exception as exc:  # noqa: BLE001 - provider details stay inside the adapter
            self._future.cancel()
            _log_completion("failed", failure_type=type(exc).__name__)
            return None
        finally:
            observations.extend(self._collector.observations)
        selected = _single_compiled_batch(observation)
        if selected is None:
            _log_completion("declined", observation=observation)
            return None
        batch, confidence = selected
        # Compilation ran seconds ago; the gateway accepts only a current cutoff, so the plan
        # is stamped again and verified again before it can answer.
        try:
            plan = _refresh_object_set_cutoffs(batch.plan, execution_time=self._cutoff())
            self._verifier.verify(plan, manifest=self._manifest)
        except (PermissionError, ValueError) as exc:
            _log_completion("failed", observation=observation, failure_type=type(exc).__name__)
            return None
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
            intent_graph=build_intent_graph(frame=batch.frame, plan=plan, confidence=confidence),
        )

    def cancel(self) -> None:
        """Cancel an unconsumed path; the owner loop drains its provider calls."""

        if not self._settled:
            self._settled = True
            self._future.cancel()
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
    return compiled if compiled is not None else outcome


async def _run_form_path(
    model: QuestionFormModel,
    collector: _ObservationCollector,
    **arguments: Any,
) -> ReasoningShadowObservation:
    async with bind_adaptive_model_budget(collector):
        return await run_reasoning_shadow(model=model, retain_compilations=True, **arguments)


def _single_compiled_batch(
    observation: ReasoningShadowObservation,
) -> tuple[Any, float] | None:
    """Return the one verified batch of a released single-goal compilation, else ``None``."""

    if not observation.released or observation.continuation_pending:
        return None
    if len(observation.compilations) != 1 or observation.compilations[0].needs_continuation:
        return None
    goals = observation.compilations[0].goals
    if len(goals) != 1 or goals[0].status is not GoalStatus.COMPILED or goals[0].limitations:
        return None
    if len(goals[0].batches) != 1 or goals[0].confidence is None:
        return None
    batch = goals[0].batches[0]
    if (batch.index, batch.total) != (0, 1):
        return None
    return batch, goals[0].confidence


def _log_completion(
    result: str,
    *,
    observation: ReasoningShadowObservation | None = None,
    failure_type: str | None = None,
) -> None:
    extra: dict[str, object] = {"result": result}
    if failure_type is not None:
        extra["failure_type"] = failure_type
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
                "goal_limitations": [
                    limitation for goal in goals for limitation in goal.limitations
                ][:_MAX_EVENT_ITEMS],
                "model_calls": observation.model_calls,
                "elapsed_ms": observation.elapsed_ms,
                "notes": list(observation.notes[:_MAX_EVENT_ITEMS]),
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
]
