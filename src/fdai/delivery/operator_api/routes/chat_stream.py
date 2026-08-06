"""Server-Sent Events delivery for read-only console chat."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route

from fdai.core.conversation.answer_planning import AnswerPlanningResult
from fdai.core.conversation.busy_input_coordinator import BusyInputCoordinator
from fdai.core.conversation_assurance import ConversationPolicyRuntime
from fdai.core.metering import InvocationScope, with_invocation_scope
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.conversation_images import (
    ConversationImageConflictError,
    ConversationImageQuotaError,
    ConversationImageStore,
)
from fdai.delivery.operator_api.application import (
    ConversationTurnApplicationService,
    ConversationTurnInput,
    ConversationTurnTerminalStatus,
)
from fdai.delivery.operator_api.application.conversation.verification import (
    AnswerVerification,
    verify_answer,
)
from fdai.delivery.operator_api.routes.chat_action_context import (
    is_explicit_action_draft_request,
    needs_action_context,
)
from fdai.delivery.operator_api.routes.chat_answer_planning import (
    AnswerPlanningDelegate,
    cancel_planning,
    start_shadow_answer_planning,
)
from fdai.delivery.operator_api.routes.chat_answer_quality import (
    review_korean_narrator_answer,
    verify_quality_result,
)
from fdai.delivery.operator_api.routes.chat_backend_common import (
    ChatBackend,
    ChatBackendUnavailableError,
    ChatContentPolicyError,
)
from fdai.delivery.operator_api.routes.chat_backend_router import LatencyRoutedChatBackend
from fdai.delivery.operator_api.routes.chat_busy_input import (
    MAX_STEER_RERUNS,
    ChatTurnInterruptedError,
    answer_with_busy_input,
    append_next_steer,
    interruptible_events,
)
from fdai.delivery.operator_api.routes.chat_content_policy import (
    answer_with_content_policy_recovery,
    collect_stream_with_content_policy_recovery,
)
from fdai.delivery.operator_api.routes.chat_conversation_context import (
    needs_conversation_context,
)
from fdai.delivery.operator_api.routes.chat_current_time import needs_current_time
from fdai.delivery.operator_api.routes.chat_document_evidence import (
    ChatDocumentEvidenceResolver,
    with_document_evidence,
)
from fdai.delivery.operator_api.routes.chat_evidence import needs_operational_evidence
from fdai.delivery.operator_api.routes.chat_evidence_enrichment import (
    AgentChatDelegate,
    ChatBehaviorEvidenceResolver,
    ChatToolResolver,
    ChatWebSearchEvidenceResolver,
    OperationalEvidenceResolverProtocol,
    PlannedChatToolResolver,
    _delegation_summary,
    _retrieval_source_previews,
    _with_behavior_evidence,
    _with_screen_scope,
)
from fdai.delivery.operator_api.routes.chat_evidence_pipeline import (
    has_bound_incident_analysis_context,
    has_screen_incident_analysis_context,
    resolve_parallel_chat_evidence,
)
from fdai.delivery.operator_api.routes.chat_freshness_context import (
    freshness_evidence_refs,
    needs_evidence_freshness_context,
    render_evidence_freshness_answer,
)
from fdai.delivery.operator_api.routes.chat_history import (
    append_content_policy_receipt,
    completed_replay_payload,
)
from fdai.delivery.operator_api.routes.chat_history_context import (
    DEFAULT_CHAT_HISTORY_POLICY,
    BackendChatHistoryCompressor,
    ChatHistoryPolicy,
)
from fdai.delivery.operator_api.routes.chat_image_history import (
    image_turn_metadata,
    persist_operator_turn_with_images,
)
from fdai.delivery.operator_api.routes.chat_intent_graph import (
    IntentGraph,
    IntentGraphPlanner,
    apply_intent_graph_to_answer_plan,
    draft_capability_available,
    plan_semantic_turn,
    planner_context_envelope,
)
from fdai.delivery.operator_api.routes.chat_inventory_compiler import (
    compile_inventory_query,
    inventory_query_requires_semantic_completion,
)
from fdai.delivery.operator_api.routes.chat_llm_usage import (
    is_llm_usage_followup,
    needs_llm_usage,
)
from fdai.delivery.operator_api.routes.chat_log_query import needs_log_query
from fdai.delivery.operator_api.routes.chat_model_trace import (
    activate_model_trace,
    deactivate_model_trace,
    snapshot_model_trace,
)
from fdai.delivery.operator_api.routes.chat_presentation import (
    PresentationDecision,
    select_answer_presentation,
)
from fdai.delivery.operator_api.routes.chat_prompt import (
    _concept_answer,
    _is_grounded_concept_query,
    _ontology_browse_answer,
    _response_locale,
    _with_concept_evidence,
)
from fdai.delivery.operator_api.routes.chat_prompt_ontology import _with_ontology_storage_contract
from fdai.delivery.operator_api.routes.chat_resource_context import resource_followup_verification
from fdai.delivery.operator_api.routes.chat_route_common import (
    DEFAULT_MAX_CHAT_BODY_BYTES,
    AnswerPreferenceResolver,
    AuthorizeFn,
    ModelPreferenceResolver,
    _metering_correlation_id,
    _uses_evidence_fast_path,
    _with_assurance_policy,
    _with_compiled_user_policy,
)
from fdai.delivery.operator_api.routes.chat_screen_data import render_screen_data_answer
from fdai.delivery.operator_api.routes.chat_stream_metrics import record_enqueued_progress_metrics
from fdai.delivery.operator_api.routes.chat_stream_post_generation import (
    PostGenerationContext,
    evidence_timing_status,
    finalize_post_generation,
)
from fdai.delivery.operator_api.routes.chat_stream_protocol import (
    DEFAULT_STREAM_HEARTBEAT_S,
    _chunk_answer_for_stream,
    _sse,
    _sse_heartbeat,
    _with_sse_heartbeats,
)
from fdai.delivery.operator_api.routes.chat_stream_setup import (
    ContentPolicyReplayRequest,
    prepare_chat_stream_request,
)
from fdai.delivery.operator_api.routes.chat_stream_terminal import TurnTimingRecorder
from fdai.delivery.operator_api.routes.chat_subscription_health import needs_subscription_health
from fdai.delivery.operator_api.routes.chat_system_health import render_system_health_answer
from fdai.delivery.operator_api.routes.chat_topology_intent import is_topology_question
from fdai.delivery.operator_api.routes.chat_trajectory_detail import TrajectoryDetailCollector
from fdai.delivery.operator_api.routes.chat_turn_plan import (
    TurnPlanner,
    TurnTool,
    apply_turn_plan_to_answer_plan,
)
from fdai.delivery.operator_api.routes.chat_vision_evidence import (
    vision_source_previews,
)
from fdai.delivery.operator_api.routes.post_turn_review import PostTurnReviewSubmitter
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.providers.user_context import ConversationHistoryStore, UserContextConflictError
from fdai.shared.telemetry import ConversationProgressMetrics, with_correlation

_LOG = logging.getLogger(__name__)
_PRESENTATION_JOIN_TIMEOUT_SECONDS: Final[float] = 5.0


DEFAULT_STREAM_PATH: Final[str] = "/chat/stream"


def make_chat_stream_route(
    *,
    backend: ChatBackend,
    authorize: AuthorizeFn,
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
    model_preference_resolver: ModelPreferenceResolver | None = None,
    answer_preference_resolver: AnswerPreferenceResolver | None = None,
    post_turn_review_submitter: PostTurnReviewSubmitter | None = None,
    busy_input_coordinator: BusyInputCoordinator | None = None,
    document_evidence_resolver: ChatDocumentEvidenceResolver | None = None,
    progress_metrics: ConversationProgressMetrics | None = None,
    turn_planner: TurnPlanner | IntentGraphPlanner | None = None,
    turn_tools: tuple[TurnTool, ...] | Callable[[], tuple[TurnTool, ...]] = (),
    history_policy: ChatHistoryPolicy = DEFAULT_CHAT_HISTORY_POLICY,
    turn_service: ConversationTurnApplicationService | None = None,
    path: str = DEFAULT_STREAM_PATH,
    max_body_bytes: int = DEFAULT_MAX_CHAT_BODY_BYTES,
) -> Route:
    """Build the ``POST /chat/stream`` route (Server-Sent Events).

    Streams the narrator answer token by token as ``event: token`` frames,
    then a terminal ``event: done`` frame carrying the full answer, model,
    router snapshot, and latency. On failure mid-stream an ``event: error``
    frame is emitted and the stream closes. Backends that do not implement
    ``answer_stream`` fall back to a single-shot ``answer`` emitted as one
    token + done, so the FE can always consume the same protocol.
    The route can persist conversation history and review records, but has no
    privileged execution or approval authority.
    """

    history_compressor = BackendChatHistoryCompressor(
        backend=backend,
        max_summary_chars=history_policy.max_summary_chars,
    )
    resolved_turn_service = (
        turn_service if turn_service is not None else ConversationTurnApplicationService()
    )

    async def handler(request: Request) -> StreamingResponse:
        prepared = await prepare_chat_stream_request(
            request,
            authorize=authorize,
            model_preference_resolver=model_preference_resolver,
            answer_preference_resolver=answer_preference_resolver,
            document_evidence_resolver=document_evidence_resolver,
            conversation_history_store=conversation_history_store,
            history_compressor=history_compressor,
            history_policy=history_policy,
            max_body_bytes=max_body_bytes,
        )
        if isinstance(prepared, ContentPolicyReplayRequest):
            if progress_metrics is not None:
                progress_metrics.increment("content_policy_blocks")
            policy_execution = resolved_turn_service.start_turn(
                ConversationTurnInput(
                    principal_id=prepared.user_id,
                    conversation_id=prepared.session_id,
                    request_id=prepared.request_id,
                    correlation_id=_metering_correlation_id(
                        prepared.user_id,
                        prepared.session_id,
                    ),
                    prompt=prepared.clean_prompt,
                    history_turn_count=0,
                    streaming=True,
                )
            )

            async def policy_replay_source() -> AsyncIterator[bytes]:
                detail = "chat request blocked by content policy"
                payload = {
                    "v": 1,
                    "request_id": prepared.request_id,
                    "seq": 1,
                    "revision": 0,
                    "code": "content_policy_block",
                    "stage": prepared.stage,
                    "receipt_persisted": True,
                    "detail": detail,
                }
                abstained = resolved_turn_service.terminate_turn(
                    policy_execution,
                    terminal_status=ConversationTurnTerminalStatus.ABSTAINED,
                    code="content_policy_block",
                    detail=detail,
                    wire_payload=payload,
                )
                yield _sse(
                    "error",
                    abstained.to_wire_payload(),
                )

            return StreamingResponse(
                policy_replay_source(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )
        user_id = prepared.user_id
        preferred_model = prepared.preferred_model
        document_evidence_refs = prepared.document_evidence_refs
        clean_prompt = prepared.clean_prompt
        evidence_prompt = prepared.evidence_prompt
        resource_context = prepared.resource_context
        freshness_context = prepared.freshness_context
        conversation_context = prepared.conversation_context
        view_context = prepared.view_context
        resource_followup = prepared.resource_followup
        compiled_inventory = (
            compile_inventory_query(evidence_prompt) if tool_resolver is not None else None
        )
        semantic_inventory_completion = compiled_inventory is not None and (
            inventory_query_requires_semantic_completion(compiled_inventory, prompt=evidence_prompt)
        )
        deterministic_followup = (
            resource_followup
            or (
                has_bound_incident_analysis_context(
                    clean_prompt, view_context, conversation_context
                )
                or has_screen_incident_analysis_context(clean_prompt, view_context)
            )
            or prepared.inventory_screen_scope
            or prepared.inventory_scope_followup
            or "_read_investigation_context_hold" in view_context
            or is_topology_question(evidence_prompt)
            or (
                compiled_inventory is not None
                and not inventory_query_requires_semantic_completion(
                    compiled_inventory, prompt=evidence_prompt
                )
            )
            or needs_subscription_health(evidence_prompt)
            or needs_log_query(evidence_prompt)
            or needs_action_context(evidence_prompt)
            or needs_conversation_context(evidence_prompt)
            or needs_llm_usage(evidence_prompt)
            or is_llm_usage_followup(evidence_prompt)
            or needs_operational_evidence(evidence_prompt, view_context)
            or needs_current_time(evidence_prompt)
            or (freshness_context is not None and needs_evidence_freshness_context(clean_prompt))
        )
        target_agent = prepared.target_agent
        history = prepared.history
        history_metadata = prepared.history_metadata
        answer_plan = prepared.answer_plan
        session_id = prepared.session_id
        request_id = prepared.request_id
        include_model_trace = prepared.include_model_trace
        turn_execution = resolved_turn_service.start_turn(
            ConversationTurnInput(
                principal_id=user_id,
                conversation_id=session_id,
                request_id=request_id,
                correlation_id=_metering_correlation_id(user_id, session_id),
                prompt=clean_prompt,
                response_locale=_response_locale(clean_prompt, view_context),
                target_agent=target_agent,
                evidence_refs=document_evidence_refs,
                history_turn_count=len(history),
                streaming=True,
            )
        )
        active_turn = None
        if busy_input_coordinator is not None:
            try:
                active_turn = await busy_input_coordinator.begin_turn(
                    session_id=session_id,
                    turn_id=request_id,
                    principal_id=user_id,
                )
            except RuntimeError as exc:
                failed_detail = "conversation session already has an active turn"
                resolved_turn_service.terminate_turn(
                    turn_execution,
                    terminal_status=ConversationTurnTerminalStatus.FAILED,
                    code="chat_session_busy",
                    detail=failed_detail,
                    wire_payload={"detail": failed_detail},
                )
                raise HTTPException(
                    status_code=409,
                    detail=failed_detail,
                ) from exc
        try:
            operator_turn = None
            completed_payload: dict[str, Any] | None = None
            if conversation_history_store is not None:
                if prepared.vision_attachments and conversation_image_store is None:
                    raise HTTPException(
                        status_code=503,
                        detail="conversation image storage is unavailable",
                    )
                operator_recorded_at = datetime.now(tz=UTC)
                try:
                    operator_turn = await persist_operator_turn_with_images(
                        history_store=conversation_history_store,
                        image_store=conversation_image_store,
                        attachments=prepared.vision_attachments,
                        principal_id=user_id,
                        conversation_id=session_id,
                        request_id=request_id,
                        content=clean_prompt,
                        recorded_at=operator_recorded_at,
                        metadata={
                            "document_refs": list(document_evidence_refs),
                            **image_turn_metadata(prepared.vision_attachments),
                            **history_metadata,
                        },
                        ontology_projector=user_context_ontology_projector,
                    )
                except ConversationImageConflictError as exc:
                    raise HTTPException(
                        status_code=409,
                        detail="chat image id conflicts with existing content",
                    ) from exc
                except ConversationImageQuotaError as exc:
                    raise HTTPException(
                        status_code=429,
                        detail="conversation image storage quota exceeded",
                    ) from exc
                except UserContextConflictError as exc:
                    raise HTTPException(
                        status_code=409,
                        detail="chat request id conflicts with an existing turn",
                    ) from exc
                completed_turn = await conversation_history_store.get_turn_by_idempotency(
                    principal_id=user_id,
                    idempotency_key=f"{request_id}:assistant",
                )
                if completed_turn is not None:
                    completed_payload = completed_replay_payload(completed_turn)
        except asyncio.CancelledError:
            if busy_input_coordinator is not None and active_turn is not None:
                await busy_input_coordinator.finish_turn(
                    session_id=session_id,
                    turn_id=request_id,
                    principal_id=user_id,
                )
            cancelled_detail = "chat turn cancelled"
            resolved_turn_service.terminate_turn(
                turn_execution,
                terminal_status=ConversationTurnTerminalStatus.CANCELLED,
                code="chat_turn_cancelled",
                detail=cancelled_detail,
                wire_payload={"detail": cancelled_detail},
            )
            raise
        except Exception:
            if busy_input_coordinator is not None and active_turn is not None:
                await busy_input_coordinator.finish_turn(
                    session_id=session_id,
                    turn_id=request_id,
                    principal_id=user_id,
                )
            failed_detail = "chat stream setup failed"
            resolved_turn_service.terminate_turn(
                turn_execution,
                terminal_status=ConversationTurnTerminalStatus.FAILED,
                code="chat_stream_setup_failed",
                detail=failed_detail,
                wire_payload={"detail": failed_detail},
            )
            raise

        async def event_source() -> AsyncIterator[bytes]:
            nonlocal answer_plan
            model_trace_scope = activate_model_trace(include_model_trace)
            turn_timing = TurnTimingRecorder()
            trajectory_detail = TrajectoryDetailCollector()
            started = turn_timing.started_monotonic
            sequence = 0
            revision = 0
            planning_task: asyncio.Task[AnswerPlanningResult] | None = None
            presentation_task: asyncio.Task[PresentationDecision] | None = None
            cleanup_complete = False
            first_progress_recorded = False

            def frame(event: str, payload: dict[str, Any]) -> bytes:
                nonlocal sequence
                sequence += 1
                return _sse(
                    event,
                    {
                        **payload,
                        "v": 1,
                        "request_id": request_id,
                        "seq": sequence,
                        "revision": revision,
                    },
                )

            async def cleanup() -> None:
                nonlocal cleanup_complete
                if cleanup_complete:
                    return
                await cancel_planning(planning_task)
                if presentation_task is not None and not presentation_task.done():
                    presentation_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await presentation_task
                if busy_input_coordinator is not None and active_turn is not None:
                    try:
                        await busy_input_coordinator.finish_turn(
                            session_id=session_id,
                            turn_id=request_id,
                            principal_id=user_id,
                        )
                    except Exception as exc:  # noqa: BLE001 - preserve terminal response
                        _LOG.warning(
                            "chat stream busy-input cleanup failed: %s",
                            type(exc).__name__,
                            extra={"session_id": session_id, "request_id": request_id},
                            exc_info=True,
                        )
                cleanup_complete = True

            try:
                if completed_payload is not None:
                    if not include_model_trace:
                        completed_payload.pop("model_trace", None)
                    if progress_metrics is not None:
                        progress_metrics.increment("replays")
                        progress_metrics.observe_latency(
                            "time_to_first_confirmed",
                            max(0, int((time.monotonic() - started) * 1000)),
                        )
                    await cleanup()
                    validated_replay = resolved_turn_service.validate_turn_result(
                        turn_execution,
                        completed_payload,
                    )
                    replay_payload = validated_replay.to_wire_payload()
                    _sse(
                        "done",
                        {
                            **replay_payload,
                            "v": 1,
                            "request_id": request_id,
                            "seq": 9_223_372_036_854_775_807,
                            "revision": revision,
                        },
                    )
                    replay = resolved_turn_service.complete_turn(
                        turn_execution,
                        replay_payload,
                    )
                    yield frame("done", replay.to_wire_payload())
                    return
                semantic_plan = None
                if (
                    turn_planner is not None
                    and not prepared.vision_attachments
                    and not _is_grounded_concept_query(clean_prompt)
                    and (
                        not deterministic_followup
                        or semantic_inventory_completion
                        or is_explicit_action_draft_request(clean_prompt)
                    )
                ):
                    semantic_plan_timing = turn_timing.begin("semantic_plan")
                    try:
                        semantic_plan = await plan_semantic_turn(
                            turn_planner,
                            prompt=clean_prompt,
                            tools=turn_tools() if callable(turn_tools) else turn_tools,
                            history=history,
                            attachments=view_context.get("_attachments"),
                            context=planner_context_envelope(
                                view_context,
                                resource_context=resource_context,
                                conversation_context=conversation_context,
                                document_refs=document_evidence_refs,
                            ),
                        )
                    except Exception as exc:  # noqa: BLE001 - shadow plan degrades closed
                        turn_timing.complete(semantic_plan_timing, status="degraded")
                        _LOG.warning(
                            "chat stream turn planning unavailable: %s",
                            type(exc).__name__,
                            extra={"request_id": request_id},
                        )
                    else:
                        turn_timing.complete(semantic_plan_timing, status="completed")
                        answer_plan = (
                            apply_intent_graph_to_answer_plan(answer_plan, semantic_plan)
                            if isinstance(semantic_plan, IntentGraph)
                            else apply_turn_plan_to_answer_plan(answer_plan, semantic_plan)
                        )
                        view_context["_answer_plan"] = answer_plan.to_dict()
                        view_context[
                            "_intent_graph"
                            if isinstance(semantic_plan, IntentGraph)
                            else "_turn_plan"
                        ] = semantic_plan.to_dict()
                        if semantic_plan.requires_confirmation:
                            if isinstance(
                                semantic_plan, IntentGraph
                            ) and not draft_capability_available(
                                semantic_plan,
                                turn_tools() if callable(turn_tools) else turn_tools,
                            ):
                                await cleanup()
                                unavailable_detail = "draft capability is no longer available"
                                unavailable_payload = {
                                    "error": unavailable_detail,
                                    "status": 409,
                                }
                                unavailable = resolved_turn_service.terminate_turn(
                                    turn_execution,
                                    terminal_status=ConversationTurnTerminalStatus.UNAVAILABLE,
                                    code="draft_capability_unavailable",
                                    detail=unavailable_detail,
                                    wire_payload=unavailable_payload,
                                )
                                yield frame(
                                    "error",
                                    unavailable.to_wire_payload(),
                                )
                                return
                            await cleanup()
                            draft_payload = {
                                "answer": "Review this action draft before submitting it.",
                                "model": "semantic-turn-planner",
                                "source": "action-draft",
                                "action_draft": semantic_plan.confirmation_payload(
                                    request_id=request_id,
                                    session_id=session_id,
                                ),
                                "turn_timing": turn_timing.snapshot(),
                            }
                            draft = resolved_turn_service.complete_turn(
                                turn_execution,
                                draft_payload,
                                terminal_status=ConversationTurnTerminalStatus.UNVERIFIED,
                            )
                            yield frame(
                                "done",
                                draft.to_wire_payload(),
                            )
                            return
                yield frame(
                    "status",
                    {
                        "phase": "evidence_resolving",
                        "label": "Checking read-only evidence",
                        "sources": _retrieval_source_previews(
                            view_context,
                            server_owned=False,
                        ),
                    },
                )
                # Vision escalation: when the turn carries validated image
                # attachments, surface a read-only "analyzing" phase before the
                # narrator composes, symmetric to the web_search_* phases.
                vision_previews = vision_source_previews(view_context.get("_attachments"))
                if vision_previews:
                    yield frame(
                        "status",
                        {
                            "phase": "vision_analyzing",
                            "label": f"Analyzing {len(vision_previews)} attached image(s)",
                            "sources": vision_previews,
                        },
                    )
                enriched_context = await _with_compiled_user_policy(
                    view_context,
                    user_id=user_id,
                    store=conversation_policy_store,
                )
                enriched_context = await _with_assurance_policy(
                    enriched_context,
                    user_id=user_id,
                    request_id=request_id,
                    runtime=conversation_assurance_runtime,
                )
                enriched_context = with_document_evidence(
                    enriched_context,
                    document_evidence_refs,
                )
                enriched_context = _with_screen_scope(
                    evidence_prompt,
                    enriched_context,
                    agent_delegate,
                    conversation_context=conversation_context,
                    target_agent=target_agent,
                )
                enriched_context = await _with_behavior_evidence(
                    evidence_prompt,
                    enriched_context,
                    behavior_resolver,
                )
                progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=128)
                evidence_outcomes: list[str] = []

                async def observe_evidence_progress(event: Mapping[str, Any]) -> None:
                    nonlocal first_progress_recorded
                    progress_event = dict(event)
                    if progress_event.get("event") == "milestone":
                        progress_event.setdefault("recorded_at", datetime.now(tz=UTC).isoformat())
                    trajectory_detail.observe(progress_event)
                    if progress_event.get("event") == "branch" and isinstance(
                        progress_event.get("status"), str
                    ):
                        evidence_outcomes.append(str(progress_event["status"]))
                    if progress_metrics is not None and progress_queue.full():
                        progress_metrics.increment("queue_saturation")
                    await progress_queue.put(progress_event)
                    if progress_metrics is not None:
                        first_progress_recorded = record_enqueued_progress_metrics(
                            progress_metrics,
                            progress_event,
                            elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                            first_progress_recorded=first_progress_recorded,
                        )

                evidence_timing = turn_timing.begin("evidence")
                evidence_task = asyncio.create_task(
                    resolve_parallel_chat_evidence(
                        request_id=request_id,
                        prompt=evidence_prompt,
                        view_context=enriched_context,
                        user_id=user_id,
                        session_id=session_id,
                        conversation_context=conversation_context,
                        target_agent=target_agent,
                        tool_resolver=tool_resolver,
                        planned_tool_resolver=planned_tool_resolver,
                        evidence_resolver=evidence_resolver,
                        agent_delegate=agent_delegate,
                        web_search_resolver=web_search_resolver,
                        progress_observer=observe_evidence_progress,
                        intent_graph=(
                            semantic_plan if isinstance(semantic_plan, IntentGraph) else None
                        ),
                    )
                )
                try:
                    while not evidence_task.done() or not progress_queue.empty():
                        try:
                            progress_event = await asyncio.wait_for(
                                progress_queue.get(),
                                timeout=0.25,
                            )
                        except TimeoutError:
                            continue
                        event_name = progress_event.pop("event", None)
                        if event_name in {"activity", "milestone", "status", "branch"}:
                            yield frame(event_name, progress_event)
                    enriched_context = await evidence_task
                    turn_timing.complete(
                        evidence_timing,
                        status=evidence_timing_status(evidence_outcomes),
                    )
                finally:
                    if not evidence_task.done():
                        evidence_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await evidence_task
                enriched_context = _with_concept_evidence(evidence_prompt, enriched_context)
                enriched_context = _with_ontology_storage_contract(
                    evidence_prompt, enriched_context
                )
                answer_plan, planning_task = start_shadow_answer_planning(
                    prompt=evidence_prompt,
                    plan=answer_plan,
                    delegate=(
                        None
                        if "_screen_scope" in enriched_context
                        or "_ontology_storage_contract" in enriched_context
                        or deterministic_followup
                        or _uses_evidence_fast_path(enriched_context)
                        else answer_planning_delegate
                    ),
                )
                enriched_context["_answer_plan"] = answer_plan.to_dict()
                delegation = _delegation_summary(enriched_context)
                has_operational_evidence = "_operational_evidence" in enriched_context
                evidence_fast_path = _uses_evidence_fast_path(enriched_context)
                response_locale = _response_locale(clean_prompt, enriched_context)
                freshness_answer = render_evidence_freshness_answer(
                    clean_prompt,
                    freshness_context,
                    locale=response_locale,
                )
                health_answer = render_system_health_answer(
                    enriched_context,
                    locale=response_locale,
                )
                screen_answer = render_screen_data_answer(
                    clean_prompt,
                    enriched_context,
                    locale=response_locale,
                )
                concept_answer = (
                    _concept_answer(enriched_context, answer_plan)
                    if response_locale is None
                    else None
                )
                ontology_answer = _ontology_browse_answer(
                    clean_prompt,
                    enriched_context,
                    locale=response_locale,
                )
                contextual_verification = (
                    resource_followup_verification(enriched_context, resource_context)
                    if resource_followup
                    else None
                )
                contextual_answer = (
                    contextual_verification.answer if contextual_verification is not None else None
                )
                freshness_verification = (
                    AnswerVerification(
                        status="verified",
                        answer=freshness_answer,
                        authority="server_evidence_freshness",
                        checks_completed=1,
                        checks_total=1,
                        evidence_refs=freshness_evidence_refs(freshness_context),
                        reason_code="evidence_freshness_grounded",
                    )
                    if freshness_answer is not None and freshness_context is not None
                    else None
                )
                if vision_previews:
                    yield frame(
                        "status",
                        {
                            "phase": "vision_grounded",
                            "label": f"Grounded on {len(vision_previews)} attached image(s)",
                            "completed": len(vision_previews),
                            "total": len(vision_previews),
                            "sources": vision_previews,
                        },
                    )
                yield frame(
                    "status",
                    {
                        "phase": "generating",
                        "label": (
                            "Evidence ready; composing bounded answer"
                            if evidence_fast_path
                            or ontology_answer is not None
                            or health_answer is not None
                            or screen_answer is not None
                            else "Evidence ready; drafting answer"
                        ),
                        "authority": (
                            "server_intent_graph"
                            if isinstance(enriched_context.get("_intent_graph_evidence"), Mapping)
                            and enriched_context["_intent_graph_evidence"].get("status")
                            != "completed"
                            else "server_read_model"
                            if has_operational_evidence or health_answer is not None
                            else "client_snapshot"
                        ),
                        "sources": _retrieval_source_previews(
                            enriched_context,
                            server_owned=True,
                        ),
                    },
                )

                generation_timing = turn_timing.begin("generation")
                if evidence_fast_path:
                    presentation_base_plan = answer_plan
                    default_presentation = await select_answer_presentation(
                        backend=object(),
                        prompt=clean_prompt,
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
                            backend=backend,
                            prompt=clean_prompt,
                            plan=presentation_base_plan,
                            view_context=enriched_context,
                        )
                    )
                stream = getattr(backend, "answer_stream", None)
                provisional_answer = ""
                model_generated = False
                terminal_model: Any = None
                terminal_router: Any = None
                terminal_usage: Any = None
                if freshness_answer is not None:
                    provisional_answer = freshness_answer
                    terminal_model = "evidence-freshness"
                    for chunk in _chunk_answer_for_stream(provisional_answer):
                        yield frame("token", {"delta": chunk})
                elif contextual_answer is not None:
                    provisional_answer = contextual_answer
                    terminal_model = "heimdall-read-investigation"
                    for chunk in _chunk_answer_for_stream(provisional_answer):
                        yield frame("token", {"delta": chunk})
                elif evidence_fast_path:
                    canonical = verify_answer(
                        "",
                        enriched_context,
                        locale=_response_locale(clean_prompt, enriched_context),
                    )
                    provisional_answer = canonical.answer
                    terminal_model = "evidence-verifier"
                    for chunk in _chunk_answer_for_stream(provisional_answer):
                        yield frame("token", {"delta": chunk})
                elif ontology_answer is not None:
                    provisional_answer = ontology_answer
                    terminal_model = "ontology-snapshot"
                    for chunk in _chunk_answer_for_stream(provisional_answer):
                        yield frame("token", {"delta": chunk})
                elif health_answer is not None:
                    provisional_answer = health_answer
                    terminal_model = "read-model-health"
                    for chunk in _chunk_answer_for_stream(provisional_answer):
                        yield frame("token", {"delta": chunk})
                elif screen_answer is not None:
                    provisional_answer = screen_answer
                    terminal_model = "bragi-screen-t0"
                    for chunk in _chunk_answer_for_stream(provisional_answer):
                        yield frame("token", {"delta": chunk})
                elif concept_answer is not None:
                    provisional_answer = concept_answer
                    terminal_model = "concept-glossary"
                    for chunk in _chunk_answer_for_stream(provisional_answer):
                        yield frame("token", {"delta": chunk})
                elif stream is not None:
                    model_generated = True
                    steer_reruns = 0
                    while steer_reruns <= MAX_STEER_RERUNS:

                        async def invoke_stream(
                            candidate_history: list[dict[str, str]],
                        ) -> AsyncIterator[dict[str, Any]]:
                            if isinstance(backend, LatencyRoutedChatBackend):
                                async for candidate_event in backend.answer_stream(
                                    prompt=clean_prompt,
                                    view_context=enriched_context,
                                    history=candidate_history,
                                    preferred_model=preferred_model,
                                ):
                                    yield candidate_event
                            else:
                                async for candidate_event in stream(
                                    prompt=clean_prompt,
                                    view_context=enriched_context,
                                    history=candidate_history,
                                ):
                                    yield candidate_event

                        async def recovered_stream() -> AsyncIterator[dict[str, Any]]:
                            nonlocal history_metadata
                            buffered, recovery = await collect_stream_with_content_policy_recovery(
                                invoke=invoke_stream,
                                history=history,
                                compressor=history_compressor,
                                policy=history_policy,
                            )
                            if recovery is not None:
                                history_metadata = recovery.metadata()
                                if progress_metrics is not None:
                                    progress_metrics.increment("history_policy_degraded")
                            for buffered_event in buffered:
                                yield buffered_event

                        provisional_answer = ""
                        with (
                            with_correlation(_metering_correlation_id(user_id, session_id)),
                            with_invocation_scope(InvocationScope.OPERATOR_CHAT),
                        ):
                            events = _with_sse_heartbeats(
                                recovered_stream(), interval=DEFAULT_STREAM_HEARTBEAT_S
                            )
                            async for event in interruptible_events(
                                events,
                                active_turn=active_turn,
                            ):
                                if event is None:
                                    yield _sse_heartbeat()
                                    continue
                                etype = event.get("type")
                                if etype == "token":
                                    delta = event.get("delta", "")
                                    if isinstance(delta, str):
                                        provisional_answer += delta
                                    yield frame("token", {"delta": delta})
                                elif etype == "done":
                                    answer = event.get("answer")
                                    if isinstance(answer, str) and answer:
                                        provisional_answer = answer
                                    terminal_model = event.get("model")
                                    terminal_router = event.get("router")
                                    terminal_usage = event.get("usage")
                        if steer_reruns >= MAX_STEER_RERUNS or not await append_next_steer(
                            history=history,
                            coordinator=busy_input_coordinator,
                            active_turn=active_turn,
                        ):
                            break
                        steer_reruns += 1
                        revision += 1
                        yield frame(
                            "status",
                            {
                                "phase": "steering",
                                "label": "Applying operator guidance",
                            },
                        )
                else:
                    model_generated = True

                    async def invoke_backend(
                        active_history: list[dict[str, str]],
                    ) -> dict[str, Any]:
                        nonlocal history_metadata

                        async def invoke_raw(
                            candidate_history: list[dict[str, str]],
                        ) -> dict[str, Any]:
                            if isinstance(backend, LatencyRoutedChatBackend):
                                return await backend.answer(
                                    prompt=clean_prompt,
                                    view_context=enriched_context,
                                    history=candidate_history,
                                    preferred_model=preferred_model,
                                )
                            return await backend.answer(
                                prompt=clean_prompt,
                                view_context=enriched_context,
                                history=candidate_history,
                            )

                        backend_reply, recovery = await answer_with_content_policy_recovery(
                            invoke=invoke_raw,
                            history=active_history,
                            compressor=history_compressor,
                            policy=history_policy,
                        )
                        if recovery is not None:
                            history_metadata = recovery.metadata()
                            if progress_metrics is not None:
                                progress_metrics.increment("history_policy_degraded")
                        return backend_reply

                    with (
                        with_correlation(_metering_correlation_id(user_id, session_id)),
                        with_invocation_scope(InvocationScope.OPERATOR_CHAT),
                    ):
                        reply = await answer_with_busy_input(
                            invoke=invoke_backend,
                            history=history,
                            coordinator=busy_input_coordinator,
                            active_turn=active_turn,
                        )
                    answer = reply.get("answer", "")
                    if isinstance(answer, str) and answer:
                        provisional_answer = answer
                        # Chunk the one-shot answer so a non-streaming backend
                        # still renders progressively in the deck. ~4-char
                        # groups match the client-side typewriter cadence in
                        # console/src/deck/backend.ts::chunksForTypewriter -
                        # small enough to look live, whole-word aligned so
                        # nothing breaks mid-token.
                        for chunk in _chunk_answer_for_stream(answer):
                            yield frame("token", {"delta": chunk})
                    terminal_model = reply.get("model")
                    terminal_router = reply.get("router")
                    terminal_usage = reply.get("usage")

                post_generation = finalize_post_generation(
                    PostGenerationContext(
                        backend=backend,
                        presentation_task=presentation_task,
                        presentation_timeout_seconds=_PRESENTATION_JOIN_TIMEOUT_SECONDS,
                        answer_plan=answer_plan,
                        enriched_context=enriched_context,
                        provisional_answer=provisional_answer,
                        terminal_model=terminal_model,
                        terminal_router=terminal_router,
                        terminal_usage=terminal_usage,
                        started=started,
                        turn_timing=turn_timing,
                        generation_timing=generation_timing,
                        model_generated=model_generated,
                        preferred_model=preferred_model,
                        response_locale=response_locale,
                        active_turn=active_turn,
                        user_id=user_id,
                        session_id=session_id,
                        request_id=request_id,
                        clean_prompt=clean_prompt,
                        review_quality=review_korean_narrator_answer,
                        verify_quality=verify_quality_result,
                        freshness_verification=freshness_verification,
                        contextual_verification=contextual_verification,
                        document_evidence_refs=document_evidence_refs,
                        progress_metrics=progress_metrics,
                        revision=revision,
                        planning_task=planning_task,
                        evidence_fast_path=evidence_fast_path,
                        ontology_answer=ontology_answer,
                        health_answer=health_answer,
                        screen_answer=screen_answer,
                        concept_answer=concept_answer,
                        contextual_answer=contextual_answer,
                        freshness_answer=freshness_answer,
                        delegation=delegation,
                        resource_context=resource_context,
                        freshness_context=freshness_context,
                        model_trace_snapshot=lambda: snapshot_model_trace(
                            model_trace_scope.collector
                        ),
                        history_metadata=history_metadata,
                        trajectory_detail=trajectory_detail,
                        conversation_history_store=conversation_history_store,
                        user_context_ontology_projector=user_context_ontology_projector,
                        operator_turn=operator_turn,
                        post_turn_review_submitter=post_turn_review_submitter,
                        cleanup=cleanup,
                        turn_service=resolved_turn_service,
                        turn_execution=turn_execution,
                    )
                )
                async for terminal_frame in post_generation:
                    revision = terminal_frame.revision
                    if terminal_frame.event is None:
                        yield _sse_heartbeat()
                    elif terminal_frame.payload is not None:
                        yield frame(terminal_frame.event, terminal_frame.payload)
            except asyncio.CancelledError:
                await cleanup()
                cancelled_detail = "chat turn cancelled"
                if not turn_execution.closed:
                    resolved_turn_service.terminate_turn(
                        turn_execution,
                        terminal_status=ConversationTurnTerminalStatus.CANCELLED,
                        code="chat_turn_cancelled",
                        detail=cancelled_detail,
                        wire_payload={"detail": cancelled_detail},
                    )
                raise
            except ChatTurnInterruptedError:
                await cleanup()
                interrupted_payload = {
                    "detail": "chat turn interrupted",
                    "session_id": session_id,
                }
                wire_interrupted_payload: dict[str, Any] = interrupted_payload
                if not turn_execution.closed:
                    interrupted = resolved_turn_service.terminate_turn(
                        turn_execution,
                        terminal_status=ConversationTurnTerminalStatus.CANCELLED,
                        code="chat_turn_interrupted",
                        detail=interrupted_payload["detail"],
                        wire_payload=interrupted_payload,
                    )
                    wire_interrupted_payload = interrupted.to_wire_payload()
                yield frame("interrupted", wire_interrupted_payload)
            except ChatBackendUnavailableError:
                await cleanup()
                unavailable_detail = "chat backend not configured"
                unavailable_payload = {"detail": unavailable_detail}
                wire_unavailable_payload: dict[str, Any] = unavailable_payload
                if not turn_execution.closed:
                    unavailable = resolved_turn_service.terminate_turn(
                        turn_execution,
                        terminal_status=ConversationTurnTerminalStatus.UNAVAILABLE,
                        code="chat_backend_unavailable",
                        detail=unavailable_detail,
                        wire_payload=unavailable_payload,
                    )
                    wire_unavailable_payload = unavailable.to_wire_payload()
                yield frame("error", wire_unavailable_payload)
            except ChatContentPolicyError as exc:
                await cleanup()
                if progress_metrics is not None:
                    progress_metrics.increment("content_policy_blocks")
                receipt_persisted = True
                if conversation_history_store is not None and operator_turn is not None:
                    try:
                        await append_content_policy_receipt(
                            store=conversation_history_store,
                            principal_id=user_id,
                            conversation_id=session_id,
                            request_id=request_id,
                            stage=exc.stage,
                            recorded_at=datetime.now(tz=UTC),
                            history_metadata=history_metadata,
                        )
                    except Exception as receipt_error:  # noqa: BLE001 - preserve stream error
                        receipt_persisted = False
                        _LOG.error(
                            "chat stream content-policy receipt failed: %s",
                            type(receipt_error).__name__,
                            extra={"request_id": request_id},
                        )
                policy_detail = str(exc)
                policy_payload = {
                    "code": "content_policy_block",
                    "stage": exc.stage,
                    "receipt_persisted": receipt_persisted,
                    "detail": policy_detail,
                }
                wire_policy_payload: dict[str, Any] = policy_payload
                if not turn_execution.closed:
                    abstained = resolved_turn_service.terminate_turn(
                        turn_execution,
                        terminal_status=ConversationTurnTerminalStatus.ABSTAINED,
                        code="content_policy_block",
                        detail=policy_detail,
                        wire_payload=policy_payload,
                    )
                    wire_policy_payload = abstained.to_wire_payload()
                yield frame("error", wire_policy_payload)
            except HTTPException as exc:
                _LOG.warning(
                    "chat stream HTTP failure",
                    extra={"request_id": request_id, "status_code": exc.status_code},
                )
                await cleanup()
                http_status = exc.status_code if 400 <= exc.status_code <= 599 else 500
                http_reason = f"upstream HTTP {http_status}"
                failure_detail = "chat stream failed"
                failed_payload = {
                    "code": "chat_stream_failed",
                    "detail": failure_detail,
                    "status": http_status,
                    "reason": http_reason,
                }
                wire_failed_payload: dict[str, Any] = failed_payload
                if not turn_execution.closed:
                    failed = resolved_turn_service.terminate_turn(
                        turn_execution,
                        terminal_status=ConversationTurnTerminalStatus.FAILED,
                        code="chat_stream_failed",
                        detail=failure_detail,
                        wire_payload=failed_payload,
                    )
                    wire_failed_payload = failed.to_wire_payload()
                yield frame("error", wire_failed_payload)
            except Exception as exc:  # noqa: BLE001 - surface as a stream error, never 500 mid-stream
                _LOG.warning("chat stream failed: %s", type(exc).__name__, exc_info=True)
                await cleanup()
                failure_detail = "chat stream failed"
                failed_payload = {"detail": failure_detail}
                wire_failure_payload: dict[str, Any] = failed_payload
                if not turn_execution.closed:
                    failed = resolved_turn_service.terminate_turn(
                        turn_execution,
                        terminal_status=ConversationTurnTerminalStatus.FAILED,
                        code="chat_stream_failed",
                        detail=failure_detail,
                        wire_payload=failed_payload,
                    )
                    wire_failure_payload = failed.to_wire_payload()
                yield frame("error", wire_failure_payload)
            finally:
                await cleanup()
                if not turn_execution.closed:
                    cancelled_detail = "chat turn cancelled"
                    resolved_turn_service.terminate_turn(
                        turn_execution,
                        terminal_status=ConversationTurnTerminalStatus.CANCELLED,
                        code="chat_turn_cancelled",
                        detail=cancelled_detail,
                        wire_payload={"detail": cancelled_detail},
                    )
                deactivate_model_trace(model_trace_scope)

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return Route(path, handler, methods=["POST"])
