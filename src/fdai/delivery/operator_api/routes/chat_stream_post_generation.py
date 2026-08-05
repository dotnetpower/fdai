"""Post-generation review and terminal presentation for streamed chat turns."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.core.conversation import ActiveConversationTurn
from fdai.core.conversation.answer_plan import AnswerPlan
from fdai.core.conversation.answer_planning import AnswerPlanningResult
from fdai.core.metering import InvocationScope, with_invocation_scope
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.operator_api.application import (
    ConversationTurnApplicationService,
    ConversationTurnExecution,
)
from fdai.delivery.operator_api.routes.chat_answer_planning import planning_metadata
from fdai.delivery.operator_api.routes.chat_answer_quality import (
    AnswerQualityInvoke,
    AnswerQualityResult,
)
from fdai.delivery.operator_api.routes.chat_backend_common import ChatBackend
from fdai.delivery.operator_api.routes.chat_backend_router import LatencyRoutedChatBackend
from fdai.delivery.operator_api.routes.chat_busy_input import interruptible_events
from fdai.delivery.operator_api.routes.chat_document_evidence import merge_document_verification
from fdai.delivery.operator_api.routes.chat_freshness_context import (
    EvidenceFreshnessContext,
    response_evidence_freshness_context,
)
from fdai.delivery.operator_api.routes.chat_history import (
    append_assistant_turn,
    replay_metadata,
)
from fdai.delivery.operator_api.routes.chat_presentation import PresentationDecision
from fdai.delivery.operator_api.routes.chat_resource_context import response_resource_context
from fdai.delivery.operator_api.routes.chat_route_common import (
    _metering_correlation_id,
    _turn_metadata,
)
from fdai.delivery.operator_api.routes.chat_stream_protocol import (
    DEFAULT_STREAM_HEARTBEAT_S,
    _sse,
    _with_sse_heartbeats,
)
from fdai.delivery.operator_api.routes.chat_stream_terminal import (
    TurnTimingRecorder,
    TurnTimingStatus,
    TurnTimingToken,
    build_done_payload,
    verification_events,
)
from fdai.delivery.operator_api.routes.chat_trajectory_detail import (
    TrajectoryDetailCollector,
    trajectory_detail_budget,
)
from fdai.delivery.operator_api.routes.chat_verification import (
    AnswerVerification,
    verify_answer,
)
from fdai.delivery.operator_api.routes.post_turn_review import (
    PostTurnReviewSubmission,
    PostTurnReviewSubmitter,
    explicit_corrections,
)
from fdai.shared.providers.user_context import (
    ConversationHistoryStore,
    ConversationTurnRecord,
)
from fdai.shared.telemetry import ConversationProgressMetrics, with_correlation

_LOG = logging.getLogger(__name__)


class QualityReviewFn(Protocol):
    def __call__(
        self,
        *,
        answer: str,
        view_context: Mapping[str, Any],
        locale: str | None,
        invoke: AnswerQualityInvoke,
    ) -> Awaitable[AnswerQualityResult]: ...


class QualityVerifyFn(Protocol):
    def __call__(
        self,
        result: AnswerQualityResult,
        view_context: Mapping[str, Any],
        *,
        locale: str | None,
    ) -> AnswerVerification: ...


@dataclass(frozen=True, slots=True)
class PostGenerationFrame:
    """One ordered terminal update; ``event=None`` denotes an SSE heartbeat."""

    event: str | None
    payload: dict[str, Any] | None
    revision: int


@dataclass(frozen=True, slots=True)
class PostGenerationContext:
    """Runtime dependencies and immutable turn state needed after answer generation."""

    backend: ChatBackend
    presentation_task: asyncio.Task[PresentationDecision] | None
    presentation_timeout_seconds: float
    answer_plan: AnswerPlan
    enriched_context: dict[str, Any]
    provisional_answer: str
    terminal_model: Any
    terminal_router: Any
    terminal_usage: Any
    started: float
    turn_timing: TurnTimingRecorder
    generation_timing: TurnTimingToken
    model_generated: bool
    preferred_model: str | None
    response_locale: str | None
    active_turn: ActiveConversationTurn | None
    user_id: str
    session_id: str
    request_id: str
    clean_prompt: str
    review_quality: QualityReviewFn
    verify_quality: QualityVerifyFn
    freshness_verification: AnswerVerification | None
    contextual_verification: AnswerVerification | None
    document_evidence_refs: tuple[str, ...]
    progress_metrics: ConversationProgressMetrics | None
    revision: int
    planning_task: asyncio.Task[AnswerPlanningResult] | None
    evidence_fast_path: bool
    ontology_answer: str | None
    health_answer: str | None
    screen_answer: str | None
    concept_answer: str | None
    contextual_answer: str | None
    freshness_answer: str | None
    delegation: Mapping[str, Any] | None
    resource_context: Mapping[str, str] | None
    freshness_context: EvidenceFreshnessContext | None
    model_trace_snapshot: Callable[[], Mapping[str, Any] | None]
    history_metadata: dict[str, Any]
    trajectory_detail: TrajectoryDetailCollector
    conversation_history_store: ConversationHistoryStore | None
    user_context_ontology_projector: UserContextOntologyProjector | None
    operator_turn: ConversationTurnRecord | None
    post_turn_review_submitter: PostTurnReviewSubmitter | None
    cleanup: Callable[[], Awaitable[None]]
    turn_service: ConversationTurnApplicationService
    turn_execution: ConversationTurnExecution


def evidence_timing_status(outcomes: list[str]) -> TurnTimingStatus:
    """Reduce evidence branch outcomes to one terminal timing status."""

    terminal = [
        status
        for status in outcomes
        if status in {"completed", "unavailable", "failed", "timed_out", "cancelled"}
    ]
    if not terminal or all(status == "completed" for status in terminal):
        return "completed"
    if all(status == "failed" for status in terminal):
        return "failed"
    return "degraded"


def _verification_timing_status(status: str) -> TurnTimingStatus:
    if status == "corrected":
        return "corrected"
    if status == "unverified":
        return "unverified"
    return "completed"


async def finalize_post_generation(
    context: PostGenerationContext,
) -> AsyncIterator[PostGenerationFrame]:
    """Review, verify, persist, and emit one streamed answer's terminal updates in order."""

    answer_plan = context.answer_plan
    presentation_task = context.presentation_task
    if presentation_task is not None:
        try:
            presentation_decision = await asyncio.wait_for(
                presentation_task,
                timeout=context.presentation_timeout_seconds,
            )
        except TimeoutError:
            presentation_task.cancel()
            with suppress(asyncio.CancelledError):
                await presentation_task
        except Exception as exc:  # noqa: BLE001 - keep canonical answer and default plan
            _LOG.warning(
                "chat presentation task failed after answer streaming",
                extra={"error_type": type(exc).__name__},
            )
        else:
            answer_plan = presentation_decision.answer_plan
            if presentation_decision.presentation_plan is not None:
                context.enriched_context["_presentation_plan"] = (
                    presentation_decision.presentation_plan.to_dict()
                )
            context.enriched_context["_answer_plan"] = answer_plan.to_dict()

    generation_ms = int((time.monotonic() - context.started) * 1000)
    context.turn_timing.complete(context.generation_timing, status="completed")
    yield PostGenerationFrame(
        event="provisional",
        payload={
            "answer": context.provisional_answer,
            "model": context.terminal_model,
            "generation_ms": generation_ms,
        },
        revision=context.revision,
    )

    quality: AnswerQualityResult | None = None
    if context.model_generated:
        quality_timing = context.turn_timing.begin("quality_review")

        async def invoke_quality(
            quality_prompt: str,
            quality_context: dict[str, Any],
        ) -> dict[str, Any]:
            if isinstance(context.backend, LatencyRoutedChatBackend):
                return await context.backend.answer(
                    prompt=quality_prompt,
                    view_context=quality_context,
                    history=[],
                    preferred_model=str(context.terminal_model or context.preferred_model or "")
                    or None,
                )
            return await context.backend.answer(
                prompt=quality_prompt,
                view_context=quality_context,
                history=[],
            )

        async def quality_source() -> AsyncIterator[dict[str, Any]]:
            with (
                with_correlation(_metering_correlation_id(context.user_id, context.session_id)),
                with_invocation_scope(InvocationScope.OPERATOR_CHAT),
            ):
                result = await context.review_quality(
                    answer=context.provisional_answer,
                    view_context=context.enriched_context,
                    locale=context.response_locale,
                    invoke=invoke_quality,
                )
            yield {"result": result}

        quality_events = _with_sse_heartbeats(quality_source(), interval=DEFAULT_STREAM_HEARTBEAT_S)
        async for quality_event in interruptible_events(
            quality_events,
            active_turn=context.active_turn,
        ):
            if quality_event is None:
                yield PostGenerationFrame(
                    event=None,
                    payload=None,
                    revision=context.revision,
                )
                continue
            candidate = quality_event.get("result")
            if isinstance(candidate, AnswerQualityResult):
                quality = candidate
        context.turn_timing.complete(
            quality_timing,
            status="completed" if quality is not None else "degraded",
        )

    verification_timing = context.turn_timing.begin("verification")
    verification = (
        context.freshness_verification
        if context.freshness_verification is not None
        else context.contextual_verification
        if context.contextual_verification is not None
        else context.verify_quality(
            quality,
            context.enriched_context,
            locale=context.response_locale,
        )
        if quality is not None
        else verify_answer(
            context.provisional_answer,
            context.enriched_context,
            locale=context.response_locale,
        )
    )
    verification = merge_document_verification(
        verification,
        context.document_evidence_refs,
    )
    if context.progress_metrics is not None and verification.answer != context.provisional_answer:
        context.progress_metrics.increment("corrections")
    terminal_events, revision = verification_events(
        context.provisional_answer,
        verification,
        context.revision,
    )
    for event_name, payload in terminal_events:
        yield PostGenerationFrame(event=event_name, payload=payload, revision=revision)
    context.turn_timing.complete(
        verification_timing,
        status=_verification_timing_status(verification.status),
    )
    if verification.status != "unverified":
        if context.progress_metrics is not None:
            context.progress_metrics.observe_latency(
                "time_to_first_confirmed",
                max(0, int((time.monotonic() - context.started) * 1000)),
            )
        confirmed_payload: dict[str, Any] = {
            "segment_index": 0,
            "text": verification.answer,
            "status": verification.status,
            "evidence_refs": list(verification.evidence_refs),
        }
        if verification.answer != context.provisional_answer:
            confirmed_payload.update(
                {
                    "replace_start": 0,
                    "replace_end": len(context.provisional_answer),
                }
            )
        yield PostGenerationFrame(
            event="confirmed",
            payload=confirmed_payload,
            revision=revision,
        )

    answer_planning = await planning_metadata(context.planning_task)
    done_payload = build_done_payload(
        verification=verification,
        terminal_model=context.terminal_model,
        terminal_router=context.terminal_router,
        terminal_usage=context.terminal_usage,
        evidence_fast_path=context.evidence_fast_path,
        ontology_answer=context.ontology_answer,
        health_answer=context.health_answer,
        screen_answer=context.screen_answer,
        concept_answer=context.concept_answer,
        resource_answer=context.contextual_answer,
        freshness_answer=context.freshness_answer,
        started=context.started,
        delegation=context.delegation,
        enriched_context=context.enriched_context,
        response_locale=context.response_locale,
        answer_plan=answer_plan,
        answer_planning=answer_planning,
        quality=quality,
        resource_context=response_resource_context(
            context.enriched_context,
            context.resource_context,
        ),
        freshness_context=response_evidence_freshness_context(
            context.enriched_context,
            context.freshness_context,
        ),
        model_trace=context.model_trace_snapshot(),
        turn_timing=context.turn_timing.snapshot(),
        trajectory_detail=None,
    )
    done_payload["history_context"] = context.history_metadata
    trajectory_detail_snapshot = context.trajectory_detail.snapshot(
        max_bytes=trajectory_detail_budget(done_payload)
    )
    if trajectory_detail_snapshot is not None:
        done_payload["trajectory_detail"] = trajectory_detail_snapshot
    validated_result = context.turn_service.validate_turn_result(
        context.turn_execution,
        done_payload,
    )
    terminal_payload = validated_result.to_wire_payload()
    _sse(
        "done",
        {
            **terminal_payload,
            "v": 1,
            "request_id": context.request_id,
            "seq": 9_223_372_036_854_775_807,
            "revision": revision,
        },
    )
    if context.conversation_history_store is not None:
        assistant_turn = await append_assistant_turn(
            store=context.conversation_history_store,
            principal_id=context.user_id,
            conversation_id=context.session_id,
            request_id=context.request_id,
            content=verification.answer,
            recorded_at=datetime.now(tz=UTC),
            metadata=replay_metadata(
                model=str(context.terminal_model or "unknown"),
                payload=terminal_payload,
                additional=_turn_metadata(
                    model=str(context.terminal_model or "unknown"),
                    view_context=context.enriched_context,
                    answer_planning=answer_planning,
                )
                | context.history_metadata,
            ),
            ontology_projector=context.user_context_ontology_projector,
        )
        if context.post_turn_review_submitter is not None and context.operator_turn is not None:
            context.post_turn_review_submitter.submit_nowait(
                operator_turn=context.operator_turn,
                assistant_turn=assistant_turn,
                submission=PostTurnReviewSubmission(
                    validation_outcomes=(verification.status,),
                    evidence_refs=verification.evidence_refs,
                    explicit_corrections=explicit_corrections(context.clean_prompt),
                ),
            )
    result = context.turn_service.complete_turn(context.turn_execution, terminal_payload)
    terminal_payload = result.to_wire_payload()
    await context.cleanup()
    if context.progress_metrics is not None:
        context.progress_metrics.increment("terminal_completed")
    yield PostGenerationFrame(
        event="done",
        payload=terminal_payload,
        revision=revision,
    )


__all__ = [
    "PostGenerationContext",
    "PostGenerationFrame",
    "evidence_timing_status",
    "finalize_post_generation",
]
