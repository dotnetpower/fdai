"""Server-Sent Events delivery for read-only console chat."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route

from fdai.core.conversation.answer_plan import build_answer_plan
from fdai.core.conversation.answer_planning import AnswerPlanningResult
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
from fdai.delivery.read_api.routes.chat_evidence_enrichment import (
    AgentChatDelegate,
    ChatToolResolver,
    ChatWebSearchEvidenceResolver,
    OperationalEvidenceResolverProtocol,
    _delegation_summary,
    _retrieval_source_previews,
    _web_search_summary,
    _with_agent_evidence,
    _with_operational_evidence,
    _with_tool_evidence,
    _with_web_evidence,
)
from fdai.delivery.read_api.routes.chat_history import append_assistant_turn, append_operator_turn
from fdai.delivery.read_api.routes.chat_prompt import (
    _concept_answer,
    _response_locale,
    _with_concept_evidence,
)
from fdai.delivery.read_api.routes.chat_route_common import (
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_MAX_HISTORY_ITEMS,
    AnswerPreferenceResolver,
    AuthorizeFn,
    ModelPreferenceResolver,
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
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.providers.user_context import ConversationHistoryStore

_LOG = logging.getLogger(__name__)


DEFAULT_STREAM_PATH: Final[str] = "/chat/stream"


def make_chat_stream_route(
    *,
    backend: ChatBackend,
    authorize: AuthorizeFn,
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
        if conversation_history_store is not None:
            await append_operator_turn(
                store=conversation_history_store,
                principal_id=user_id,
                conversation_id=session_id,
                request_id=request_id,
                content=clean_prompt,
                recorded_at=datetime.now(tz=UTC),
                ontology_projector=user_context_ontology_projector,
            )

        async def event_source() -> AsyncIterator[bytes]:
            nonlocal answer_plan
            started = time.monotonic()
            sequence = 0
            revision = 0
            planning_task: asyncio.Task[AnswerPlanningResult] | None = None

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

            try:
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
                enriched_context = await _with_tool_evidence(
                    clean_prompt,
                    enriched_context,
                    tool_resolver,
                )
                enriched_context = await _with_operational_evidence(
                    clean_prompt, enriched_context, evidence_resolver
                )
                enriched_context = await _with_agent_evidence(
                    clean_prompt,
                    enriched_context,
                    agent_delegate,
                    user_id=user_id,
                    session_id=session_id,
                )
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
                yield frame(
                    "status",
                    {
                        "phase": "generating",
                        "label": (
                            "Evidence ready; composing bounded answer"
                            if evidence_fast_path or health_answer is not None
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
                    async for event in _with_sse_heartbeats(
                        upstream, interval=DEFAULT_STREAM_HEARTBEAT_S
                    ):
                        if event is None:
                            # Idle keep-alive: nothing arrived in the last
                            # `interval` seconds - emit a comment frame so
                            # proxies do not drop the connection while the
                            # reasoning model is still thinking.
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
                else:
                    if isinstance(backend, LatencyRoutedChatBackend):
                        reply = await backend.answer(
                            prompt=clean_prompt,
                            view_context=enriched_context,
                            history=history,
                            preferred_model=preferred_model,
                        )
                    else:
                        reply = await backend.answer(
                            prompt=clean_prompt,
                            view_context=enriched_context,
                            history=history,
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
                if conversation_history_store is not None:
                    await append_assistant_turn(
                        store=conversation_history_store,
                        principal_id=user_id,
                        conversation_id=session_id,
                        request_id=request_id,
                        content=verification.answer,
                        recorded_at=datetime.now(tz=UTC),
                        metadata=_turn_metadata(
                            model=str(terminal_model or "unknown"),
                            view_context=enriched_context,
                            answer_planning=answer_planning,
                        ),
                        ontology_projector=user_context_ontology_projector,
                    )
                yield frame(
                    "done",
                    {
                        "answer": verification.answer,
                        "model": terminal_model,
                        "router": terminal_router,
                        "usage": terminal_usage,
                        "source": (
                            f"evidence:{verification.status}"
                            if evidence_fast_path
                            else (
                                "evidence:system-health"
                                if health_answer is not None
                                else (
                                    "evidence:fdai-glossary" if concept_answer is not None else None
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
                    },
                )
            except ChatBackendUnavailableError:
                yield frame("error", {"detail": "chat backend not configured"})
            except HTTPException as exc:
                yield frame("error", {"detail": str(exc.detail)})
            except Exception as exc:  # noqa: BLE001 - surface as a stream error, never 500 mid-stream
                _LOG.warning("chat stream failed: %s", type(exc).__name__, exc_info=True)
                yield frame("error", {"detail": "chat stream failed"})
            finally:
                await cancel_planning(planning_task)

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return Route(path, handler, methods=["POST"])
