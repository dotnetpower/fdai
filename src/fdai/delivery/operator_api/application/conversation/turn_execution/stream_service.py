"""Coordinate streamed conversation turns outside HTTP and SSE transport.

Responsibility:
Coordinate request preparation results, planning, evidence, generation,
verification, persistence, metering, and completion for one streamed turn.

Boundary:
Accept application-owned prepared values and yield semantic events. HTTP status
mapping, SSE framing, heartbeat bytes, sequence numbers, and connection teardown
stay in the route adapter.

Authority and state:
This service has no approval, execution, promotion, or provider-scope authority.
It writes only through injected conversation stores that own those records.

Dependencies:
Provider-neutral conversation contracts plus application, projection,
persistence, metering, and transport callback seams supplied by composition.

Deployment:
Runs in-process inside the Operator API and creates no network boundary.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Final, Protocol

from fdai.core.conversation.answer_planning import AnswerPlanningResult
from fdai.core.conversation.busy_input_coordinator import BusyInputCoordinator
from fdai.core.conversation_assurance import ConversationPolicyRuntime
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.conversation_images import ConversationImageStore
from fdai.delivery.operator_api.application import (
    ConversationTurnApplicationService,
    ConversationTurnExecution,
    ConversationTurnTerminalStatus,
)
from fdai.delivery.operator_api.application.conversation.backend import (
    ChatBackend,
    ChatBackendUnavailableError,
    ChatContentPolicyError,
)
from fdai.delivery.operator_api.application.conversation.busy_input import (
    ChatTurnInterruptedError,
    interruptible_events,
)
from fdai.delivery.operator_api.application.conversation.capabilities.action_context import (
    is_explicit_action_draft_request,
)
from fdai.delivery.operator_api.application.conversation.evidence import (
    AgentChatDelegate,
    ChatBehaviorEvidenceResolver,
    ChatToolResolver,
    ChatWebSearchEvidenceResolver,
    OperationalEvidenceResolverProtocol,
    PlannedChatToolResolver,
)
from fdai.delivery.operator_api.application.conversation.freshness_context import (
    response_evidence_freshness_context,
)
from fdai.delivery.operator_api.application.conversation.intent_graph import (
    IntentGraph,
    IntentGraphPlanner,
    apply_intent_graph_to_answer_plan,
    draft_capability_available,
    plan_semantic_turn,
    planner_context_envelope,
)
from fdai.delivery.operator_api.application.conversation.planning import (
    AnswerPlanningDelegate,
    cancel_planning,
    planning_metadata,
)
from fdai.delivery.operator_api.application.conversation.post_generation import (
    PostGenerationContext,
    PostGenerationDependencies,
    finalize_post_generation,
    review_korean_narrator_answer,
    verify_quality_result,
)
from fdai.delivery.operator_api.application.conversation.prompt import (
    _is_grounded_concept_query,
)
from fdai.delivery.operator_api.application.conversation.request_preparation import (
    DEFAULT_CHAT_HISTORY_POLICY,
    ChatHistoryPolicy,
    ContentPolicyReplayRequest,
    PreparedChatStreamRequest,
)
from fdai.delivery.operator_api.application.conversation.response_completion import (
    metering_correlation_id,
    turn_metadata,
)
from fdai.delivery.operator_api.application.conversation.review_submission import (
    PostTurnReviewSubmission,
    PostTurnReviewSubmitter,
    explicit_corrections,
)
from fdai.delivery.operator_api.application.conversation.turn_plan import (
    TurnPlanner,
    TurnTool,
    apply_turn_plan_to_answer_plan,
)
from fdai.delivery.operator_api.application.conversation.verification import (
    AnswerVerification,
)
from fdai.delivery.operator_api.persistence.conversation import (
    append_assistant_turn,
    append_content_policy_receipt,
    replay_metadata,
)
from fdai.delivery.operator_api.projections.conversation.document_evidence import (
    merge_document_verification,
)
from fdai.delivery.operator_api.projections.conversation.presentation import (
    PresentationDecision,
    select_answer_presentation,
)
from fdai.delivery.operator_api.projections.conversation.resource_context import (
    response_resource_context,
)
from fdai.delivery.operator_api.projections.conversation.terminal import (
    TurnTimingRecorder,
)
from fdai.delivery.operator_api.projections.conversation.tracing import (
    activate_model_trace,
    deactivate_model_trace,
    snapshot_model_trace,
)
from fdai.delivery.operator_api.projections.conversation.trajectory import (
    TrajectoryDetailCollector,
    trajectory_detail_budget,
)
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.providers.user_context import (
    ConversationHistoryStore,
    ConversationTurnRecord,
)
from fdai.shared.telemetry import ConversationProgressMetrics

from .lifecycle import JsonTurnLifecycle
from .models import (
    StreamTurnEvent,
    StreamTurnExecution,
)
from .stream_evidence import (
    StreamEvidenceContext,
    StreamEvidenceState,
    resolve_stream_evidence,
)
from .stream_generation import (
    IdleEventAdapter,
    StreamGenerationContext,
    StreamGenerationState,
    generate_stream_answer,
)
from .stream_setup import PreparedStreamSession, StreamTurnSetup

_LOG = logging.getLogger(__name__)
_PRESENTATION_JOIN_TIMEOUT_SECONDS: Final[float] = 5.0


class UpstreamStatusResolver(Protocol):
    """Project a transport exception to a bounded status without importing it."""

    def __call__(self, exc: BaseException) -> int | None: ...


class StreamTurnExecutionService:
    """Prepare and execute one authenticated streamed conversation turn."""

    def __init__(
        self,
        *,
        backend: ChatBackend,
        behavior_resolver: ChatBehaviorEvidenceResolver | None = None,
        evidence_resolver: OperationalEvidenceResolverProtocol | None = None,
        tool_resolver: ChatToolResolver | None = None,
        planned_tool_resolver: PlannedChatToolResolver | None = None,
        web_search_resolver: ChatWebSearchEvidenceResolver | None = None,
        agent_delegate: AgentChatDelegate | None = None,
        answer_planning_delegate: AnswerPlanningDelegate | None = None,
        conversation_policy_store: ConversationPolicyStore | None = None,
        conversation_assurance_runtime: ConversationPolicyRuntime | None = None,
        conversation_history_store: ConversationHistoryStore | None = None,
        conversation_image_store: ConversationImageStore | None = None,
        user_context_ontology_projector: UserContextOntologyProjector | None = None,
        post_turn_review_submitter: PostTurnReviewSubmitter | None = None,
        busy_input_coordinator: BusyInputCoordinator | None = None,
        progress_metrics: ConversationProgressMetrics | None = None,
        turn_planner: TurnPlanner | IntentGraphPlanner | None = None,
        turn_tools: tuple[TurnTool, ...] | Callable[[], tuple[TurnTool, ...]] = (),
        history_policy: ChatHistoryPolicy = DEFAULT_CHAT_HISTORY_POLICY,
        turn_service: ConversationTurnApplicationService | None = None,
        idle_events: IdleEventAdapter,
        chunk_answer: Callable[[str], list[str]],
        upstream_status: UpstreamStatusResolver,
    ) -> None:
        self._backend = backend
        self._behavior_resolver = behavior_resolver
        self._evidence_resolver = evidence_resolver
        self._tool_resolver = tool_resolver
        self._planned_tool_resolver = planned_tool_resolver
        self._web_search_resolver = web_search_resolver
        self._agent_delegate = agent_delegate
        self._answer_planning_delegate = answer_planning_delegate
        self._conversation_policy_store = conversation_policy_store
        self._conversation_assurance_runtime = conversation_assurance_runtime
        self._conversation_history_store = conversation_history_store
        self._user_context_ontology_projector = user_context_ontology_projector
        self._post_turn_review_submitter = post_turn_review_submitter
        self._busy_input_coordinator = busy_input_coordinator
        self._progress_metrics = progress_metrics
        self._turn_planner = turn_planner
        self._turn_tools = turn_tools
        self._history_policy = history_policy
        self._turn_service = (
            turn_service if turn_service is not None else ConversationTurnApplicationService()
        )
        from fdai.delivery.operator_api.application.conversation.request_preparation import (
            BackendChatHistoryCompressor,
        )

        self._history_compressor = BackendChatHistoryCompressor(
            backend=backend,
            max_summary_chars=history_policy.max_summary_chars,
        )
        self._lifecycle = JsonTurnLifecycle(
            turn_service=self._turn_service,
            conversation_history_store=conversation_history_store,
            conversation_image_store=conversation_image_store,
            user_context_ontology_projector=user_context_ontology_projector,
            busy_input_coordinator=busy_input_coordinator,
            document_evidence_resolver=None,
            turn_planner=turn_planner,
            turn_tools=turn_tools,
            handover_availability_publisher=None,
        )
        self._setup = StreamTurnSetup(
            turn_service=self._turn_service,
            lifecycle=self._lifecycle,
            tool_resolver=tool_resolver,
            progress_metrics=progress_metrics,
        )
        self._idle_events = idle_events
        self._chunk_answer = chunk_answer
        self._upstream_status = upstream_status

    async def start(
        self,
        prepared: PreparedChatStreamRequest | ContentPolicyReplayRequest,
    ) -> StreamTurnExecution:
        """Complete pre-stream setup so HTTP status semantics remain available."""

        return await self._setup.start(prepared, self._run)

    async def _run(self, session: PreparedStreamSession) -> AsyncIterator[StreamTurnEvent]:
        request = session.request
        execution = session.turn_execution
        model_trace_scope = activate_model_trace(request.include_model_trace)
        turn_timing = TurnTimingRecorder()
        trajectory_detail = TrajectoryDetailCollector()
        started = turn_timing.started_monotonic
        answer_plan = request.answer_plan
        planning_task: asyncio.Task[AnswerPlanningResult] | None = None
        presentation_task: asyncio.Task[PresentationDecision] | None = None
        cleanup_complete = False

        async def cleanup() -> None:
            nonlocal cleanup_complete
            if cleanup_complete:
                return
            await cancel_planning(planning_task)
            if presentation_task is not None and not presentation_task.done():
                presentation_task.cancel()
                with suppress(asyncio.CancelledError):
                    await presentation_task
            try:
                await self._setup.finish_active(request, session.active_turn)
            except Exception as exc:  # noqa: BLE001 - preserve terminal response
                _LOG.warning(
                    "chat stream busy-input cleanup failed: %s",
                    type(exc).__name__,
                    extra={
                        "session_id": request.session_id,
                        "request_id": request.request_id,
                    },
                    exc_info=True,
                )
            cleanup_complete = True

        try:
            if session.completed_payload is not None:
                replay_payload = dict(session.completed_payload)
                if not request.include_model_trace:
                    replay_payload.pop("model_trace", None)
                if self._progress_metrics is not None:
                    self._progress_metrics.increment("replays")
                    self._progress_metrics.observe_latency(
                        "time_to_first_confirmed",
                        max(0, int((time.monotonic() - started) * 1000)),
                    )
                await cleanup()
                validated = self._turn_service.validate_turn_result(execution, replay_payload)
                result = self._turn_service.complete_turn(
                    execution,
                    validated.to_wire_payload(),
                )
                yield StreamTurnEvent("done", result.to_wire_payload())
                return

            semantic_plan = None
            if (
                self._turn_planner is not None
                and not request.vision_attachments
                and not _is_grounded_concept_query(request.clean_prompt)
                and (
                    not session.deterministic_followup
                    or session.semantic_inventory_completion
                    or is_explicit_action_draft_request(request.clean_prompt)
                )
            ):
                semantic_timing = turn_timing.begin("semantic_plan")
                try:
                    semantic_plan = await plan_semantic_turn(
                        self._turn_planner,
                        prompt=request.clean_prompt,
                        tools=self._resolved_turn_tools(),
                        history=request.history,
                        attachments=request.view_context.get("_attachments"),
                        context=planner_context_envelope(
                            request.view_context,
                            resource_context=request.resource_context,
                            conversation_context=request.conversation_context,
                            document_refs=request.document_evidence_refs,
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - shadow plan degrades closed
                    turn_timing.complete(semantic_timing, status="degraded")
                    _LOG.warning(
                        "chat stream turn planning unavailable: %s",
                        type(exc).__name__,
                        extra={"request_id": request.request_id},
                    )
                else:
                    turn_timing.complete(semantic_timing, status="completed")
                    answer_plan = (
                        apply_intent_graph_to_answer_plan(answer_plan, semantic_plan)
                        if isinstance(semantic_plan, IntentGraph)
                        else apply_turn_plan_to_answer_plan(answer_plan, semantic_plan)
                    )
                    request.view_context["_answer_plan"] = answer_plan.to_dict()
                    request.view_context[
                        "_intent_graph" if isinstance(semantic_plan, IntentGraph) else "_turn_plan"
                    ] = semantic_plan.to_dict()
                    if semantic_plan.requires_confirmation:
                        await cleanup()
                        if isinstance(
                            semantic_plan,
                            IntentGraph,
                        ) and not draft_capability_available(
                            semantic_plan,
                            self._resolved_turn_tools(),
                        ):
                            detail = "draft capability is no longer available"
                            payload = {"error": detail, "status": 409}
                            unavailable = self._turn_service.terminate_turn(
                                execution,
                                terminal_status=ConversationTurnTerminalStatus.UNAVAILABLE,
                                code="draft_capability_unavailable",
                                detail=detail,
                                wire_payload=payload,
                            )
                            yield StreamTurnEvent("error", unavailable.to_wire_payload())
                            return
                        payload = {
                            "answer": "Review this action draft before submitting it.",
                            "model": "semantic-turn-planner",
                            "source": "action-draft",
                            "action_draft": semantic_plan.confirmation_payload(
                                request_id=request.request_id,
                                session_id=request.session_id,
                            ),
                            "turn_timing": turn_timing.snapshot(),
                        }
                        draft = self._turn_service.complete_turn(
                            execution,
                            payload,
                            terminal_status=ConversationTurnTerminalStatus.UNVERIFIED,
                        )
                        yield StreamTurnEvent("done", draft.to_wire_payload())
                        return
            evidence_state = StreamEvidenceState(answer_plan=answer_plan)
            async for evidence_event in resolve_stream_evidence(
                StreamEvidenceContext(
                    request=request,
                    semantic_plan=semantic_plan,
                    deterministic_followup=session.deterministic_followup,
                    behavior_resolver=self._behavior_resolver,
                    evidence_resolver=self._evidence_resolver,
                    tool_resolver=self._tool_resolver,
                    planned_tool_resolver=self._planned_tool_resolver,
                    web_search_resolver=self._web_search_resolver,
                    agent_delegate=self._agent_delegate,
                    answer_planning_delegate=self._answer_planning_delegate,
                    conversation_policy_store=self._conversation_policy_store,
                    conversation_assurance_runtime=self._conversation_assurance_runtime,
                    progress_metrics=self._progress_metrics,
                    turn_timing=turn_timing,
                    trajectory_detail=trajectory_detail,
                    started=started,
                ),
                evidence_state,
            ):
                yield evidence_event
            answer_plan = evidence_state.answer_plan
            planning_task = evidence_state.planning_task
            enriched_context = evidence_state.enriched_context
            if enriched_context is None:
                raise RuntimeError("stream evidence did not produce context")
            delegation = evidence_state.delegation
            evidence_fast_path = evidence_state.evidence_fast_path
            response_locale = evidence_state.response_locale
            freshness_answer = evidence_state.freshness_answer
            health_answer = evidence_state.health_answer
            screen_answer = evidence_state.screen_answer
            concept_answer = evidence_state.concept_answer
            ontology_answer = evidence_state.ontology_answer
            contextual_verification = evidence_state.contextual_verification
            contextual_answer = evidence_state.contextual_answer
            freshness_verification = evidence_state.freshness_verification
            generation_timing = turn_timing.begin("generation")
            if evidence_fast_path:
                presentation_base_plan = answer_plan
                default_presentation = await select_answer_presentation(
                    backend=object(),
                    prompt=request.clean_prompt,
                    plan=presentation_base_plan,
                    view_context=enriched_context,
                )
                answer_plan = default_presentation.answer_plan
                if default_presentation.presentation_plan is not None:
                    enriched_context["_presentation_plan"] = (
                        default_presentation.presentation_plan.to_dict()
                    )
                enriched_context["_answer_plan"] = answer_plan.to_dict()
                presentation_task = asyncio.create_task(
                    select_answer_presentation(
                        backend=self._backend,
                        prompt=request.clean_prompt,
                        plan=presentation_base_plan,
                        view_context=enriched_context,
                    )
                )
            generation_state = StreamGenerationState(
                history_metadata=dict(request.history_metadata)
            )
            async for generated_event in generate_stream_answer(
                StreamGenerationContext(
                    backend=self._backend,
                    prompt=request.clean_prompt,
                    enriched_context=enriched_context,
                    history=request.history,
                    preferred_model=request.preferred_model,
                    history_compressor=self._history_compressor,
                    history_policy=self._history_policy,
                    busy_input_coordinator=self._busy_input_coordinator,
                    active_turn=session.active_turn,
                    user_id=request.user_id,
                    session_id=request.session_id,
                    response_locale=response_locale,
                    answer_plan=answer_plan,
                    freshness_answer=freshness_answer,
                    contextual_answer=contextual_answer,
                    evidence_fast_path=evidence_fast_path,
                    ontology_answer=ontology_answer,
                    health_answer=health_answer,
                    screen_answer=screen_answer,
                    concept_answer=concept_answer,
                    progress_metrics=self._progress_metrics,
                    idle_events=self._idle_events,
                    chunk_answer=self._chunk_answer,
                    state=generation_state,
                )
            ):
                yield generated_event

            async def quality_events(
                source: AsyncIterator[dict[str, Any]],
            ) -> AsyncIterator[dict[str, Any] | None]:
                async for quality_event in interruptible_events(
                    self._idle_events(source),
                    active_turn=session.active_turn,
                ):
                    yield quality_event

            async def persist_assistant_turn(
                *,
                answer: str,
                terminal_payload: Mapping[str, Any],
                answer_planning: Mapping[str, object] | None,
            ) -> ConversationTurnRecord | None:
                if self._conversation_history_store is None:
                    return None
                return await append_assistant_turn(
                    store=self._conversation_history_store,
                    principal_id=request.user_id,
                    conversation_id=request.session_id,
                    request_id=request.request_id,
                    content=answer,
                    recorded_at=datetime.now(tz=UTC),
                    metadata=replay_metadata(
                        model=str(generation_state.terminal_model or "unknown"),
                        payload=terminal_payload,
                        additional=turn_metadata(
                            model=str(generation_state.terminal_model or "unknown"),
                            view_context=enriched_context,
                            answer_planning=answer_planning,
                        )
                        | generation_state.history_metadata,
                    ),
                    ontology_projector=self._user_context_ontology_projector,
                )

            def submit_post_turn_review(
                assistant_turn: ConversationTurnRecord,
                verification: AnswerVerification,
            ) -> None:
                if self._post_turn_review_submitter is None or session.operator_turn is None:
                    return
                self._post_turn_review_submitter.submit_nowait(
                    operator_turn=session.operator_turn,
                    assistant_turn=assistant_turn,
                    submission=PostTurnReviewSubmission(
                        validation_outcomes=(verification.status,),
                        evidence_refs=verification.evidence_refs,
                        explicit_corrections=explicit_corrections(request.clean_prompt),
                    ),
                )

            post_generation = finalize_post_generation(
                PostGenerationContext(
                    backend=self._backend,
                    presentation_task=presentation_task,
                    presentation_timeout_seconds=_PRESENTATION_JOIN_TIMEOUT_SECONDS,
                    answer_plan=answer_plan,
                    enriched_context=enriched_context,
                    provisional_answer=generation_state.provisional_answer,
                    terminal_model=generation_state.terminal_model,
                    terminal_router=generation_state.terminal_router,
                    terminal_usage=generation_state.terminal_usage,
                    started=started,
                    turn_timing=turn_timing,
                    generation_timing=generation_timing,
                    model_generated=generation_state.model_generated,
                    preferred_model=request.preferred_model,
                    response_locale=response_locale,
                    metering_correlation_id=metering_correlation_id(
                        request.user_id,
                        request.session_id,
                    ),
                    review_quality=review_korean_narrator_answer,
                    verify_quality=verify_quality_result,
                    freshness_verification=freshness_verification,
                    contextual_verification=contextual_verification,
                    document_evidence_refs=request.document_evidence_refs,
                    progress_metrics=self._progress_metrics,
                    revision=generation_state.revision,
                    planning_task=planning_task,
                    evidence_fast_path=evidence_fast_path,
                    ontology_answer=ontology_answer,
                    health_answer=health_answer,
                    screen_answer=screen_answer,
                    concept_answer=concept_answer,
                    contextual_answer=contextual_answer,
                    freshness_answer=freshness_answer,
                    delegation=delegation,
                    response_resource_context=response_resource_context(
                        enriched_context,
                        request.resource_context,
                    ),
                    response_freshness_context=response_evidence_freshness_context(
                        enriched_context,
                        request.freshness_context,
                    ),
                    model_trace_snapshot=lambda: snapshot_model_trace(model_trace_scope.collector),
                    history_metadata=generation_state.history_metadata,
                    cleanup=cleanup,
                    turn_service=self._turn_service,
                    turn_execution=execution,
                    dependencies=PostGenerationDependencies(
                        quality_events=quality_events,
                        planning_metadata=planning_metadata,
                        merge_document_verification=merge_document_verification,
                        persist_assistant_turn=persist_assistant_turn,
                        submit_post_turn_review=submit_post_turn_review,
                        trajectory_detail_snapshot=lambda payload: trajectory_detail.snapshot(
                            max_bytes=trajectory_detail_budget(payload)
                        ),
                    ),
                )
            )
            async for terminal_event in post_generation:
                yield StreamTurnEvent(
                    terminal_event.event,
                    terminal_event.payload,
                    terminal_event.revision,
                )
        except asyncio.CancelledError:
            await cleanup()
            self._terminate_open(
                execution,
                ConversationTurnTerminalStatus.CANCELLED,
                "chat_turn_cancelled",
                "chat turn cancelled",
            )
            raise
        except ChatTurnInterruptedError:
            await cleanup()
            interrupted_detail = "chat turn interrupted"
            interrupted_payload: dict[str, Any] = {
                "detail": interrupted_detail,
                "session_id": request.session_id,
            }
            if not execution.closed:
                result = self._turn_service.terminate_turn(
                    execution,
                    terminal_status=ConversationTurnTerminalStatus.CANCELLED,
                    code="chat_turn_interrupted",
                    detail=interrupted_detail,
                    wire_payload=interrupted_payload,
                )
                interrupted_payload = result.to_wire_payload()
            yield StreamTurnEvent("interrupted", interrupted_payload)
        except ChatBackendUnavailableError:
            await cleanup()
            unavailable_detail = "chat backend not configured"
            unavailable_payload: dict[str, Any] = {"detail": unavailable_detail}
            if not execution.closed:
                result = self._turn_service.terminate_turn(
                    execution,
                    terminal_status=ConversationTurnTerminalStatus.UNAVAILABLE,
                    code="chat_backend_unavailable",
                    detail=unavailable_detail,
                    wire_payload=unavailable_payload,
                )
                unavailable_payload = result.to_wire_payload()
            yield StreamTurnEvent("error", unavailable_payload)
        except ChatContentPolicyError as exc:
            await cleanup()
            yield await self._content_policy_event(session, exc, generation_state)
        except Exception as exc:  # noqa: BLE001 - stream failures become bounded events
            await cleanup()
            status = self._upstream_status(exc)
            if status is not None:
                _LOG.warning(
                    "chat stream upstream failure",
                    extra={"request_id": request.request_id, "status_code": status},
                )
                failed_payload: dict[str, Any] = {
                    "code": "chat_stream_failed",
                    "detail": "chat stream failed",
                    "status": status,
                    "reason": f"upstream HTTP {status}",
                }
            else:
                _LOG.warning("chat stream failed: %s", type(exc).__name__, exc_info=True)
                failed_payload = {"detail": "chat stream failed"}
            if not execution.closed:
                result = self._turn_service.terminate_turn(
                    execution,
                    terminal_status=ConversationTurnTerminalStatus.FAILED,
                    code="chat_stream_failed",
                    detail="chat stream failed",
                    wire_payload=failed_payload,
                )
                failed_payload = result.to_wire_payload()
            yield StreamTurnEvent("error", failed_payload)
        finally:
            await cleanup()
            self._terminate_open(
                execution,
                ConversationTurnTerminalStatus.CANCELLED,
                "chat_turn_cancelled",
                "chat turn cancelled",
            )
            deactivate_model_trace(model_trace_scope)

    async def _content_policy_event(
        self,
        session: PreparedStreamSession,
        exc: ChatContentPolicyError,
        generation_state: StreamGenerationState,
    ) -> StreamTurnEvent:
        request = session.request
        if self._progress_metrics is not None:
            self._progress_metrics.increment("content_policy_blocks")
        receipt_persisted = True
        if self._conversation_history_store is not None and session.operator_turn is not None:
            try:
                await append_content_policy_receipt(
                    store=self._conversation_history_store,
                    principal_id=request.user_id,
                    conversation_id=request.session_id,
                    request_id=request.request_id,
                    stage=exc.stage,
                    recorded_at=datetime.now(tz=UTC),
                    history_metadata=generation_state.history_metadata,
                )
            except Exception as receipt_error:  # noqa: BLE001 - preserve stream error
                receipt_persisted = False
                _LOG.error(
                    "chat stream content-policy receipt failed: %s",
                    type(receipt_error).__name__,
                    extra={"request_id": request.request_id},
                )
        policy_payload: dict[str, Any] = {
            "code": "content_policy_block",
            "stage": exc.stage,
            "receipt_persisted": receipt_persisted,
            "detail": str(exc),
        }
        if not session.turn_execution.closed:
            result = self._turn_service.terminate_turn(
                session.turn_execution,
                terminal_status=ConversationTurnTerminalStatus.ABSTAINED,
                code="content_policy_block",
                detail=str(exc),
                wire_payload=policy_payload,
            )
            policy_payload = result.to_wire_payload()
        return StreamTurnEvent("error", policy_payload)

    def _resolved_turn_tools(self) -> tuple[TurnTool, ...]:
        return self._turn_tools() if callable(self._turn_tools) else self._turn_tools

    def _terminate_open(
        self,
        execution: ConversationTurnExecution,
        status: ConversationTurnTerminalStatus,
        code: str,
        detail: str,
    ) -> None:
        if not execution.closed:
            self._turn_service.terminate_turn(
                execution,
                terminal_status=status,
                code=code,
                detail=detail,
                wire_payload={"detail": detail},
            )


__all__ = ["StreamTurnExecutionService", "UpstreamStatusResolver"]
