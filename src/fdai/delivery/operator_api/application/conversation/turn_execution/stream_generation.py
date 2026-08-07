"""Collect one streamed narrator answer without owning SSE transport.

Responsibility:
Collect deterministic or backend-generated answer events, including bounded
steer reruns and request-scoped metering.

Boundary:
Yield semantic token, status, or idle events. SSE framing, heartbeat bytes,
sequence numbers, and HTTP cancellation remain outside this module.

Authority and state:
This module has no approval or execution authority and mutates only the
request-local generation state supplied by its caller.

Dependencies:
Provider-neutral chat backend and busy-input contracts plus injected chunking
and idle-event adapters owned by the transport boundary.

Deployment:
Runs in-process inside the Operator API and creates no network boundary.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from fdai.core.conversation.answer_plan import AnswerPlan
from fdai.core.conversation.busy_input_coordinator import BusyInputCoordinator
from fdai.core.metering import InvocationScope, with_invocation_scope
from fdai.delivery.operator_api.application.conversation.backend import (
    ChatBackend,
    LatencyRoutedChatBackend,
)
from fdai.delivery.operator_api.application.conversation.busy_input import (
    MAX_STEER_RERUNS,
    answer_with_busy_input,
    append_next_steer,
    interruptible_events,
)
from fdai.delivery.operator_api.application.conversation.request_preparation import (
    ChatHistoryCompressor,
    ChatHistoryPolicy,
    answer_with_content_policy_recovery,
    collect_stream_with_content_policy_recovery,
)
from fdai.delivery.operator_api.application.conversation.response_completion import (
    metering_correlation_id,
)
from fdai.delivery.operator_api.application.conversation.verification import verify_answer
from fdai.shared.telemetry import ConversationProgressMetrics, with_correlation

from .models import StreamTurnEvent


class IdleEventAdapter(Protocol):
    """Wrap a source with transport-owned idle sentinels."""

    def __call__(
        self,
        source: AsyncIterator[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any] | None]: ...


@dataclass(slots=True)
class StreamGenerationState:
    """Mutable request-local values produced while collecting an answer."""

    history_metadata: dict[str, Any]
    revision: int = 0
    provisional_answer: str = ""
    model_generated: bool = False
    terminal_model: Any = None
    terminal_router: Any = None
    terminal_usage: Any = None


@dataclass(frozen=True, slots=True)
class StreamGenerationContext:
    """Inputs needed to collect one answer while preserving event ordering."""

    backend: ChatBackend
    prompt: str
    enriched_context: dict[str, Any]
    history: list[dict[str, str]]
    preferred_model: str | None
    history_compressor: ChatHistoryCompressor
    history_policy: ChatHistoryPolicy
    busy_input_coordinator: BusyInputCoordinator | None
    active_turn: Any | None
    user_id: str
    session_id: str
    response_locale: str | None
    answer_plan: AnswerPlan
    freshness_answer: str | None
    contextual_answer: str | None
    evidence_fast_path: bool
    ontology_answer: str | None
    health_answer: str | None
    screen_answer: str | None
    concept_answer: str | None
    progress_metrics: ConversationProgressMetrics | None
    idle_events: IdleEventAdapter
    chunk_answer: Callable[[str], list[str]]
    state: StreamGenerationState


async def generate_stream_answer(
    context: StreamGenerationContext,
) -> AsyncIterator[StreamTurnEvent]:
    """Yield ordered semantic answer events and update terminal generation state."""

    state = context.state
    if context.freshness_answer is not None:
        state.provisional_answer = context.freshness_answer
        state.terminal_model = "evidence-freshness"
        for chunk in context.chunk_answer(state.provisional_answer):
            yield StreamTurnEvent("token", {"delta": chunk}, state.revision)
        return
    if context.contextual_answer is not None:
        state.provisional_answer = context.contextual_answer
        state.terminal_model = "heimdall-read-investigation"
        for chunk in context.chunk_answer(state.provisional_answer):
            yield StreamTurnEvent("token", {"delta": chunk}, state.revision)
        return
    if context.evidence_fast_path:
        canonical = verify_answer(
            "",
            context.enriched_context,
            locale=context.response_locale,
        )
        state.provisional_answer = canonical.answer
        state.terminal_model = "evidence-verifier"
        for chunk in context.chunk_answer(state.provisional_answer):
            yield StreamTurnEvent("token", {"delta": chunk}, state.revision)
        return
    deterministic = (
        (context.ontology_answer, "ontology-snapshot")
        if context.ontology_answer is not None
        else (context.health_answer, "read-model-health")
        if context.health_answer is not None
        else (context.screen_answer, "bragi-screen-t0")
        if context.screen_answer is not None
        else (context.concept_answer, "concept-glossary")
        if context.concept_answer is not None
        else None
    )
    if deterministic is not None:
        state.provisional_answer, state.terminal_model = deterministic
        for chunk in context.chunk_answer(state.provisional_answer):
            yield StreamTurnEvent("token", {"delta": chunk}, state.revision)
        return

    stream = getattr(context.backend, "answer_stream", None)
    if stream is not None:
        state.model_generated = True
        steer_reruns = 0
        while steer_reruns <= MAX_STEER_RERUNS:

            async def invoke_stream(
                candidate_history: list[dict[str, str]],
            ) -> AsyncIterator[dict[str, Any]]:
                if isinstance(context.backend, LatencyRoutedChatBackend):
                    async for candidate_event in context.backend.answer_stream(
                        prompt=context.prompt,
                        view_context=context.enriched_context,
                        history=candidate_history,
                        preferred_model=context.preferred_model,
                    ):
                        yield candidate_event
                else:
                    async for candidate_event in stream(
                        prompt=context.prompt,
                        view_context=context.enriched_context,
                        history=candidate_history,
                    ):
                        yield candidate_event

            async def recovered_stream() -> AsyncIterator[dict[str, Any]]:
                buffered, recovery = await collect_stream_with_content_policy_recovery(
                    invoke=invoke_stream,
                    history=context.history,
                    compressor=context.history_compressor,
                    policy=context.history_policy,
                )
                if recovery is not None:
                    state.history_metadata = recovery.metadata()
                    if context.progress_metrics is not None:
                        context.progress_metrics.increment("history_policy_degraded")
                for buffered_event in buffered:
                    yield buffered_event

            state.provisional_answer = ""
            with (
                with_correlation(metering_correlation_id(context.user_id, context.session_id)),
                with_invocation_scope(InvocationScope.OPERATOR_CHAT),
            ):
                async for event in interruptible_events(
                    context.idle_events(recovered_stream()),
                    active_turn=context.active_turn,
                ):
                    if event is None:
                        yield StreamTurnEvent(None, revision=state.revision)
                        continue
                    event_type = event.get("type")
                    if event_type == "token":
                        delta = event.get("delta", "")
                        if isinstance(delta, str):
                            state.provisional_answer += delta
                        yield StreamTurnEvent("token", {"delta": delta}, state.revision)
                    elif event_type == "done":
                        answer = event.get("answer")
                        if isinstance(answer, str) and answer:
                            state.provisional_answer = answer
                        state.terminal_model = event.get("model")
                        state.terminal_router = event.get("router")
                        state.terminal_usage = event.get("usage")
            if steer_reruns >= MAX_STEER_RERUNS or not await append_next_steer(
                history=context.history,
                coordinator=context.busy_input_coordinator,
                active_turn=context.active_turn,
            ):
                break
            steer_reruns += 1
            state.revision += 1
            yield StreamTurnEvent(
                "status",
                {"phase": "steering", "label": "Applying operator guidance"},
                state.revision,
            )
        return

    state.model_generated = True

    async def invoke_backend(active_history: list[dict[str, str]]) -> dict[str, Any]:
        async def invoke_raw(candidate_history: list[dict[str, str]]) -> dict[str, Any]:
            if isinstance(context.backend, LatencyRoutedChatBackend):
                return await context.backend.answer(
                    prompt=context.prompt,
                    view_context=context.enriched_context,
                    history=candidate_history,
                    preferred_model=context.preferred_model,
                )
            return await context.backend.answer(
                prompt=context.prompt,
                view_context=context.enriched_context,
                history=candidate_history,
            )

        reply, recovery = await answer_with_content_policy_recovery(
            invoke=invoke_raw,
            history=active_history,
            compressor=context.history_compressor,
            policy=context.history_policy,
        )
        if recovery is not None:
            state.history_metadata = recovery.metadata()
            if context.progress_metrics is not None:
                context.progress_metrics.increment("history_policy_degraded")
        return reply

    with (
        with_correlation(metering_correlation_id(context.user_id, context.session_id)),
        with_invocation_scope(InvocationScope.OPERATOR_CHAT),
    ):
        reply = await answer_with_busy_input(
            invoke=invoke_backend,
            history=context.history,
            coordinator=context.busy_input_coordinator,
            active_turn=context.active_turn,
        )
    answer = reply.get("answer", "")
    if isinstance(answer, str) and answer:
        state.provisional_answer = answer
        for chunk in context.chunk_answer(answer):
            yield StreamTurnEvent("token", {"delta": chunk}, state.revision)
    state.terminal_model = reply.get("model")
    state.terminal_router = reply.get("router")
    state.terminal_usage = reply.get("usage")


__all__ = [
    "IdleEventAdapter",
    "StreamGenerationContext",
    "StreamGenerationState",
    "generate_stream_answer",
]
