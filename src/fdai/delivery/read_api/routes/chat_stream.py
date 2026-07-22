"""Server-Sent Events delivery for read-only console chat."""

from __future__ import annotations

import asyncio
import json
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

from fdai.core.conversation.answer_plan import build_answer_plan
from fdai.core.conversation.answer_planning import AnswerPlanningResult
from fdai.core.conversation.busy_input_coordinator import BusyInputCoordinator
from fdai.core.metering import InvocationScope, with_invocation_scope
from fdai.core.python_task.grounded_code import extract_grounded_code
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.read_api.routes.chat_answer_planning import (
    AnswerPlanningDelegate,
    cancel_planning,
    planning_metadata,
    start_shadow_answer_planning,
)
from fdai.delivery.read_api.routes.chat_backend_common import (
    ChatBackend,
    ChatBackendUnavailableError,
    _reject_direct_override,
)
from fdai.delivery.read_api.routes.chat_backend_router import LatencyRoutedChatBackend
from fdai.delivery.read_api.routes.chat_busy_input import (
    MAX_STEER_RERUNS,
    ChatTurnInterruptedError,
    answer_with_busy_input,
    append_next_steer,
    interruptible_events,
)
from fdai.delivery.read_api.routes.chat_evidence_enrichment import (
    AgentChatDelegate,
    ChatBehaviorEvidenceResolver,
    ChatToolResolver,
    ChatWebSearchEvidenceResolver,
    OperationalEvidenceResolverProtocol,
    _delegation_summary,
    _retrieval_source_previews,
    _web_search_summary,
    _with_agent_evidence,
    _with_behavior_evidence,
    _with_operational_evidence,
    _with_tool_evidence,
    _with_web_evidence,
)
from fdai.delivery.read_api.routes.chat_history import (
    append_assistant_turn,
    append_operator_turn,
    completed_replay_payload,
    replay_metadata,
)
from fdai.delivery.read_api.routes.chat_prompt import (
    _concept_answer,
    _ontology_browse_answer,
    _response_locale,
    _with_concept_evidence,
)
from fdai.delivery.read_api.routes.chat_route_common import (
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_MAX_HISTORY_ITEMS,
    AnswerPreferenceResolver,
    AuthorizeFn,
    ModelPreferenceResolver,
    _conversation_context,
    _metering_correlation_id,
    _request_id,
    _session_id,
    _turn_metadata,
    _uses_evidence_fast_path,
    _with_compiled_user_policy,
)
from fdai.delivery.read_api.routes.chat_stream_protocol import (
    DEFAULT_STREAM_HEARTBEAT_S,
    _chunk_answer_for_stream,
    _sse,
    _sse_heartbeat,
    _with_sse_heartbeats,
)
from fdai.delivery.read_api.routes.chat_system_health import render_system_health_answer
from fdai.delivery.read_api.routes.chat_verification import verify_answer
from fdai.delivery.read_api.routes.post_turn_review import (
    PostTurnReviewSubmission,
    PostTurnReviewSubmitter,
    explicit_corrections,
)
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.providers.user_context import ConversationHistoryStore, UserContextConflictError
from fdai.shared.telemetry.correlation import with_correlation

_LOG = logging.getLogger(__name__)


DEFAULT_STREAM_PATH: Final[str] = "/chat/stream"


