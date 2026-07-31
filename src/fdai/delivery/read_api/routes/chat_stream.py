"""Server-Sent Events delivery for read-only console chat."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Mapping
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
from fdai.delivery.read_api.routes.chat_answer_planning import (
    AnswerPlanningDelegate,
    cancel_planning,
    planning_metadata,
    start_shadow_answer_planning,
)
from fdai.delivery.read_api.routes.chat_answer_quality import (
    AnswerQualityResult,
    review_korean_narrator_answer,
    verify_quality_result,
)
from fdai.delivery.read_api.routes.chat_backend_common import (
    ChatBackend,
    ChatBackendUnavailableError,
)
from fdai.delivery.read_api.routes.chat_backend_router import LatencyRoutedChatBackend
from fdai.delivery.read_api.routes.chat_busy_input import (
    MAX_STEER_RERUNS,
    ChatTurnInterruptedError,
    answer_with_busy_input,
    append_next_steer,
    interruptible_events,
)
from fdai.delivery.read_api.routes.chat_document_evidence import (
    ChatDocumentEvidenceResolver,
    merge_document_verification,
    with_document_evidence,
)
from fdai.delivery.read_api.routes.chat_evidence_enrichment import (
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
from fdai.delivery.read_api.routes.chat_evidence_pipeline import (
    resolve_parallel_chat_evidence,
)
from fdai.delivery.read_api.routes.chat_history import (
    append_assistant_turn,
    append_operator_turn,
    completed_replay_payload,
    replay_metadata,
)
from fdai.delivery.read_api.routes.chat_model_trace import (
    activate_model_trace,
    deactivate_model_trace,
    snapshot_model_trace,
)
from fdai.delivery.read_api.routes.chat_prompt import (
    _concept_answer,
    _ontology_browse_answer,
    _response_locale,
    _with_concept_evidence,
)
from fdai.delivery.read_api.routes.chat_prompt_ontology import _with_ontology_storage_contract
from fdai.delivery.read_api.routes.chat_resource_context import (
    resource_followup_verification,
    response_resource_context,
)
from fdai.delivery.read_api.routes.chat_route_common import (
    DEFAULT_MAX_CHAT_BODY_BYTES,
    AnswerPreferenceResolver,
    AuthorizeFn,
    ModelPreferenceResolver,
    _metering_correlation_id,
    _turn_metadata,
    _uses_evidence_fast_path,
    _with_assurance_policy,
    _with_compiled_user_policy,
)
from fdai.delivery.read_api.routes.chat_screen_data import render_screen_data_answer
from fdai.delivery.read_api.routes.chat_stream_metrics import record_enqueued_progress_metrics
from fdai.delivery.read_api.routes.chat_stream_protocol import (
    DEFAULT_STREAM_HEARTBEAT_S,
    _chunk_answer_for_stream,
    _sse,
    _sse_heartbeat,
    _with_sse_heartbeats,
)
from fdai.delivery.read_api.routes.chat_stream_setup import prepare_chat_stream_request
from fdai.delivery.read_api.routes.chat_stream_terminal import (
    TurnTimingRecorder,
    TurnTimingStatus,
    build_done_payload,
    verification_events,
)
from fdai.delivery.read_api.routes.chat_system_health import render_system_health_answer
from fdai.delivery.read_api.routes.chat_trajectory_detail import (
    TrajectoryDetailCollector,
    trajectory_detail_budget,
)
from fdai.delivery.read_api.routes.chat_turn_plan import (
    TurnPlanner,
    TurnTool,
    apply_turn_plan_to_answer_plan,
)
from fdai.delivery.read_api.routes.chat_verification import verify_answer
from fdai.delivery.read_api.routes.chat_vision_evidence import (
    vision_source_previews,
)
from fdai.delivery.read_api.routes.post_turn_review import (
    PostTurnReviewSubmission,
    PostTurnReviewSubmitter,
    explicit_corrections,
)
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.providers.user_context import ConversationHistoryStore, UserContextConflictError
from fdai.shared.telemetry import ConversationProgressMetrics, with_correlation

_LOG = logging.getLogger(__name__)


DEFAULT_STREAM_PATH: Final[str] = "/chat/stream"


def _evidence_timing_status(outcomes: list[str]) -> TurnTimingStatus:
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
    user_context_ontology_projector: UserContextOntologyProjector | None = None,
    model_preference_resolver: ModelPreferenceResolver | None = None,
    answer_preference_resolver: AnswerPreferenceResolver | None = None,
    post_turn_review_submitter: PostTurnReviewSubmitter | None = None,
    busy_input_coordinator: BusyInputCoordinator | None = None,
    document_evidence_resolver: ChatDocumentEvidenceResolver | None = None,
    progress_metrics: ConversationProgressMetrics | None = None,
    turn_planner: TurnPlanner | None = None,
    turn_tools: tuple[TurnTool, ...] = (),
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
    Read-only in the FDAI sense - no state mutation, no privileged call.
    """

    async def handler(request: Request) -> StreamingResponse:
        prepared = await prepare_chat_stream_request(
            request,
            authorize=authorize,
            model_preference_resolver=model_preference_resolver,
            answer_preference_resolver=answer_preference_resolver,
            document_evidence_resolver=document_evidence_resolver,
            max_body_bytes=max_body_bytes,
        )
        user_id = prepared.user_id
        preferred_model = prepared.preferred_model
        document_evidence_refs = prepared.document_evidence_refs
        clean_prompt = prepared.clean_prompt
        evidence_prompt = prepared.evidence_prompt
        resource_context = prepared.resource_context
        resource_followup = prepared.resource_followup
        deterministic_followup = resource_followup or prepared.inventory_scope_followup
        view_context = prepared.view_context
        conversation_context = prepared.conversation_context
        target_agent = prepared.target_agent
        history = prepared.history
        answer_plan = prepared.answer_plan
        session_id = prepared.session_id
        request_id = prepared.request_id
        include_model_trace = prepared.include_model_trace
        active_turn = None
        if busy_input_coordinator is not None:
            try:
                active_turn = await busy_input_coordinator.begin_turn(
                    session_id=session_id,
                    turn_id=request_id,
                    principal_id=user_id,
                )
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=409,
                    detail="conversation session already has an active turn",
                ) from exc
        try:
            operator_turn = None
            completed_payload: dict[str, Any] | None = None
            if conversation_history_store is not None:
                try:
                    operator_turn = await append_operator_turn(
                        store=conversation_history_store,
                        principal_id=user_id,
                        conversation_id=session_id,
                        request_id=request_id,
                        content=clean_prompt,
                        recorded_at=datetime.now(tz=UTC),
                        metadata={"document_refs": list(document_evidence_refs)},
                        ontology_projector=user_context_ontology_projector,
                    )
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
        except Exception:
            if busy_input_coordinator is not None and active_turn is not None:
                await busy_input_coordinator.finish_turn(
                    session_id=session_id,
                    turn_id=request_id,
                    principal_id=user_id,
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
            cleanup_complete = False
            first_progress_recorded = False

            def frame(event: str, payload: dict[str, Any]) -> bytes:
                nonlocal sequence
                sequence += 1
                return _sse(
                    event,
                    {
                        "v": 1,
                        "request_id": request_id,
                        "seq": sequence,
                        "revision": revision,
                        **payload,
                    },
                )

            async def cleanup() -> None:
                nonlocal cleanup_complete
                if cleanup_complete:
                    return
                await cancel_planning(planning_task)
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
                    yield frame("done", completed_payload)
                    return
                if turn_planner is not None and not deterministic_followup:
                    semantic_plan_timing = turn_timing.begin("semantic_plan")
                    try:
                        semantic_plan = await turn_planner.plan_turn(
                            prompt=clean_prompt,
                            tools=turn_tools,
                            history=history,
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
                        answer_plan = apply_turn_plan_to_answer_plan(answer_plan, semantic_plan)
                        view_context["_answer_plan"] = answer_plan.to_dict()
                        view_context["_turn_plan"] = semantic_plan.to_dict()
                        if semantic_plan.requires_confirmation:
                            await cleanup()
                            yield frame(
                                "done",
                                {
                                    "answer": "Review this action draft before submitting it.",
                                    "model": "semantic-turn-planner",
                                    "source": "action-draft",
                                    "action_draft": semantic_plan.confirmation_payload(
                                        request_id=request_id,
                                        session_id=session_id,
                                    ),
                                    "turn_timing": turn_timing.snapshot(),
                                },
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
                        status=_evidence_timing_status(evidence_outcomes),
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
                            "server_read_model"
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
                stream = getattr(backend, "answer_stream", None)
                provisional_answer = ""
                model_generated = False
                terminal_model: Any = None
                terminal_router: Any = None
                terminal_usage: Any = None
                if contextual_answer is not None:
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
                        if isinstance(backend, LatencyRoutedChatBackend):
                            upstream = backend.answer_stream(
                                prompt=clean_prompt,
                                view_context=enriched_context,
                                history=history,
                                preferred_model=preferred_model,
                            )
                        else:
                            upstream = stream(
                                prompt=clean_prompt,
                                view_context=enriched_context,
                                history=history,
                            )
                        provisional_answer = ""
                        with (
                            with_correlation(_metering_correlation_id(user_id, session_id)),
                            with_invocation_scope(InvocationScope.OPERATOR_CHAT),
                        ):
                            events = _with_sse_heartbeats(
                                upstream, interval=DEFAULT_STREAM_HEARTBEAT_S
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
                        if isinstance(backend, LatencyRoutedChatBackend):
                            return await backend.answer(
                                prompt=clean_prompt,
                                view_context=enriched_context,
                                history=active_history,
                                preferred_model=preferred_model,
                            )
                        return await backend.answer(
                            prompt=clean_prompt,
                            view_context=enriched_context,
                            history=active_history,
                        )

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

                generation_ms = int((time.monotonic() - started) * 1000)
                turn_timing.complete(generation_timing, status="completed")
                yield frame(
                    "provisional",
                    {
                        "answer": provisional_answer,
                        "model": terminal_model,
                        "generation_ms": generation_ms,
                    },
                )
                quality: AnswerQualityResult | None = None
                if model_generated:
                    quality_timing = turn_timing.begin("quality_review")

                    async def invoke_quality(
                        quality_prompt: str,
                        quality_context: dict[str, Any],
                    ) -> dict[str, Any]:
                        if isinstance(backend, LatencyRoutedChatBackend):
                            return await backend.answer(
                                prompt=quality_prompt,
                                view_context=quality_context,
                                history=[],
                                preferred_model=str(terminal_model or preferred_model or "")
                                or None,
                            )
                        return await backend.answer(
                            prompt=quality_prompt,
                            view_context=quality_context,
                            history=[],
                        )

                    async def quality_source() -> AsyncIterator[dict[str, Any]]:
                        with (
                            with_correlation(_metering_correlation_id(user_id, session_id)),
                            with_invocation_scope(InvocationScope.OPERATOR_CHAT),
                        ):
                            result = await review_korean_narrator_answer(
                                answer=provisional_answer,
                                view_context=enriched_context,
                                locale=response_locale,
                                invoke=invoke_quality,
                            )
                        yield {"result": result}

                    quality_events = _with_sse_heartbeats(
                        quality_source(), interval=DEFAULT_STREAM_HEARTBEAT_S
                    )
                    async for quality_event in interruptible_events(
                        quality_events,
                        active_turn=active_turn,
                    ):
                        if quality_event is None:
                            yield _sse_heartbeat()
                            continue
                        candidate = quality_event.get("result")
                        if isinstance(candidate, AnswerQualityResult):
                            quality = candidate
                    turn_timing.complete(
                        quality_timing,
                        status="completed" if quality is not None else "degraded",
                    )

                verification_timing = turn_timing.begin("verification")
                verification = (
                    contextual_verification
                    if contextual_verification is not None
                    else verify_quality_result(
                        quality,
                        enriched_context,
                        locale=response_locale,
                    )
                    if quality is not None
                    else verify_answer(
                        provisional_answer,
                        enriched_context,
                        locale=response_locale,
                    )
                )
                verification = merge_document_verification(
                    verification,
                    document_evidence_refs,
                )
                if progress_metrics is not None and verification.answer != provisional_answer:
                    progress_metrics.increment("corrections")
                terminal_events, revision = verification_events(
                    provisional_answer,
                    verification,
                    revision,
                )
                for event_name, payload in terminal_events:
                    yield frame(event_name, payload)
                turn_timing.complete(
                    verification_timing,
                    status=_verification_timing_status(verification.status),
                )
                if verification.status != "unverified":
                    if progress_metrics is not None:
                        progress_metrics.observe_latency(
                            "time_to_first_confirmed",
                            max(0, int((time.monotonic() - started) * 1000)),
                        )
                    confirmed_payload: dict[str, Any] = {
                        "segment_index": 0,
                        "text": verification.answer,
                        "status": verification.status,
                        "evidence_refs": list(verification.evidence_refs),
                    }
                    if verification.answer != provisional_answer:
                        confirmed_payload.update(
                            {
                                "replace_start": 0,
                                "replace_end": len(provisional_answer),
                            }
                        )
                    yield frame("confirmed", confirmed_payload)
                answer_planning = await planning_metadata(planning_task)
                done_payload = build_done_payload(
                    verification=verification,
                    terminal_model=terminal_model,
                    terminal_router=terminal_router,
                    terminal_usage=terminal_usage,
                    evidence_fast_path=evidence_fast_path,
                    ontology_answer=ontology_answer,
                    health_answer=health_answer,
                    screen_answer=screen_answer,
                    concept_answer=concept_answer,
                    resource_answer=contextual_answer,
                    started=started,
                    delegation=delegation,
                    enriched_context=enriched_context,
                    answer_plan=answer_plan,
                    answer_planning=answer_planning,
                    quality=quality,
                    resource_context=response_resource_context(
                        enriched_context,
                        resource_context,
                    ),
                    model_trace=snapshot_model_trace(model_trace_scope.collector),
                    turn_timing=turn_timing.snapshot(),
                    trajectory_detail=None,
                )
                trajectory_detail_snapshot = trajectory_detail.snapshot(
                    max_bytes=trajectory_detail_budget(done_payload)
                )
                if trajectory_detail_snapshot is not None:
                    done_payload["trajectory_detail"] = trajectory_detail_snapshot
                if conversation_history_store is not None:
                    assistant_turn = await append_assistant_turn(
                        store=conversation_history_store,
                        principal_id=user_id,
                        conversation_id=session_id,
                        request_id=request_id,
                        content=verification.answer,
                        recorded_at=datetime.now(tz=UTC),
                        metadata=replay_metadata(
                            model=str(terminal_model or "unknown"),
                            payload=done_payload,
                            additional=_turn_metadata(
                                model=str(terminal_model or "unknown"),
                                view_context=enriched_context,
                                answer_planning=answer_planning,
                            ),
                        ),
                        ontology_projector=user_context_ontology_projector,
                    )
                    if post_turn_review_submitter is not None and operator_turn is not None:
                        post_turn_review_submitter.submit_nowait(
                            operator_turn=operator_turn,
                            assistant_turn=assistant_turn,
                            submission=PostTurnReviewSubmission(
                                validation_outcomes=(verification.status,),
                                evidence_refs=verification.evidence_refs,
                                explicit_corrections=explicit_corrections(clean_prompt),
                            ),
                        )
                await cleanup()
                if progress_metrics is not None:
                    progress_metrics.increment("terminal_completed")
                yield frame(
                    "done",
                    done_payload,
                )
            except ChatTurnInterruptedError:
                await cleanup()
                yield frame(
                    "interrupted",
                    {
                        "detail": "chat turn interrupted",
                        "session_id": session_id,
                    },
                )
            except ChatBackendUnavailableError:
                await cleanup()
                yield frame("error", {"detail": "chat backend not configured"})
            except HTTPException as exc:
                await cleanup()
                yield frame("error", {"detail": str(exc.detail)})
            except Exception as exc:  # noqa: BLE001 - surface as a stream error, never 500 mid-stream
                _LOG.warning("chat stream failed: %s", type(exc).__name__, exc_info=True)
                await cleanup()
                yield frame("error", {"detail": "chat stream failed"})
            finally:
                await cleanup()
                deactivate_model_trace(model_trace_scope)

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return Route(path, handler, methods=["POST"])