def make_chat_stream_route(
    *,
    backend: ChatBackend,
    authorize: AuthorizeFn,
    behavior_resolver: ChatBehaviorEvidenceResolver | None = None,
    evidence_resolver: OperationalEvidenceResolverProtocol | None = None,
    tool_resolver: ChatToolResolver | None = None,
    web_search_resolver: ChatWebSearchEvidenceResolver | None = None,
    agent_delegate: AgentChatDelegate | None = None,
    answer_planning_delegate: AnswerPlanningDelegate | None = None,
    conversation_policy_store: ConversationPolicyStore | None = None,
    conversation_history_store: ConversationHistoryStore | None = None,
    user_context_ontology_projector: UserContextOntologyProjector | None = None,
    model_preference_resolver: ModelPreferenceResolver | None = None,
    answer_preference_resolver: AnswerPreferenceResolver | None = None,
    post_turn_review_submitter: PostTurnReviewSubmitter | None = None,
    busy_input_coordinator: BusyInputCoordinator | None = None,
    path: str = DEFAULT_STREAM_PATH,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
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
        user_id = await authorize(request)
        preferred_model = (
            await model_preference_resolver(user_id)
            if model_preference_resolver is not None
            else None
        )
        answer_preferences = (
            await answer_preference_resolver(user_id)
            if answer_preference_resolver is not None
            else None
        )

        declared_len = request.headers.get("content-length")
        if declared_len is not None:
            try:
                if int(declared_len) > max_body_bytes:
                    raise HTTPException(status_code=413, detail="chat body too large")
            except ValueError:
                pass
        body_bytes = await request.body()
        if len(body_bytes) > max_body_bytes:
            raise HTTPException(status_code=413, detail="chat body too large")
        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="chat body MUST be JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="chat body MUST be a JSON object")
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise HTTPException(status_code=400, detail="prompt MUST be a non-empty string")
        view_context = body.get("view_context")
        if view_context is None:
            view_context = {}
        if not isinstance(view_context, dict):
            raise HTTPException(status_code=400, detail="view_context MUST be an object")
        view_context.pop("_answer_plan", None)
        conversation_context = _conversation_context(body)
        history_raw = body.get("history", [])
        if not isinstance(history_raw, list):
            raise HTTPException(status_code=400, detail="history MUST be a list")
        if len(history_raw) > DEFAULT_MAX_HISTORY_ITEMS:
            raise HTTPException(status_code=400, detail="history exceeds cap")
        history: list[dict[str, str]] = []
        for turn in history_raw:
            if isinstance(turn, dict):
                role = turn.get("role")
                content = turn.get("content")
                if isinstance(role, str) and isinstance(content, str):
                    history.append({"role": role, "content": content})

        clean_prompt = prompt.strip()
        _reject_direct_override(clean_prompt)
        answer_plan = build_answer_plan(
            clean_prompt,
            route_id=str(view_context.get("routeId") or "") or None,
            preferences=answer_preferences,
        )
        view_context["_answer_plan"] = answer_plan.to_dict()
        session_id = _session_id(body)
        request_id = _request_id(body)
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
            started = time.monotonic()
            sequence = 0
            revision = 0
            planning_task: asyncio.Task[AnswerPlanningResult] | None = None
            cleanup_complete = False

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
                    await cleanup()
                    yield frame("done", completed_payload)
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
                enriched_context = await _with_compiled_user_policy(
                    view_context,
                    user_id=user_id,
                    store=conversation_policy_store,
                )
                enriched_context = await _with_behavior_evidence(
                    clean_prompt,
                    enriched_context,
                    behavior_resolver,
                )
                tool_progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)

                async def observe_tool_progress(event: Mapping[str, Any]) -> None:
                    await tool_progress_queue.put(dict(event))

                tool_task = asyncio.create_task(
                    _with_tool_evidence(
                        clean_prompt,
                        enriched_context,
                        tool_resolver,
                        principal_id=user_id,
                        progress_observer=observe_tool_progress,
                    )
                )
                try:
                    while not tool_task.done() or not tool_progress_queue.empty():
                        try:
                            progress_event = await asyncio.wait_for(
                                tool_progress_queue.get(),
                                timeout=0.25,
                            )
                        except TimeoutError:
                            continue
                        event_name = progress_event.pop("event", None)
                        if event_name in {"activity", "milestone"}:
                            yield frame(event_name, progress_event)
                    enriched_context = await tool_task
                finally:
                    if not tool_task.done():
                        tool_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await tool_task
                enriched_context = await _with_operational_evidence(
                    clean_prompt,
                    enriched_context,
                    evidence_resolver,
                    conversation_context=conversation_context,
                )
                progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=32)

                async def observe_agent_progress(event: Mapping[str, Any]) -> None:
                    await progress_queue.put(dict(event))

                agent_task = asyncio.create_task(
                    _with_agent_evidence(
                        clean_prompt,
                        enriched_context,
                        agent_delegate,
                        user_id=user_id,
                        session_id=session_id,
                        progress_observer=observe_agent_progress,
                    )
                )
                try:
                    while not agent_task.done() or not progress_queue.empty():
                        try:
                            progress_event = await asyncio.wait_for(
                                progress_queue.get(),
                                timeout=0.25,
                            )
                        except TimeoutError:
                            continue
                        event_name = progress_event.pop("event", None)
                        if event_name in {"activity", "milestone"}:
                            yield frame(event_name, progress_event)
                    enriched_context = await agent_task
                finally:
                    if not agent_task.done():
                        agent_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await agent_task
                enriched_context = _with_concept_evidence(clean_prompt, enriched_context)
                enriched_context = await _with_web_evidence(
                    clean_prompt,
                    enriched_context,
                    web_search_resolver,
                )
                answer_plan, planning_task = start_shadow_answer_planning(
                    prompt=clean_prompt,
                    plan=answer_plan,
                    delegate=answer_planning_delegate,
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
                yield frame(
                    "status",
                    {
                        "phase": "generating",
                        "label": (
                            "Evidence ready; composing bounded answer"
                            if evidence_fast_path
                            or ontology_answer is not None
                            or health_answer is not None
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

                stream = getattr(backend, "answer_stream", None)
                provisional_answer = ""
                terminal_model: Any = None
                terminal_router: Any = None
                terminal_usage: Any = None
                if evidence_fast_path:
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
                elif concept_answer is not None:
                    provisional_answer = concept_answer
                    terminal_model = "concept-glossary"
                    for chunk in _chunk_answer_for_stream(provisional_answer):
                        yield frame("token", {"delta": chunk})
                elif stream is not None:
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
                yield frame(
                    "provisional",
                    {
                        "answer": provisional_answer,
                        "model": terminal_model,
                        "generation_ms": generation_ms,
                    },
                )
                verification = verify_answer(
                    provisional_answer,
                    enriched_context,
                    locale=_response_locale(clean_prompt, enriched_context),
                )
                yield frame(
                    "verification",
                    {
                        "phase": "verifying",
                        "label": "Verifying answer against evidence",
                        "completed": 0,
                        "total": verification.checks_total,
                    },
                )
                yield frame(
                    "verification",
                    {
                        "phase": verification.status,
                        "label": f"Verification {verification.status}",
                        "completed": verification.checks_completed,
                        "total": verification.checks_total,
                        "authority": verification.authority,
                        "evidence_refs": list(verification.evidence_refs),
                        "reason_code": verification.reason_code,
                    },
                )
                if verification.answer != provisional_answer:
                    revision += 1
                    yield frame(
                        "revision",
                        {
                            "answer": verification.answer,
                            "replaces_revision": revision - 1,
                            "status": verification.status,
                            "reason_code": verification.reason_code,
                            "evidence_refs": list(verification.evidence_refs),
                        },
                    )
                answer_planning = await planning_metadata(planning_task)
                done_payload = {
                    "answer": verification.answer,
                    "model": terminal_model,
                    "router": terminal_router,
                    "usage": terminal_usage,
                    "source": (
                        f"evidence:{verification.status}"
                        if evidence_fast_path
                        else (
                            "evidence:ontology-snapshot"
                            if ontology_answer is not None
                            else (
                                "evidence:system-health"
                                if health_answer is not None
                                else (
                                    "evidence:fdai-glossary" if concept_answer is not None else None
                                )
                            )
                        )
                    ),
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "verification": verification.to_dict(),
                    "delegation": delegation,
                    "web_search": _web_search_summary(enriched_context),
                    "answer_plan": answer_plan.to_dict(),
                    "answer_planning": answer_planning,
                    "code_artifacts": [
                        artifact.to_dict()
                        for artifact in extract_grounded_code(verification.answer)
                    ],
                }
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

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return Route(path, handler, methods=["POST"])
